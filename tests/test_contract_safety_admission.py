"""Independent-item admission and queue contrasts through the real input parser.

Boundary clients are deterministic wire fixtures, not claims about model quality.
"""
import json
from unittest.mock import patch

import pytest

from guardian_truth.integrated.transport import sha
from guardian_truth.repair import v5
from guardian_truth.verification.common import call, request, schema_errors
from guardian_truth.verification.pipeline import packet_for
from guardian_truth.v6fix import turnrules
from guardian_truth.integrated import ReviewConfig, review, reviewer
from guardian_truth.integrated.pipeline import _step
from guardian_truth.verification.admission import interpret_receipt_v2, interpret_v2


class ReplyClient:
    def __init__(self, value, finish_reason='stop'):
        self.value, self.finish_reason, self.calls = value, finish_reason, []

    def call(self, req, attempt=0, tag=''):
        self.calls.append((req, attempt, tag))
        return dict(content=json.dumps(self.value), finish_reason=self.finish_reason,
                    transport={'status': 'OK'}, key='test', cached=False)


def primary_example():
    row = dict(prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.', response='⟦ASSISTANT · ход 1⟧\nFORBIDDEN')
    packet = packet_for(row, 20000)
    tid, sid = packet['current_targets'][0]['source_id'], packet['normative_sources'][0]['source_id']
    value = dict(decision='ERROR', regulated_action=dict(target_id=tid, description='Current assertion'),
                 applicable_norms=[dict(policy_source_id=sid, interpretation='Forbidden word', modality='FORBID')],
                 supporting_evidence=[dict(source_id=tid, actor='assistant', role='action', fact='FORBIDDEN')],
                 exception_analysis='None', reason='Forbidden word written.', open_questions=[])
    return row, packet, value


class ReceiptClient(ReplyClient):
    def __init__(self, value, status, finish_reason):
        super().__init__(value, finish_reason)
        self.status = status

    def call(self, req, attempt=0, tag=''):
        return dict(super().call(req, attempt=attempt, tag=tag), transport={'status': self.status})


@pytest.mark.parametrize('status,finish', [(429, 'stop'), (200, 'error')])
@pytest.mark.parametrize('admission', ['v1', 'v2'])
def test_primary_step_and_public_review_preserve_failed_receipt_without_deciding(status, finish, admission):
    row, packet, value = primary_example()
    client = ReceiptClient(value, status, finish)
    cfg = ReviewConfig.profile('guard', model='test', admission=admission)
    req = reviewer.body(packet, 'mistral', 'test')
    step = _step(client, req, packet, cfg, 'review')
    assert step['decision'] is None and step['admitted'] is None
    assert step['raw_content'] == json.dumps(value)
    assert step['transport']['status'] == status and step['finish_reason'] == finish
    assert step['schema_validation']['status'] == 'TRANSPORT_FAILURE'
    public = review(row['prompt'], row['response'], cfg, client=client)
    assert public['binary'] == 0 and public['final_decision'] is None
    assert public['projection'] == 'TECHNICAL_NULL_PROJECTED_0'


@pytest.mark.parametrize('status,finish', [(429, 'stop'), (200, 'error')])
def test_readmission_cannot_strip_failed_primary_receipt_metadata(status, finish):
    row, packet, value = primary_example()
    client = ReceiptClient(value, status, finish)
    rec = v5.run_v5(row, client, flags=v5.FIXES, model='test')
    assert not rec['base_error'] and rec['A_adm2']['decision'] is None
    assert rec['A_adm2']['admission'] in ('TRANSPORT_FAILURE', 'COMPLETION_FAILURE')
    assert v5.decide(rec)[0] == 0
    raw = json.dumps(value)
    # Raw-only parsing is deliberately separate; every receipt-aware caller
    # must retain the known failure, including old raw-content step receipts.
    assert interpret_v2(raw, packet)['decision'] == 'ERROR'
    for receipt in (dict(content=raw, transport={'status': status}, finish_reason=finish),
                    dict(raw_content=raw, transport={'status': status}, finish_reason=finish)):
        result = interpret_receipt_v2(receipt, packet)
        assert result['decision'] is None and result['admitted'] is None


@pytest.mark.parametrize('finish', ['stop', 'length'])
def test_successful_complete_primary_contract_still_decides(finish):
    row, packet, value = primary_example()
    client = ReceiptClient(value, 200, finish)
    public = review(row['prompt'], row['response'], ReviewConfig(model='test'), client=client)
    assert public['binary'] == 1 and public['final_decision'] == 'ERROR'
    assert interpret_receipt_v2(dict(content=json.dumps(value), transport={'status': 200}, finish_reason=finish), packet)['decision'] == 'ERROR'


@pytest.mark.parametrize('runner_name', ['pipeline', 'v3', 'v4', 'second', 'confirm'])
@pytest.mark.parametrize('status,finish', [(429, 'stop'), (200, 'error')])
def test_other_receipt_aware_entrypoints_share_the_failure_gate(runner_name, status, finish):
    from guardian_truth.verification import pipeline, v3, v4, second
    from guardian_truth.v6 import confirm
    row, packet, value = primary_example()
    client = ReceiptClient(value, status, finish)
    if runner_name == 'second':
        result = second.run(client, packet, 'mistral', 'test')
        assert result['decision'] is None and result['candidate'] is None
        assert result['raw_content'] == json.dumps(value)
    elif runner_name == 'confirm':
        result = confirm.recheck(client, packet, 'Prior accusation', dict(ask='h0', user='h1'), 'mistral', 'test')
        assert result['decision'] is None
    else:
        if runner_name == 'pipeline':
            result = pipeline.run_row(row, client, model='test', mechanisms=())
        elif runner_name == 'v3':
            result = v3.run_v3(row, client, model='test', components=())
        else:
            result = v4.run_v4(row, client, model='test', components=())
        assert result['A_adm2']['decision'] is None
        assert result['A_adm2']['admission'] in ('TRANSPORT_FAILURE', 'COMPLETION_FAILURE')


def example():
    policy = 'Never call lookup with order_id forbidden-9.'
    row = dict(prompt='⟦SYSTEM⟧\n' + policy + '\n⟦USER⟧\nLook up another order.',
               response='⟦ASSISTANT · ход 1⟧\n→ TOOL_CALL lookup: {"order_id":"forbidden-9"}\n'
                        '→ TOOL_CALL lookup: {"order_id":"allowed-2"}')
    packet = packet_for(row, 400000)
    assert packet and len(packet['current_targets']) == 2
    sid = next(s['source_id'] for s in packet['normative_sources'] if policy in s['text'])
    tid = packet['current_targets'][0]['source_id']
    quote = packet['current_targets'][0]['text']
    item = dict(target_id=tid, policy_source_ids=[sid], policy_quote=policy,
                evidence=[dict(source_id=tid, quote=quote)], reason='Forbidden ID requested.', status='ERROR')
    candidate = dict(origin='AT', target_id=tid, requirement=policy, reason=item['reason'],
                     policy_source_ids=[sid], evidence_source_ids=[tid], code_proven=False, certificate=False)
    return row, packet, item, candidate


@pytest.mark.parametrize('mutation', [
    lambda x: {k: v for k, v in x.items() if k != 'analysis'},
    lambda x: dict(x, verdict='MAYBE'),
    lambda x: dict(x, analysis=12),
    lambda x: dict(x, extra='not in schema'),
])
def test_verifier_never_supports_schema_invalid_complete_json(mutation):
    _, packet, item, candidate = example()
    value = mutation(dict(policy_quote=item['policy_quote'], evidence_quote=item['evidence'][0]['quote'],
                          analysis='Directly forbidden.', verdict='SUPPORTED'))
    client = ReplyClient(value, finish_reason='length')
    result = v5.verify(client, packet, candidate, 'test', 0, 'verify', v5.FIXES)
    assert result['verification_status'] == 'TECHNICAL_FAILURE'
    assert result['verdict'] is None
    assert result['schema_validation']['status'] == 'INVALID_SCHEMA'
    assert len(client.calls) == 2  # bounded existing decoding retry protocol


def test_fully_valid_length_finish_and_single_whole_fence_are_not_truncated_json():
    _, packet, item, candidate = example()
    value = dict(policy_quote=item['policy_quote'], evidence_quote=item['evidence'][0]['quote'],
                 analysis='Directly forbidden.', verdict='SUPPORTED')
    result = v5.verify(ReplyClient(value, finish_reason='length'), packet, candidate, 'test', 0, 'verify', v5.FIXES)
    assert result['verification_status'] == 'SUPPORTED'
    req = request('test', '', {}, {'type': 'object', 'required': ['ok'], 'properties': {'ok': {'type': 'boolean'}}}, 'fixture')
    client = ReplyClient({})
    client.call = lambda *a, **kw: dict(content='```json\n{"ok":true}\n```')
    rec, value, norm = call(client, req, 0, 'fixture')
    assert value == {'ok': True} and norm == 'FENCE_STRIPPED'
    assert rec['schema_validation']['status'] == 'VALID'


def test_malformed_f_extraction_is_typed_failure_instead_of_keyerror():
    _, packet, _, _ = example()
    client = ReplyClient(dict(rules=[dict(type='MAX_TOOL_CALLS_PER_TURN', n=1)]))
    extraction = turnrules.extract(client, 'test', packet['normative_sources'])
    bound = turnrules.bind(extraction, packet['normative_sources'])
    assert bound == []


def test_json_schema_numeric_boolean_and_nested_array_contracts():
    schema = {'type': 'object', 'additionalProperties': False, 'required': ['items'],
              'properties': {'items': {'type': 'array', 'maxItems': 1,
                                      'items': {'type': 'integer', 'minimum': 0}}}}
    assert not schema_errors({'items': [0]}, schema)
    for invalid in ({'items': [True]}, {'items': [-1]}, {'items': [0, 1]}, {'items': None}, {'items': [], 'extra': 1}):
        assert schema_errors(invalid, schema)


def test_local_at_violation_survives_missing_other_target_without_claiming_complete_coverage():
    _, packet, item, _ = example()
    result = v5.at_run(ReplyClient({'targets': [item]}), packet, 'test', 0, v5.FIXES)
    assert len(result['candidates']) == 1
    assert not result['coverage']['complete']
    assert result['targets'][1]['status'] == 'UNCHECKED'
    assert result['coverage']['unchecked'] == [packet['current_targets'][1]['source_id']]


@pytest.mark.parametrize('bad', ['invented', 'malformed', 'duplicate'])
def test_at_quarantines_bad_target_without_erasing_independent_unique_target(bad):
    _, packet, item, _ = example()
    t1 = packet['current_targets'][1]['source_id']
    other = dict(item, target_id=t1, status='NO_ERROR')
    if bad == 'invented':
        items = [item, dict(other, target_id='invented-source')]
    elif bad == 'malformed':
        items = [item, {k: v for k, v in other.items() if k != 'reason'}]
    else:
        items = [item, other, dict(other, status='UNKNOWN')]
    result = v5.at_run(ReplyClient({'targets': items}), packet, 'test', 0, v5.FIXES)
    assert len(result['candidates']) == 1
    assert result['quarantined']
    assert result['targets'][1]['status'] == 'UNCHECKED'
    assert not result['coverage']['complete']


def test_duplicated_error_target_does_not_get_a_candidate():
    _, packet, item, _ = example()
    result = v5.at_run(ReplyClient({'targets': [item, item]}), packet, 'test', 0, v5.FIXES)
    assert result['candidates'] == []
    assert all(x['status'] == 'UNCHECKED' for x in result['targets'])


@pytest.mark.parametrize('raw', ['{"targets":[', '{"targets":null}', '{"targets":[],"extra":true}'])
def test_at_does_not_salvage_invalid_json_or_invalid_envelope(raw):
    _, packet, _, _ = example()
    client = ReplyClient({})
    client.call = lambda *a, **kw: dict(content=raw)
    result = v5.at_run(client, packet, 'test', 0, v5.FIXES)
    assert result['admission'] == 'INVALID_JSON' and not result['candidates']


@pytest.mark.parametrize('transport,finish', [({'status': 429}, 'stop'), ({'status': '429'}, 'stop'),
    ({'status': 'EXC'}, 'stop'), ({'status': 200, 'error': 'failed'}, 'stop'), ({'status': 200}, 'error')])
def test_failed_receipt_content_cannot_be_supported_or_salvaged(transport, finish):
    _, packet, item, candidate = example()
    client = ReplyClient({})
    value = dict(policy_quote=item['policy_quote'], evidence_quote=item['evidence'][0]['quote'],
                 analysis='Forbidden.', verdict='SUPPORTED')
    client.call = lambda *a, **kw: dict(content=json.dumps(value), transport=transport, finish_reason=finish)
    result = v5.verify(client, packet, candidate, 'test', 0, 'verify', v5.FIXES)
    assert result['verification_status'] == 'TECHNICAL_FAILURE'
    assert result['admission'] == ('COMPLETION_FAILURE' if finish == 'error' and transport == {'status': 200} else 'TRANSPORT_FAILURE')
    client.call = lambda *a, **kw: dict(content=json.dumps({'targets': [item]}), transport=transport, finish_reason=finish)
    result = v5.at_run(client, packet, 'test', 0, v5.FIXES)
    assert result['admission'] == 'TRANSPORT_FAILURE' and not result['candidates']


def test_http_success_failed_completion_is_not_used_and_has_one_bounded_retry():
    _, packet, item, candidate = example()
    valid = dict(policy_quote=item['policy_quote'], evidence_quote=item['evidence'][0]['quote'],
                 analysis='First JSON must not decide.', verdict='SUPPORTED')
    attempts = []
    client = ReplyClient({})
    def replies(req, attempt=0, tag=''):
        attempts.append(attempt)
        value = valid if len(attempts) == 1 else dict(valid, verdict='REFUTED', analysis='Second reply refutes.')
        return dict(content=json.dumps(value), transport={'status': 200},
                    finish_reason='error' if len(attempts) == 1 else 'stop')
    client.call = replies
    result = v5.verify(client, packet, candidate, 'test', 7, 'verify', v5.FIXES)
    assert attempts == [7, 107]
    assert result['verification_status'] == 'REFUTED'
    assert result['first_invalid']['admission'] == 'COMPLETION_FAILURE'


@pytest.mark.parametrize('http_status', [401, 402, 403, 429])
def test_http_quota_auth_failure_never_uses_completion_retry(http_status):
    _, packet, item, candidate = example()
    attempts = []
    client = ReplyClient({})
    def replies(req, attempt=0, tag=''):
        attempts.append(attempt)
        return dict(content=json.dumps(dict(policy_quote=item['policy_quote'], evidence_quote=item['evidence'][0]['quote'],
                    analysis='Not a successful receipt.', verdict='SUPPORTED')),
                    transport={'status': http_status}, finish_reason='error')
    client.call = replies
    result = v5.verify(client, packet, candidate, 'test', 7, 'verify', v5.FIXES)
    assert attempts == [7] and result['verification_status'] == 'TECHNICAL_FAILURE'


@pytest.mark.parametrize('difference', ['reason', 'evidence', 'proof', 'long_requirement'])
def test_pool_retains_distinct_reasons_and_witnesses_then_checks_supported_second(difference):
    row, packet, item, candidate = example()
    common = dict(candidate, origin='Ems', kind='SEMANTIC')
    first = dict(common, reason='First hypothesis.', evidence_source_ids=[packet['current_targets'][1]['source_id']])
    second = dict(first)
    if difference == 'reason':
        second['reason'] = 'Distinct hypothesis.'
    elif difference == 'evidence':
        second['evidence_source_ids'] = [packet['current_targets'][0]['source_id']]
    elif difference == 'proof':
        first['proof'] = dict(operation='LE', leaves=[1, 2])
        second['proof'] = dict(operation='LE', leaves=[2, 1])
    else:
        first['requirement'] = 'Shared text ' * 30 + 'first clause'
        second['requirement'] = 'Shared text ' * 30 + 'distinct clause'
    base = dict(final_decision='NO_ERROR', binary=0, decision_owner=None,
                guard=dict(established_error=False), reasons=[], steps=[], packet=dict(packet_sha256=sha(packet)))
    checked = []

    def verify_fixture(client, rp, cand, *args, **kwargs):
        checked.append(cand['reason'])
        status = 'SUPPORTED' if cand == second else 'REFUTED'
        return dict(verification_status=status, verdict=status)

    with patch.object(v5, 'review', return_value=base), \
         patch.object(v5.ems, 'trigger', return_value=dict(quant=['fixture'], fallback=[])), \
         patch.object(v5.df, 'trigger', return_value=[]), \
         patch.object(v5, 'ems_run', return_value=dict(candidates=[first, dict(first), second])), \
         patch.object(v5, 'at_run', return_value=dict(candidates=[])), \
         patch.object(v5, 'verify', side_effect=verify_fixture):
        result = v5.run_v5(row, None, flags={'pool'}, model='test', budget=400000)
    assert checked == [first['reason'], second['reason']]
    assert len(result['pool']) == 2
    assert v5.decide(result)[0] == 1
