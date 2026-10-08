"""Transport/schema failures and unverified proposals never become decisions."""
import json

import pytest

from experiments.guardian_binding.audit import admit_reply, ReservedClient
from experiments.guardian_binding.eval_idcheck import project
from experiments.guardian_complementarity import combine, combine2


PACKET = dict(history=[dict(source_id='h1', role='user', kind='text', text='Use INV200.')],
              current_targets=[dict(source_id='t0', role='assistant', kind='call',
                                    text='TOOL_CALL send: {"invoice_id":"INV100"}')])
ARGUMENT = dict(target_id='t0', argument='invoice_id', used_value='INV100', requested_entity='requested invoice',
                request_source_id='h1', request_quote='Use INV200.', established_source_id='h1',
                established_quote='Use INV200.', established_value='INV200', verdict='MISMATCH')


def reply(value, **updates):
    return dict(content=json.dumps(value), finish_reason='stop', transport=dict(status=200), **updates)


def test_source_supported_mismatch_is_preserved_without_policy_authority():
    receipt = admit_reply(reply(dict(arguments=[ARGUMENT])), PACKET)
    assert receipt['status'] == 'OK'
    assert receipt['source_supported_mismatches'] == 1
    assert receipt['arguments'][0]['check'] == 'SOURCE_SUPPORTED_MISMATCH'
    assert receipt['verified'] is False and receipt['binary'] is None
    assert receipt['binding_status'] == receipt['applicability_status'] == 'UNRESOLVED'


@pytest.mark.parametrize('value', [{}, {'arguments': None}, {'arguments': [{}]},
                                 {'arguments': [dict(ARGUMENT, target_id='h1')]},
                                 {'arguments': [ARGUMENT, ARGUMENT]},
                                 {'arguments': [], 'invented': True}])
def test_local_schema_does_not_trust_provider_strict_mode(value):
    receipt = admit_reply(reply(value), PACKET)
    assert receipt['status'] == 'SCHEMA_FAIL'
    assert receipt['binary'] is None


@pytest.mark.parametrize('finish,status', [('length', 200), ('error', 200), ('stop', 429)])
def test_complete_json_inside_bad_completion_is_still_a_failure(finish, status):
    r = reply(dict(arguments=[ARGUMENT]))
    r.update(finish_reason=finish, transport=dict(status=status))
    receipt = admit_reply(r, PACKET)
    assert receipt['status'] == 'TRANSPORT_OR_COMPLETION_FAILURE'
    assert receipt['binary'] is None


def test_duplicate_json_keys_are_not_silently_last_write_wins():
    r = reply({})
    r['content'] = '{"arguments":[], "arguments":[]}'
    assert admit_reply(r, PACKET)['status'] == 'PARSE_FAIL'


def test_omitted_arguments_are_an_unchecked_gap_not_a_clean_bill_of_health():
    receipt = admit_reply(reply(dict(arguments=[])), PACKET)
    assert receipt['coverage_status'] == 'MODEL_SELECTED_ARGUMENTS_ONLY'
    assert receipt['binary'] is None and receipt['verified'] is False


def test_default_shadow_keeps_base_but_explicit_unsafe_projection_is_reproducible():
    proposals = [dict(rule='B', status='HYPOTHESIS', verified=False)]
    assert project(0, proposals) == 0
    assert project(1, proposals) == 1
    assert project(None, proposals) is None
    assert project(0, proposals, historical_unsafe_or=True) == 1


def test_binding_scorer_preserves_technical_and_semantic_unknowns(tmp_path, monkeypatch):
    monkeypatch.setattr(combine2, 'BD', tmp_path)
    (tmp_path / 'sample.jsonl').write_text('\n'.join(json.dumps(r) for r in [
        dict(id='failed', status='PARSE_FAIL', verified=False),
        dict(id='historical', status='OK', verified=True),
        dict(id='no-call', status='NO_CALL', verified=False)]), encoding='utf-8')
    records = combine2.bind('sample')
    assert records['failed']['b'] is None
    assert records['historical']['b'] is None
    assert records['no-call']['b'] == 0


