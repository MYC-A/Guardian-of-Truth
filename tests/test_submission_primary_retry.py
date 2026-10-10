"""Failure-only output recovery, preserving production-format B2 processing."""
import copy
import json

import pandas as pd
import pytest

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, finalize_trace, predict_one
from guardian_truth.submission.recovery import recover_output


class NoLayers:
    def findings(self, row):
        return dict(findings=[])


def reply(request, decision):
    packet = json.loads(request['messages'][1]['content'])
    target = packet['current_targets'][0]['source_id']
    return dict(regulated_action=dict(target_id=target, description='Current prose'),
                applicable_norms=[dict(policy_source_id=packet['normative_sources'][0]['source_id'],
                    interpretation='Never write FORBIDDEN.', modality='FORBID')] if decision == 'ERROR' else [],
                supporting_evidence=[dict(source_id=target, actor='assistant', role='current prose', fact='FORBIDDEN')]
                    if decision == 'ERROR' else [], exception_analysis='', reason='Current move assessed.',
                open_questions=[], decision=decision)


class Client:
    model = MODEL
    def __init__(self, failure=None, decision='NO_ERROR'):
        self.failure, self.decision, self.calls = failure, decision, []
    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=copy.deepcopy(request), attempt=attempt, tag=tag))
        record = dict(key=sha(dict(request=request, attempt=attempt)), transport=dict(status=200),
                      finish_reason='stop', usage={}, cached=False)
        if tag == 'pre_blind':
            return dict(record, content=json.dumps(dict(requirements=[], entities=[], computed_values=[],
                                                        expected_actions=[], uncertainties=[])))
        assert tag == 'review'
        value = reply(request, self.decision)
        if self.failure == 'schema':
            value.pop('reason')
        if self.failure == 'reference':
            value['regulated_action']['target_id'] = 'not-a-current-target'
        if self.failure == 'wrong_enum':
            value['decision'] = 'INVALID'
        content = json.dumps(value)
        if self.failure in ('missing_close', 'missing_close_bad_reference'):
            if self.failure == 'missing_close_bad_reference':
                value['regulated_action']['target_id'] = 'not-a-current-target'
                content = json.dumps(value)
            content = content[:-1]
            record['finish_reason'] = 'length'
        if self.failure == 'incomplete':
            content = '{"reason":"unfinished'
            record['finish_reason'] = 'length'
        if self.failure == 'empty':
            content = None
        if self.failure == 'completion':
            record['finish_reason'] = 'error'
        if self.failure == 'context':
            content = None
            record['transport'] = dict(status='NOT_EXECUTED_CONTEXT_BUDGET')
        if self.failure == 'duplicate':
            content = content[:-1] + ',"decision":"ERROR"}'
        return dict(record, content=content)


def run(client, layers=None):
    row = dict(id='alignment-only', prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.',
               response='⟦ASSISTANT⟧\n' + ('FORBIDDEN' if client.decision == 'ERROR' else 'Hello.'))
    return predict_one(row, client, layers or NoLayers())


@pytest.mark.parametrize('decision,binary', [('ERROR', 1), ('NO_ERROR', 0), ('UNKNOWN', 0)])
def test_valid_results_keep_original_wire_and_authority(decision, binary):
    client = Client(decision=decision)
    trace = run(client)
    assert trace['binary'] == binary and 'output_recovery' not in trace
    assert len(client.calls) == 2
    request = client.calls[-1]['request']
    assert list(request['response_format']['json_schema']['schema']['properties'])[-1] == 'decision'
    assert 'Return decision as the FIRST' not in request['messages'][0]['content']
    assert request['max_tokens'] == 1700


@pytest.mark.parametrize('decision', ['ERROR', 'NO_ERROR', 'UNKNOWN'])
def test_opt_in_backend_identity_preserves_b2_tasks_and_projection(decision):
    row = dict(id='alignment-only', prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.',
               response='⟦ASSISTANT⟧\n' + ('FORBIDDEN' if decision == 'ERROR' else 'Hello.'))
    baseline = Client(decision=decision)
    before = predict_one(row, baseline, NoLayers())
    candidate = Client(decision=decision)
    candidate.model = 'qwen-fp8@pinned-revision:vllm-0.19.1'
    after = predict_one(row, candidate, NoLayers(), model=candidate.model, provider='local-vllm')
    assert {k: before.get(k) for k in ('binary', 'owner', 'accusation', 'output_recovery')} == {
        k: after.get(k) for k in ('binary', 'owner', 'accusation', 'output_recovery')}
    assert 'inference_profile' not in before
    assert after['inference_profile'] == dict(model=candidate.model, provider='local-vllm')
    assert len(candidate.calls) == len(baseline.calls)
    for old, new in zip(baseline.calls, candidate.calls):
        assert new['request']['model'] == candidate.model
        old, new = copy.deepcopy(old), copy.deepcopy(new)
        old['request'].pop('model')
        new['request'].pop('model')
        assert old == new


