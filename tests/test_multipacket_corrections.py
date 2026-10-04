"""Offline regressions for composition failures, evidence guards and call accounting."""
import json
from copy import deepcopy
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch

from experiments.multipacket_v1 import arms
from experiments.multipacket_v1.report import metrics
from experiments.multipacket_v1 import report as reporting
from experiments.multipacket_v1.run import slim_step
from experiments.multipacket_v1.syn_strata import original_evidence_coverage
from guardian_truth.evidence_packer import PackerConfig, pack
from guardian_truth.multipacket import Controller, Question, complementary, resolve_global, unify
from guardian_truth.multipacket.packets import reference_spans_covered
from guardian_truth.multipacket.ledger import Ledger
from tests.test_multipacket import long_row
from tests.test_evidence_packer import row as synthetic_row, CALL


def first(decision='ERROR', admitted=True):
    return dict(kind='decision', decision=decision if admitted else None,
                admitted=dict(decision=decision) if admitted else None,
                admission='ADMITTED' if admitted else 'REJECTED:NORM_REFERENCE_INVALID',
                attempted=True, cached=False, usage=dict(prompt_tokens=10, completion_tokens=2))


def test_independent_complement_keeps_policy_within_budget_and_original_ids():
    row = long_row()
    a = pack(row, PackerConfig(budget_bytes=6000))
    evidence_only = complementary(row, a, 6000)
    p2 = complementary(row, a, 6000, shared_normative=True)
    assert not any(s['category'] == 'POLICY' for s in evidence_only['read_sources'])
    assert any(s['category'] == 'POLICY' for s in p2['read_sources'])
    assert p2['cost']['source_token_upper_bound'] <= 6000
    assert set(p2['selected_units']) - set(a['selected_units'])
    (u1, u2), _ = unify(row, [a, p2])
    assert resolve_global([u1, u2], row)


def test_global_resolver_rejects_cross_category_and_metadata_tampering():
    row = long_row()
    a = pack(row, PackerConfig(budget_bytes=6000))
    (packet,), _ = unify(row, [a])
    for container, choose, fields in [
        ('read_sources', lambda r: r['category'] == 'POLICY', {'role': 'user', 'category': 'HISTORY', 'tool': 'fake'}),
        ('current_targets', lambda r: True, {'role': 'user', 'category': 'DECLARATION', 'kind': 'text'}),
        ('declarations', lambda r: True, {'role': 'user', 'category': 'POLICY', 'kind': 'text'}),
    ]:
        index = next(i for i, record in enumerate(packet[container]) if choose(record))
        for field, value in {**fields, 'parent_source_id': 'h9999', 'event': -1, 'sha256': 'invalid'}.items():
            bad = deepcopy(packet)
            bad[container][index][field] = value
            try:
                resolve_global([bad], row)
            except ValueError:
                pass
            else:
                raise AssertionError(f'{container} tamper accepted: {field}')


def test_reference_completeness_requires_full_union_with_no_gaps():
    reference = dict(required_normative_sources=[dict(document='prompt', start=10, end=30)],
                     required_history_sources=[])
    def view(intervals):
        return dict(read_sources=[dict(document='prompt', start=a, end=b) for a, b in intervals],
                    current_targets=[], declarations=[])
    partial = reference_spans_covered(reference, view([(10, 11)]))
    assert partial['norm_overlap_found'] == 1 and partial['norm_found'] == 0 and not partial['complete']
    assert not reference_spans_covered(reference, view([(10, 20), (21, 30)]))['complete']
    assert reference_spans_covered(reference, view([(10, 20), (20, 30)]))['complete']


def test_same_origin_ledger_promotion_preserves_both_statuses():
    ledger = Ledger()
    ledger.edge('claim', 'norm', 'INVOKES', 'SEMANTIC_HYPOTHESIS', 'round1')
    ledger.promote('claim', 'norm', 'INVOKES', 'VERIFIED_SEMANTIC', 'round1')
    ledger.promote('claim', 'norm', 'INVOKES', 'VERIFIED_SEMANTIC', 'round1')
    assert [edge.status for edge in ledger.edges] == ['SEMANTIC_HYPOTHESIS', 'VERIFIED_SEMANTIC']


def test_full_ctrl_makes_only_the_first_call():
    with patch.object(arms, 'first_pass', return_value=({'mode': 'FULL_INPUT'}, first())) as call:
        result = arms.arm_CTRL({})
    assert call.call_count == 1
    assert len(result['steps']) == 1


def test_first_pass_does_not_reuse_old_reply_for_changed_request():
    packet = dict(mode='SELECTED')
    frozen = dict(first(), request_sha256='old-packet-hash')
    with patch.object(arms, 'pack', return_value=packet), patch.object(arms, 'baseline_reply', return_value=frozen), \
            patch.object(arms, 'rp', return_value={}), patch.object(arms, 'body', return_value={'new': 'packet'}), \
            patch.object(arms, 'decide', return_value=first('NO_ERROR')) as decide:
        _, step = arms.first_pass({'id': 'known-row'})
    assert decide.call_count == 1 and step['decision'] == 'NO_ERROR'