def test_combiner_does_not_count_invalid_saved_binary_as_no_error(tmp_path, monkeypatch):
    monkeypatch.setattr(combine, 'classify_row', lambda *_: 'no_solution')
    path = tmp_path / 'rows.jsonl'
    path.write_text(json.dumps(dict(id='row', binary=0)), encoding='utf-8')
    assert combine.runs(path, 'B2')['row']['b'] is None


def test_conflicting_successful_raw_replies_require_explicit_selection(tmp_path, monkeypatch):
    monkeypatch.setattr(combine, 'classify_row', lambda *_: 'verdict')
    path = tmp_path / 'rows.jsonl'
    records = [dict(id='row', binary=1, rec=dict(key='k', usage={}, raw_content=value)) for value in ('first', 'second')]
    path.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
    with pytest.raises(ValueError, match='CONFLICTING_DUPLICATE_ID'):
        combine.runs(path, 'B2')


def test_content_only_conflicting_receipts_are_also_rejected(tmp_path, monkeypatch):
    monkeypatch.setattr(combine, 'classify_row', lambda *_: 'verdict')
    path = tmp_path / 'rows.jsonl'
    records = [dict(id='row', binary=1, rec=dict(key='k', usage={}, content=value)) for value in ('first', 'second')]
    path.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
    with pytest.raises(ValueError, match='CONFLICTING_DUPLICATE_ID'):
        combine.runs(path, 'B2')


def test_null_raw_content_does_not_hide_different_content(tmp_path, monkeypatch):
    monkeypatch.setattr(combine, 'classify_row', lambda *_: 'verdict')
    path = tmp_path / 'rows.jsonl'
    records = [dict(id='row', binary=1, rec=dict(key='k', usage={}, raw_content=None, content=value)) for value in ('first', 'second')]
    path.write_text('\n'.join(json.dumps(r) for r in records), encoding='utf-8')
    with pytest.raises(ValueError, match='CONFLICTING_DUPLICATE_ID'):
        combine.runs(path, 'B2')


def test_conditional_score_exposes_full_task_unknown_risk():
    result = combine.score({'positive': 1, 'missing-positive': 1, 'missing-negative': 0}, {'positive': 1})
    assert result['f1'] == 1
    assert result['f1_scope'] == 'decided_rows_only'
    assert result['undecided_positive'] == result['undecided_negative'] == 1
    assert result['f1_if_unknown_zero'] == .6667
    assert result['f1_full_completion_bounds'] == [.5, 1.0]


def test_granite_failure_risk_token_is_not_a_prediction(tmp_path, monkeypatch):
    monkeypatch.setattr(combine, 'GR', tmp_path)
    directory = tmp_path / 'compl_probe'
    directory.mkdir()
    path = directory / 'records.jsonl'
    path.write_text(json.dumps(dict(id='row', status='error', risk_token='yes')), encoding='utf-8')
    assert combine.granite('probe')['row']['b'] is None
    path.write_text('\n'.join([json.dumps(dict(id='row', status='ok', risk_token='yes'))] * 2), encoding='utf-8')
    with pytest.raises(ValueError, match='DUPLICATE_GRANITE_ID'):
        combine.granite('probe')


def test_crash_cannot_release_a_durable_call_reservation(tmp_path):
    class Interrupted:
        sent = 0
        def call(self, *args, **kwargs):
            self.sent += 1
            raise RuntimeError('interrupted after dispatch')
    client = Interrupted()
    ledger = tmp_path / 'reserved.jsonl'
    with pytest.raises(RuntimeError):
        ReservedClient(client, ledger, 1).call({'model': 'local'})
    receipt = ReservedClient(client, ledger, 1).call({'model': 'local'})
    assert client.sent == 1
    assert receipt['transport']['status'] == 'BUDGET_EXHAUSTED'
    with pytest.raises(ValueError, match='BUDGET_CHANGED'):
        ReservedClient(client, ledger, 2)
