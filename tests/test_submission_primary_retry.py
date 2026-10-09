import copy
import json

import pytest

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, predict_one
from guardian_truth.submission.primary import REPAIR_ADDENDUM


class NoLayers:
    def findings(self, row):
        return dict(findings=[])


def valid_reply(request, decision='NO_ERROR'):
    packet = json.loads(request['messages'][1]['content'])
    target = packet['current_targets'][0]['source_id']
    return dict(regulated_action=dict(target_id=target, description='Current greeting'),
                applicable_norms=[], supporting_evidence=[], exception_analysis='',
                reason='Greeting is allowed.', open_questions=[], decision=decision)


class Client:
    model = MODEL

    def __init__(self, failure, *, terminal_failure=False, decision='NO_ERROR'):
        self.failure, self.terminal_failure, self.decision = failure, terminal_failure, decision
        self.calls = []
        self.primary_recovery_enabled = True

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=copy.deepcopy(request), attempt=attempt, tag=tag))
        record = dict(key=sha(dict(request=request, attempt=attempt)), transport=dict(status=200),
                      finish_reason='stop', usage={}, cached=False)
        if tag == 'pre_blind':
            record['content'] = json.dumps(dict(requirements=[], entities=[], computed_values=[],
                                                expected_actions=[], uncertainties=[]))
            return record
        assert tag == 'review'
        reply = valid_reply(request, self.decision)
        fail = attempt == 0 or self.terminal_failure
        if fail and self.failure in ('json', 'length'):
            record['content'] = '{"regulated_action":'
            if self.failure == 'length':
                record['finish_reason'] = 'length'
        else:
            if fail and self.failure == 'schema':
                reply.pop('reason')
            if fail and self.failure == 'reference':
                reply['regulated_action']['target_id'] = 'invented-target'
            record['content'] = json.dumps(reply)
        if fail and self.failure == 'transport':
            record.update(content=None, transport=dict(status='EXC', error='TimeoutError'))
        if fail and self.failure == 'completion':
            record['finish_reason'] = 'error'
        if fail and self.failure == 'context':
            record.update(content=None, transport=dict(status='NOT_EXECUTED_CONTEXT_BUDGET'))
        if fail and self.failure == 'http400':
            record.update(content=None, transport=dict(status='EXC', error='HTTPError', http_status=400))
        return record


def run(client):
    return predict_one(dict(id='arbitrary-row', prompt='⟦SYSTEM⟧\nBe polite.',
                            response='⟦ASSISTANT⟧\nHello.'), client, NoLayers())


@pytest.mark.parametrize('failure', ['json', 'length', 'schema', 'reference', 'transport', 'completion'])
def test_retry_recovers_primary_using_same_packet_and_one_prepass(failure):
    client = Client(failure)
    trace = run(client)
    assert trace['binary'] == 0
    assert 'error' not in trace
    assert [c['tag'] for c in client.calls] == ['pre_blind', 'review', 'review']
    first, second = client.calls[1:]
    assert first['attempt'] == 0 and second['attempt'] == 1000
    expected = copy.deepcopy(first['request'])
    if failure in ('json', 'length', 'schema', 'reference'):
        expected['messages'][0]['content'] += REPAIR_ADDENDUM
    if failure == 'length':
        expected['max_tokens'] = 3400
    assert second['request'] == expected
    retry = trace['pre_steps'][-1]
    assert retry['tag'] == 'primary_review_retry'
    assert retry['admission'] == 'ADMITTED'
    assert retry['first_invalid']['admission'] != 'ADMITTED'
    assert 'content' in retry['first_invalid']
    assert retry['first_invalid']['key'] != retry['terminal_key']
    assert trace['technical_gaps'] == []


@pytest.mark.parametrize('failure', ['json', 'length', 'schema', 'reference', 'transport', 'completion'])
def test_exhausted_retry_stays_primary_failure(failure):
    client = Client(failure, terminal_failure=True)
    trace = run(client)
    assert trace['binary'] is None
    assert trace['error'] == 'PRIMARY_INFERENCE_FAILURE'
    assert len(client.calls) == 3
    assert trace['pre_steps'][-1]['admission'] != 'ADMITTED'


