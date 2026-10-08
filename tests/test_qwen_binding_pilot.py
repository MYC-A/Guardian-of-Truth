import json

from experiments.guardian_binding import pilot
from guardian_truth.verification.common import schema_errors


PACKET = dict(normative_sources=[dict(source_id='p0', text='Use the requested record.')], declarations=[],
              history=[dict(source_id='h1', text='Use R200.')],
              current_targets=[dict(source_id='t0', text='TOOL_CALL write: {"record":"R100"}')])
CANDIDATE = dict(target_id='t0')


def test_policy_verifier_requires_exact_refs_and_current_target():
    req = pilot.verifier_request(PACKET, CANDIDATE, 'model')
    value = dict(verdict='SUPPORTED', policy_refs=[dict(source_id='p0', quote='Use the requested record.')],
                 evidence_refs=[dict(source_id='h1', quote='Use R200.')], analysis='wrong record')
    reply = dict(content=json.dumps(value), finish_reason='stop', transport=dict(status=200))
    # Verifier schema needs the code-owned source categories, as in real packets.
    typed = dict(PACKET, history=[dict(PACKET['history'][0], role='user', kind='text')],
                 current_targets=[dict(PACKET['current_targets'][0], role='assistant', kind='call')])
    assert pilot.admit_verifier(reply, req, typed, CANDIDATE)['verdict'] == 'UNRESOLVED'
    value['evidence_refs'].append(dict(source_id='t0', quote=typed['current_targets'][0]['text']))
    reply['content'] = json.dumps(value)
    result = pilot.admit_verifier(reply, req, typed, CANDIDATE)
    assert result['verdict'] == 'SUPPORTED'
    assert result['authority'] == 'MODEL_JUDGMENT' and result['code_certificate'] is False
    value['policy_refs'][0]['quote'] = 'Use any record.'
    reply['content'] = json.dumps(value)
    assert pilot.admit_verifier(reply, req, typed, CANDIDATE)['verdict'] == 'UNRESOLVED'


def test_token_count_uses_rendered_chat_template(monkeypatch):
    seen = []
    def fake_post(url, data):
        seen.append((url, data))
        return {'prompt': 'rendered template'} if url.endswith('/apply-template') else {'tokens': [1, 2, 3]}
    monkeypatch.setattr(pilot, 'post_json', fake_post)
    assert pilot.context_count({'messages': [{'role': 'user', 'content': 'body'}]}, 'http://127.0.0.1:1') == 3
    assert seen[1][1]['content'] == 'rendered template'


def test_failed_complete_json_cannot_be_verifier_support():
    req = pilot.verifier_request(PACKET, CANDIDATE, 'model')
    result = pilot.admit_verifier(dict(content='{}', finish_reason='length', transport=dict(status=200)), req, PACKET, CANDIDATE)
    assert result['verdict'] is None and result['status'] == 'TECHNICAL_FAILURE'


def test_no_policy_schema_still_allows_an_explicit_unresolved_reply():
    req = pilot.verifier_request(dict(PACKET, normative_sources=[], declarations=[]), CANDIDATE, 'model')
    schema = req['response_format']['json_schema']['schema']
    assert not schema_errors(dict(verdict='UNRESOLVED', policy_refs=[], evidence_refs=[], analysis='no policy'), schema)
