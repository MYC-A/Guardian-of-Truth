import copy
import json
import sys

import pytest

from experiments.guardian_binding import source_completion_pilot as pilot
from guardian_truth.integrated import reviewer
from guardian_truth.integrated.transport import sha


def request():
    packet = dict(normative_sources=[dict(source_id='p0', role='system', text='Use the requested record.')],
                  declarations=[], history=[dict(source_id='h2', role='assistant', kind='result', text='{"x":"A"}')],
                  current_targets=[dict(source_id='t0', role='assistant', kind='call', text='TOOL_CALL send: {"x":"B"}')])
    return reviewer.body(packet, 'local-llamacpp', 'model')


def reply():
    value = dict(decision='ERROR', regulated_action=dict(target_id='t0', description='send'),
        applicable_norms=[dict(policy_source_id='p0', interpretation='wrong record', modality='REQUIRE')],
        supporting_evidence=[dict(source_id='h2', actor='system', role='result', fact='A')],
        exception_analysis='none', reason='wrong record', open_questions=[])
    return dict(content=json.dumps(value), transport=dict(status=200), finish_reason='stop')


def test_receipt_actor_normalization_is_preserved_but_never_becomes_code_proof():
    result = pilot.admit(reply(), request())
    assert result['status'] == 'ADMITTED' and result['binary'] == 1
    assert result['interpretation']['actor_normalised'] == ['h2']
    assert result['authority'] == 'MODEL_JUDGMENT' and not result['code_certificate']


@pytest.mark.parametrize('change', ['truncated', 'http', 'duplicate', 'foreign_source', 'schema'])
def test_bad_reply_is_not_projected_to_no_error(change):
    response = reply()
    if change == 'truncated': response['finish_reason'] = 'length'
    elif change == 'http': response['transport']['status'] = 429
    elif change == 'duplicate': response['content'] = '{"decision":"ERROR","decision":"NO_ERROR"}'
    else:
        value = json.loads(response['content'])
        if change == 'foreign_source': value['supporting_evidence'][0]['source_id'] = 'h999'
        else: value['decision'] = 1
        response['content'] = json.dumps(value)
    assert pilot.admit(response, request())['binary'] is None


def test_unknown_remains_explicit():
    response = reply(); value = json.loads(response['content']); value['decision'] = 'UNKNOWN'
    response['content'] = json.dumps(value)
    assert pilot.admit(response, request())['decision'] == 'UNKNOWN'
    assert pilot.admit(response, request())['binary'] is None


def test_main_freeze_resume_and_paired_inventory(tmp_path, monkeypatch):
    req = request(); digest = sha(req)
    row = dict(id='arbitrary', control=req, completion=copy.deepcopy(req), source_completion={},
               archived_dispatched_key='old', control_sha256=digest, completion_sha256=digest, wire_identical=True)
    inputs = tmp_path / 'input.jsonl'; inputs.write_text(json.dumps(row) + '\n', encoding='utf-8')
    output = tmp_path / 'output'; calls = []
    class Client:
        def call(self, request, **kwargs):
            calls.append(kwargs)
            return reply()
    monkeypatch.setattr(pilot, 'client_for', lambda *a, **k: Client())
    monkeypatch.setattr(pilot, 'served_models', lambda _: [dict(id='model', meta=dict(n_ctx=32768))])
    monkeypatch.setattr(pilot, 'context_count', lambda *a: 200)
    monkeypatch.setattr(pilot, 'backend_endpoint', lambda _: 'http://127.0.0.1:8081/v1/chat/completions')
    monkeypatch.setattr(sys, 'argv', ['pilot', '--input', str(inputs), '--output', str(output), '--model-id', 'model'])
    pilot.main()
    rows = [json.loads(l) for l in (output / 'records.jsonl').read_text(encoding='utf-8').splitlines()]
    assert len(rows) == 2 and {r['mode'] for r in rows} == set(pilot.MODES)
    assert all(r['result']['binary'] == 1 for r in rows)
    assert all(c['attempt'] == 1 for c in calls)
    pilot.main()
    assert len(calls) == 2
    manifest = json.loads((output / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest['expected_ids'] == ['arbitrary'] and manifest['attempt'] == 1


def test_source_schema_refresh_admits_only_new_packet_ids():
    req = request(); response = reply(); value = json.loads(response['content'])
    value['supporting_evidence'][0]['source_id'] = 'h7'; response['content'] = json.dumps(value)
    assert pilot.admit(response, req)['binary'] is None
    packet = json.loads(req['messages'][1]['content'])
    packet['history'].append(dict(source_id='h7', role='assistant', kind='result', text='{"x":"A"}'))
    req['messages'][1]['content'] = json.dumps(packet)
    req['response_format']['json_schema']['schema'] = reviewer.schema(packet)
    assert pilot.admit(response, req)['binary'] == 1