@pytest.mark.parametrize('failure', ['context', 'http400'])
def test_fixed_request_failure_is_not_repeated(failure):
    client = Client(failure)
    trace = run(client)
    assert trace['binary'] is None
    assert len(client.calls) == 2


@pytest.mark.parametrize('decision', ['NO_ERROR', 'UNKNOWN'])
def test_admitted_decision_does_not_trigger_retry(decision):
    client = Client(None, decision=decision)
    assert run(client)['binary'] == 0
    assert len(client.calls) == 2


def test_global_recovery_cap_preserves_failure_when_exhausted():
    client = Client('json')
    client.reserve_recovery = lambda: False
    trace = run(client)
    assert len(client.calls) == 2
    assert trace['binary'] is None
    assert trace['pre_steps'][-1]['reason'] == 'RECOVERY_CALL_LIMIT'


def test_local_recovery_cap_is_shared_between_threads():
    from concurrent.futures import ThreadPoolExecutor
    from guardian_truth.submission.cli import LocalClient
    client = LocalClient(9999, 32768)
    with ThreadPoolExecutor(max_workers=8) as pool:
        granted = list(pool.map(lambda _: client.reserve_recovery(), range(20)))
    assert sum(granted) == client.recovery_calls == 4


def test_recovery_timeout_includes_tokenizer_time(monkeypatch):
    from guardian_truth.submission import cli
    now, observed = [0.0], []
    monkeypatch.setattr(cli.time, 'monotonic', lambda: now[0])
    def http(url, payload=None, timeout=20, api_key=None):
        observed.append(timeout)
        if url.endswith('/input_tokens'):
            now[0] += 19
            return dict(input_tokens=12)
        return dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')])
    monkeypatch.setattr(cli, 'http_json', http)
    client = cli.LocalClient(9999, 32768)
    rec = client.call_recovery(dict(model=MODEL, messages=[], max_tokens=1700), attempt=1000)
    assert rec['transport']['status'] == 200
    assert observed == [20, 101]


def test_stdout_summary_does_not_include_raw_model_or_transport_detail():
    from guardian_truth.submission.cli import failure_summary
    trace = dict(id='any', rec=dict(A=dict(steps=[dict(tag='review', raw_content='PRIVATE_REPLY',
                        transport=dict(status='EXC', detail='PRIVATE_TRANSPORT_DETAIL'))]),
                        A_adm2=dict(admission='REJECTED:ValueError:PRIVATE_VALUE')))
    serialized = json.dumps(failure_summary(trace))
    assert 'PRIVATE_' not in serialized


def test_recovery_receipt_identifies_actual_repaired_request():
    client = Client('length')
    trace = run(client)
    retry = trace['pre_steps'][-1]
    assert retry['terminal_request_sha256'] == sha(client.calls[-1]['request'])
    assert retry['terminal_request_sha256'] != sha(client.calls[1]['request'])


def test_public_cli_writes_complete_parquet_after_validated_recovery(monkeypatch, tmp_path, capsys):
    import pandas as pd
    from guardian_truth.submission import cli
    from guardian_truth.v6fix import pipeline
    class Server:
        port, props, api_key = 9999, {}, None
        def __init__(self, *args, **kwargs): pass
        def __enter__(self): return self
        def __exit__(self, *args): pass
    class Layers(NoLayers):
        def __init__(self, *args, **kwargs): pass
    reviews = []
    def http(url, payload=None, timeout=20, api_key=None):
        if url.endswith('/input_tokens'):
            return dict(input_tokens=12)
        name = payload['response_format']['json_schema']['name']
        if name == 'pre_analysis_neutral_v2':
            content = json.dumps(dict(requirements=[], entities=[], computed_values=[], expected_actions=[], uncertainties=[]))
        else:
            assert name == 'current_move_review'
            reviews.append(payload)
            content = '{' if len(reviews) == 1 else json.dumps(valid_reply(payload))
        return dict(choices=[dict(message=dict(content=content), finish_reason='stop')])
    monkeypatch.setattr(cli, 'ModelServer', Server)
    monkeypatch.setattr(cli, 'http_json', http)
    monkeypatch.setattr(pipeline, 'Layers', Layers)
    source, target, work = tmp_path / 'input.parquet', tmp_path / 'output.csv', tmp_path / 'work'
    pd.DataFrame([dict(id='001', prompt='⟦SYSTEM⟧\nBe polite.', response='⟦ASSISTANT⟧\nHello.')]).to_parquet(source)
    cli.main(['--input', str(source), '--output', str(target), '--work-dir', str(work), '--retry-primary'])
    assert pd.read_parquet(target).to_dict('records') == [dict(id='001', label=0)]
    report = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    assert report['completed'] == 1 and report['recovery_calls'] == 1
    assert len(reviews) == 2
    assert 'prediction_recovery=' in capsys.readouterr().out