def test_shared_anchors_do_not_count_as_new_evidence_for_c1_or_d():
    a = dict(mode='SELECTED', selected_units=['h1', 'p1'])
    p2 = dict(selected_units=['h1', 'p1'])
    with patch.object(arms, 'first_pass', return_value=(a, first())), \
            patch.object(arms, 'complementary', return_value=p2), \
            patch.object(arms, 'gap_packet', return_value=p2), \
            patch.object(arms, 'decide', side_effect=AssertionError('no new units must not call')):
        for result in (arms.arm_C1({}), arms.arm_D({}, 'D1'), arms.arm_D({}, 'D2')):
            assert result['degenerate'] == 'NO_NEW_EVIDENCE'
            assert result['decision'] == 'ERROR'
            assert len(result['steps']) == 1


def test_rejected_secondary_retains_only_admitted_vote_without_adjudication():
    a, failed = first(), first(admitted=False)
    with patch.object(arms, 'decide', side_effect=AssertionError('null is not a disagreement')):
        final, adj = arms._aggregate({}, {}, a, failed, {}, {}, 'test')
        assert final == 'ERROR' and adj is None
        assert arms._aggregate({}, {}, failed, failed, {}, {}, 'test') == (None, None)
    result = arms.result(final, [a, failed], **arms.aggregation_info(a, failed, adj))
    assert result['aggregate_status'] == 'PARTIAL_ADMISSION'
    assert result['decision_owner'] == 'review_1'
    assert result['fallback_used'] and result['stage_failure']
    assert result['final_status'] == 'FALLBACK'
    assert not result['composition_complete']
    assert result['binary_projection'] == 1


def test_no_policy_or_target_skips_impossible_schema_before_call():
    for packet, reason in [(dict(current_targets=[{}], normative_sources=[]), 'NO_POLICY_RETRIEVED'),
                           (dict(current_targets=[], normative_sources=[{}]), 'NO_CURRENT_TARGET')]:
        with patch.object(arms, 'rp', return_value=packet), \
                patch.object(arms, 'call', side_effect=AssertionError('prerequisite missing')):
            step = arms.decide({}, {})
        assert step['admission'] == 'SKIPPED:' + reason
        assert step['decision'] is None and step['attempted'] is False


def test_normalized_duplicates_retrieve_once_even_when_both_initial():
    controller = Controller(long_row(), max_hops=10, max_chars=100000)
    questions = [Question('order status delivered', 'test'), Question('order  status delivered', 'test')]
    with patch.object(controller, 'retrieve_relevant', return_value=[]) as retrieve:
        controller.explore(questions)
    assert retrieve.call_count == 1
    assert controller.hops == 1


def test_g4_does_not_qa_an_exhausted_followup_round():
    class Search:
        def __init__(self, *args, **kwargs):
            self.selected, self.trace = [], []
        def explore(self, questions):
            if not self.selected:
                self.selected.append('h1')
        def summary(self):
            return {'selected_units': self.selected}
    reply = first()
    reply['admitted'].update(open_questions=['initial question'])
    packet = dict(mode='SELECTED', selected_units=[], read_sources=[], current_targets=[], declarations=[])
    answer = dict(kind='qa', admission='ADMITTED', answers=[dict(question_index=0, status='UNKNOWN',
                  finding='uncertain', source_refs=[], follow_up_questions=['follow-up'])])
    with patch.object(arms, 'first_pass', return_value=(packet, reply)), \
            patch.object(arms, 'Controller', Search), patch.object(arms, 'claim', return_value={}), \
            patch.object(arms, 'claim_records', return_value=[]), \
            patch.object(arms, 'units_records', return_value=[]), patch.object(arms, 'compose', return_value=packet), \
            patch.object(arms, 'ledger_json', return_value=[]), patch.object(arms, 'qa', return_value=answer) as qa, \
            patch.object(arms, 'decide', return_value=first()):
        result = arms.arm_G4({}, 'S', use_scan=False)
    assert qa.call_count == 1
    assert result['qa_rounds'] == 1