def test_wrong_opt_in_backend_identity_fails_before_any_model_call():
    client = Client()
    with pytest.raises(ValueError, match='PREDICTOR_CLIENT_MODEL_MISMATCH'):
        predict_one(dict(id='x', prompt='unused', response='unused'), client, NoLayers(),
                    model='different-serving-identity', provider='local-vllm')
    assert not client.calls


def test_mixed_backend_layers_fail_before_silent_optional_stage_loss():
    client = Client()
    client.model = 'qwen-fp8@pinned-revision:vllm-0.19.1'
    layers = NoLayers()
    layers.model = MODEL
    with pytest.raises(ValueError, match='PREDICTOR_LAYERS_MODEL_MISMATCH'):
        predict_one(dict(id='x', prompt='unused', response='unused'), client, layers,
                    model=client.model, provider='local-vllm')
    assert not client.calls


@pytest.mark.parametrize('decision,binary', [('ERROR', 1), ('NO_ERROR', 0), ('UNKNOWN', 0)])
def test_missing_root_close_revalidates_all_original_fields_and_references(decision, binary):
    client = Client('missing_close', decision)
    trace = run(client)
    assert trace['binary'] == binary and 'output_recovery' not in trace
    assert trace['rec']['A_adm2']['admission'] == 'ADMITTED'
    assert trace['pre_steps'][-1]['normalization'] == 'MISSING_ROOT_CLOSE_ADDED'
    assert trace['primary_receipt']['content'].endswith('"' + decision + '"')
    assert len(client.calls) == 2
    assert recover_output(finalize_trace(trace)) == trace


@pytest.mark.parametrize('failure', ['schema', 'reference'])
@pytest.mark.parametrize('decision,binary', [('ERROR', 1), ('NO_ERROR', 0), ('UNKNOWN', 0)])
def test_complete_model_enum_can_classify_without_admitting_rejected_cause(failure, decision, binary):
    client = Client(failure, decision)
    trace = run(client)
    assert trace['binary'] == binary
    assert trace['owner'] == 'RAW_MODEL_DECISION'
    assert trace['accusation'] is None
    assert trace['rec']['A_adm2']['decision'] is None
    assert trace['output_recovery']['cause_status'] == 'NOT_VALIDATED'
    assert trace['technical_error'] == 'PRIMARY_INFERENCE_FAILURE'
    assert len(client.calls) == 2
    assert recover_output(finalize_trace(trace)) == trace


@pytest.mark.parametrize('failure', ['incomplete', 'empty', 'context', 'completion', 'wrong_enum', 'duplicate',
                                    'missing_close_bad_reference'])
def test_no_usable_classification_gets_explicit_zero_without_reviewer_retry(failure):
    client = Client(failure, decision='ERROR')
    trace = run(client)
    assert trace['binary'] == 0 and trace['owner'] == 'DEFAULT_ZERO'
    assert trace['accusation'] is None
    assert trace['output_recovery']['strict_binary'] is None
    assert len(client.calls) == 2
    assert recover_output(finalize_trace(trace)) == trace


@pytest.mark.parametrize('decision,binary', [('ERROR', 1), ('NO_ERROR', 0)])
def test_auxiliary_exception_preserves_already_admitted_primary(decision, binary):
    class BrokenLayers:
        def findings(self, row):
            raise RuntimeError('unrelated checker failure')
    trace = run(Client(decision=decision), BrokenLayers())
    assert trace['binary'] == binary and 'output_recovery' not in trace
    assert trace['layer_trace']['admission'] == 'TECHNICAL_FAILURE'