@pytest.mark.parametrize('text,expected', [
    ('{"decision":"ERROR",', 'ERROR'),
    (' { "decision" : "NO_ERROR", "reason":"unfinished', 'NO_ERROR'),
    ('{"decision":"UNKNOWN","regulated_action":{"target_id":"t0",', 'UNKNOWN'),
    ('{"decision":"ERROR"', None),
    ('{"decision":"ERR', None),
    ('{"reason":"decision ERROR",', None),
    ('{"reason":{"decision":"ERROR"},', None),
    ('{"decision":"ERROR","decision":"NO_ERROR",', None),
    ('{"decision":"ERROR","reason":false}', None),
    ('{"decision":"ERROR", garbage', None),
    ('{"decision":1,', None),
    ('{"decision":"ERROR", "reason":"bad\\q', None),
    ('{"decision":"ERROR", "reason":NaN', None),
    ('{"decision":"ERROR", "evidence":{"a":1,"a":2},', None),
    ('{"decision":"ERROR",\u00a0', None),
    ('\x0c{"decision":"ERROR",', None),
    ('{"decision":"ERROR",\x0c', None),
    ('{"decision":"NO_ERROR","regulated_action":{"target_id":"t0","target_id":"t1","description":"unfinished', None),
    ('{"decision":"ERROR","items":[{"a":1},{"a":2}],"reason":"unfinished', 'ERROR'),
])
def test_partial_parser_recovers_only_complete_first_classification(text, expected):
    from guardian_truth.submission.primary import partial_decision
    assert partial_decision(dict(content=text, finish_reason='length', transport=dict(status=200))) == expected


@pytest.mark.parametrize('status,finish', [(200, 'stop'), (200, 'error'), ('EXC', 'length'), (429, 'length')])
def test_partial_parser_never_salvages_failed_completion(status, finish):
    from guardian_truth.submission.primary import partial_decision
    assert partial_decision(dict(content='{"decision":"ERROR",', finish_reason=finish, transport=dict(status=status))) is None


@pytest.mark.parametrize('decision,label', [('ERROR', 1), ('NO_ERROR', 0), ('UNKNOWN', 0)])
def test_partial_model_prediction_is_not_an_admitted_cause_and_needs_no_retry(decision, label):
    class PartialClient(Client):
        primary_contract = 'decision-first'
        def call(self, request, attempt=0, tag=''):
            result = super().call(request, attempt=attempt, tag=tag)
            if tag == 'review':
                props = request['response_format']['json_schema']['schema']['properties']
                assert next(iter(props)) == 'decision'
                result.update(content='{"decision":' + json.dumps(decision) + ',"reason":"unfinished', finish_reason='length')
            return result
    client = PartialClient(None)
    client.primary_recovery_enabled = False
    trace = run(client)
    assert len(client.calls) == 2
    assert trace['binary'] == label
    assert trace['owner'] == 'PARTIAL_MODEL_DECISION'
    assert trace['accusation'] is None
    assert trace['source_support_status'] == 'NOT_VALIDATED'
    assert trace['explanation_status'] == 'INCOMPLETE'
    assert trace['rec']['A_adm2']['decision'] is None
    assert 'error' not in trace
    from guardian_truth.submission.cli import finalize_trace
    assert finalize_trace(trace) == trace
    damaged = copy.deepcopy(trace)
    damaged['binary'] = 1 - label
    damaged['partial_model_decision'] = 'FAKE'
    assert finalize_trace(damaged) == trace


def test_recovery_diagnostic_sanitizes_validation_details():
    from guardian_truth.submission.cli import failure_summary
    trace = dict(pre_steps=[dict(tag='primary_review_retry', admission='REJECTED:ValueError:PRIVATE_SENTINEL')])
    assert 'PRIVATE_SENTINEL' not in json.dumps(failure_summary(trace))