def test_failed_final_call_usage_and_raw_rejection_survive_metrics_and_runner():
    failed = first(admitted=False)
    failed.update(raw_content='{"decision":"ERROR"}', parsed=dict(decision='ERROR'), raw_decision='ERROR')
    rec = dict(id='x', arm='C1', decision=None, steps=[first(), failed])
    report = metrics({'x': rec}, {'x': dict(label=1)}, ['x'], {})
    assert report['tech'] == 1 and report['fn'] == 1
    assert report['rejected_stages'] == 1 and report['rows_with_stage_failure'] == 1
    assert report['reviewer_calls_per_row'] == 2 and report['paid_calls_per_row'] == 2
    assert report['prompt_tokens_per_row'] == report['paid_prompt_tokens_per_row'] == 20
    assert report['reason_is_source_proof'] is False and 'PROXY' in report['reason_contract']
    slim = slim_step(failed)
    assert slim['raw_decision'] == 'ERROR' and slim['decision'] is None
    assert slim['parsed'] == {'decision': 'ERROR'} and slim['raw_content']


def test_retried_records_preserve_prior_attempt_costs_without_extra_predictions():
    failed = dict(first(admitted=False), admission='TRANSPORT_FAILURE', usage=None, cached=False)
    success = first('NO_ERROR')
    records = [dict(id='x', arm='A', decision=None, steps=[failed], retryable=True),
               dict(id='x', arm='A', decision='NO_ERROR', steps=[success], retryable=False)]
    with TemporaryDirectory() as temporary:
        out = Path(temporary)
        path = out / 'runs/test/run1/A.jsonl'
        path.parent.mkdir(parents=True)
        path.write_text('\n'.join(json.dumps(r) for r in records))
        with patch.object(reporting, 'OUT', out):
            loaded = reporting.load('test', 1, 'A')
    metrics = reporting.metrics(loaded, {'x': dict(label=0)}, ['x'], {})
    assert metrics['tn'] == 1 and metrics['tech'] == 0
    assert metrics['paid_calls_per_row'] == 1 and metrics['uncached_calls_per_row'] == 2
    assert metrics['transport_failures'] == 1 and metrics['uncached_calls_without_usage'] == 1


def test_decide_records_raw_verdict_when_schema_admission_rejects_it():
    raw = '{"decision":"ERROR"}'
    response = dict(key='fake', content=raw, cached=False, usage=dict(prompt_tokens=12))
    packet = dict(current_targets=[{}], normative_sources=[{}])
    trace = []
    token = arms.ATTEMPTS.set(trace)
    try:
        with patch.object(arms, 'rp', return_value=packet), patch.object(arms, 'body', return_value={}), \
                patch.object(arms, 'call', return_value=response):
            step = arms.decide({}, {})
    finally:
        arms.ATTEMPTS.reset(token)
    assert step['admission'].startswith('REJECTED:')
    assert step['raw_decision'] == 'ERROR' and step['decision'] is None
    assert step['raw_content'] == raw and trace == [step]


def test_fallback_decision_is_distinct_from_failed_final_admission():
    failed = first(admitted=False)
    result = arms.result('ERROR', [first(), failed])
    assert result['fallback_used'] and result['fallback_decision'] == 'ERROR'
    assert result['admitted_final_decision'] is None
    assert result['decision_owner'] == 'step_0'
    assert not result['composition_complete']


def test_source_value_coverage_requires_original_result_tool_token_and_span():
    row = long_row()
    packet = pack(row, PackerConfig(budget_bytes=None))
    mutation = dict(old='W0000007', operator='CALL_ARG_ID', tool='return_order')
    check = original_evidence_coverage(row, packet, mutation)
    assert check['covered']
    assert check['covered_evidence'][0]['tool'] == 'get_order'
    # A tool-name mismatch disqualifies FACT evidence even if the token occurs.
    assert not original_evidence_coverage(row, packet, dict(mutation, operator='FACT_ID'))['covered']
    metadata_only = dict(packet, read_sources=[dict(s, text=s['text'].replace('W0000007', 'W0000700'))
                                             for s in packet['read_sources']])
    assert not original_evidence_coverage(row, metadata_only, mutation)['covered']
    assert not original_evidence_coverage(row, packet, dict(mutation, old='0000007'))['covered']


def test_numeric_source_coverage_uses_decimal_equality_not_prefix_matches():
    mutation = dict(old='89', operator='FACT_NUMBER', tool='get_order')
    for value, expected in [('89.5', False), ('89.0', True), ('89.00', True), ('-89.0', False), ('189', False)]:
        history = '⟦ASSISTANT · ход 3⟧\n\t← TOOL_RESPONSE get_order: {"amount": ' + value + '}\n'
        row = synthetic_row(CALL, history)
        packet = pack(row, PackerConfig(budget_bytes=None))
        check = original_evidence_coverage(row, packet, mutation)
        assert check['covered'] is expected, value
    decimal_row = synthetic_row(CALL, '⟦ASSISTANT · ход 3⟧\n\t← TOOL_RESPONSE get_order: {"amount": 89.500}\n')
    assert original_evidence_coverage(decimal_row, pack(decimal_row, PackerConfig(budget_bytes=None)),
                                      dict(mutation, old='89.5'))['covered']