@pytest.mark.parametrize('status', ['EXC', 429, 500])
def test_failed_transport_cannot_supply_a_positive_enum(status):
    trace = dict(binary=None, error='PRIMARY_INFERENCE_FAILURE',
                 primary_receipt=dict(content='{"decision":"ERROR"}', finish_reason='stop', transport=dict(status=status)))
    assert recover_output(trace)['owner'] == 'DEFAULT_ZERO'


def test_nested_or_quoted_decision_never_supplies_classification():
    for text in ['{"reason":"ERROR"}', '{"analysis":{"decision":"ERROR"}}']:
        trace = dict(binary=None, error='PRIMARY_INFERENCE_FAILURE',
                     primary_receipt=dict(content=text, finish_reason='stop', transport=dict(status=200)))
        assert recover_output(trace)['owner'] == 'DEFAULT_ZERO'


def test_full_entry_writes_all_rows_and_reports_zero_fallback(monkeypatch, tmp_path, capsys):
    from guardian_truth.submission import cli
    class Server:
        port, props, api_key = 9999, {}, None
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    monkeypatch.setattr(cli, 'ModelServer', Server)
    def predict(row, *args):
        if row['id'] == '001':
            raise ValueError('row failure')
        return dict(id=row['id'], binary=1, owner='EXISTING_VALID_RESULT', accusation=dict(text='Existing reason'))
    monkeypatch.setattr(cli, 'predict_one', predict)
    source, dest, work = tmp_path/'input.parquet', tmp_path/'output.csv', tmp_path/'work'
    pd.DataFrame([dict(id=i, prompt='p', response='r') for i in ['001', '002']]).to_parquet(source)
    cli.main(['--input', str(source), '--output', str(dest), '--work-dir', str(work)])
    assert pd.read_parquet(dest).to_dict('records') == [dict(id='001', label=0), dict(id='002', label=1)]
    report = json.loads((work/'run.json').read_text(encoding='utf-8'))
    assert report['default_zero_fallbacks'] == 1 and report['completed'] == 2 and report['calls'] == 0
    assert 'prediction_recovery=' in capsys.readouterr().out


def test_independent_checked_layer_positive_survives_absent_primary(monkeypatch):
    from guardian_truth.repair import v5
    def failed(*args, **kwargs):
        raise RuntimeError('primary unavailable')
    monkeypatch.setattr(v5, 'run_v5', failed)
    finding = dict(status='MECHANICAL', layer='S', kind='STRUCTURAL', target_id='t0',
                   fact=dict(supported=True), norm=dict(source_supported=True), reason='Independent checked violation')
    class Layers:
        def findings(self, row): return dict(findings=[finding])
    trace = run(Client(), Layers())
    assert trace['binary'] == 1 and trace['owner'] == 'S'
    assert 'output_recovery' not in trace
    assert recover_output(finalize_trace(trace)) == trace


@pytest.mark.parametrize('policy_gap', [False, True])
def test_failed_later_layer_preserves_earlier_finding_and_existing_policy_gate(monkeypatch, policy_gap):
    from guardian_truth.v6fix import pipeline
    from guardian_truth.verification.pipeline import packet_for
    row = dict(prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.', response='⟦ASSISTANT⟧\nFORBIDDEN')
    packet = packet_for(row, 20000)
    finding = dict(status='MECHANICAL', layer='F', kind='FORMAT', target_id='t0',
                   fact=dict(supported=True), norm=dict(source_supported=True), reason='Previously checked finding')
    layers = pipeline.Layers(Client(), MODEL, layers=('F', 'P'), tolerate_component_errors=True)
    monkeypatch.setattr(layers, 'packet', lambda _: packet)
    monkeypatch.setattr(pipeline.F, 'extract', lambda *a, **k: dict(raw='', n_lines=0, steps=[]))
    monkeypatch.setattr(pipeline.F, 'bind', lambda *a: [])
    monkeypatch.setattr(pipeline.F, 'check', lambda *a: [copy.deepcopy(finding)])
    def failed(*a): raise ValueError('later layer failed')
    monkeypatch.setattr(pipeline.P, 'check', failed)
    monkeypatch.setattr(pipeline, 'coverage', lambda _: dict(unread=[dict(category='POLICY')] if policy_gap else []))
    result = layers.findings(row)
    assert result['findings'][0]['status'] == ('HYPOTHESIS' if policy_gap else 'MECHANICAL')
    assert result['stage_errors'][0]['stage'] == 'P_check'
