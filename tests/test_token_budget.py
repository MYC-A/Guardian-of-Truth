"""Native-token request budget in the review hook: off = historical byte cap, on = served context."""
import copy
import json

import pytest

from experiments.guardian_semantic.variants import Hook
from guardian_truth.submission.cli import MODEL, predict_one
from guardian_truth.integrated.transport import sha


class Inner:
    model = MODEL

    def __init__(self):
        self.calls = []

    def call(self, request, attempt=0, tag=''):
        self.calls.append((tag, copy.deepcopy(request)))
        return dict(content='{}', transport=dict(status=200), finish_reason='stop')


class Budget:
    """Fake tokenizer: 1 token per 10 bytes of the user message."""
    def __init__(self, context, fail=False):
        self.context, self.fail, self.n = context, fail, 0

    def count(self, request):
        self.n += 1
        if self.fail:
            raise TimeoutError('down')
        return len(request['messages'][1]['content'].encode()) // 10


def req(nbytes, max_tokens=100):
    return dict(model=MODEL, max_tokens=max_tokens, messages=[dict(role='system', content='s'),
                                                              dict(role='user', content='x' * nbytes)])


def test_default_is_historical_byte_cap_with_identical_receipt():
    h = Hook(Inner(), None, MODEL, max_request_bytes=60000)
    b = h._wire_budget(req(10))
    assert set(b) == {'request_bytes', 'max_request_bytes', 'reserved_completion_tokens', 'validation'}
    assert b['validation'] == 'SERIALIZED_UTF8_BYTE_CAP_ONLY_NOT_PROVIDER_TOKENIZER'
    assert h._send(req(70000))['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET'
    assert h._send(req(1000))['transport']['status'] == 200


def test_token_budget_replaces_byte_cap():
    inner = Inner()
    h = Hook(inner, None, MODEL, max_request_bytes=60000, token_budget=Budget(context=10000))
    ok = h._send(req(90000, max_tokens=500))                     # 9000 + 500 <= 10000 tokens: sent although >60 KB
    assert ok['transport']['status'] == 200 and ok['input_budget']['input_tokens'] == 9000
    over = h._send(req(96000, max_tokens=500))                   # 9600 + 500 > 10000
    assert over['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET' and len(inner.calls) == 1
    edge = h._send(req(95000, max_tokens=500))                   # exactly at the limit is allowed
    assert edge['transport']['status'] == 200


def test_token_count_failure_falls_back_to_byte_cap():
    h = Hook(Inner(), None, MODEL, max_request_bytes=60000, token_budget=Budget(context=10 ** 6, fail=True))
    r = h._send(req(70000))
    assert r['transport']['status'] == 'NOT_EXECUTED_INPUT_BUDGET'
    assert r['input_budget']['token_count_error'] == 'TimeoutError'
    assert h._send(req(1000))['transport']['status'] == 200


def test_invalid_token_budget_object_is_rejected():
    with pytest.raises(ValueError):
        Hook(Inner(), None, MODEL, token_budget=object())
    with pytest.raises(ValueError):
        Hook(Inner(), None, MODEL, token_budget=Budget(context=0))


class InjectHook(Hook):
    def inject(self, request, attempt):
        new = copy.deepcopy(request)
        new['messages'][1]['content'] += 'y' * 30000
        return new


def test_injection_fallback_uses_the_same_rule():
    # bytes: injected request 31 KB + base > 60 KB -> fallback to base
    inner = Inner()
    InjectHook(inner, 'blind', MODEL, max_request_bytes=60000).call(req(40000), tag='review')
    assert len(inner.calls[0][1]['messages'][1]['content']) == 40000
    # tokens: 7000 tokens fits a 10 000 context -> injected request is sent
    inner = Inner()
    InjectHook(inner, 'blind', MODEL, max_request_bytes=60000, token_budget=Budget(10000)).call(req(40000), tag='review')
    assert len(inner.calls[0][1]['messages'][1]['content']) == 70000
    # tokens: injected exceeds, base fits -> base
    inner = Inner()
    InjectHook(inner, 'blind', MODEL, max_request_bytes=60000, token_budget=Budget(6000)).call(req(40000), tag='review')
    assert len(inner.calls[0][1]['messages'][1]['content']) == 40000


class NoLayers:
    def findings(self, row):
        return dict(findings=[])


class Client:
    model = MODEL

    def __init__(self):
        self.calls = []

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=copy.deepcopy(request), tag=tag))
        rec = dict(key=sha(dict(request=request, attempt=attempt)), transport=dict(status=200),
                   finish_reason='stop', usage={}, cached=False)
        if tag == 'pre_blind':
            return dict(rec, content=json.dumps(dict(requirements=[], entities=[], computed_values=[],
                                                     expected_actions=[], uncertainties=['u' * 70000])))
        p = json.loads(request['messages'][1]['content'])
        return dict(rec, content=json.dumps(dict(
            regulated_action=dict(target_id=p['current_targets'][0]['source_id'], description='x'),
            applicable_norms=[], supporting_evidence=[], exception_analysis='', reason='ok',
            open_questions=[], decision='NO_ERROR')))


ROW = dict(id='r', prompt='⟦SYSTEM⟧\nNever write FORBIDDEN.', response='⟦ASSISTANT⟧\nHello.')


def review_packet(client):
    return json.loads(next(c['request'] for c in client.calls if c['tag'] == 'review')['messages'][1]['content'])


def test_predict_one_large_pre_analysis_delivered_only_with_token_budget():
    off = Client()
    predict_one(ROW, off, NoLayers())
    assert 'blind_analysis' not in review_packet(off)              # >60 KB -> dropped under the byte cap
    on = Client()
    predict_one(ROW, on, NoLayers(), token_budget=Budget(context=32768))
    assert 'blind_analysis' in review_packet(on)
    # default call is unchanged: same review request as an explicit None
    again = Client()
    predict_one(ROW, again, NoLayers(), token_budget=None)
    assert [c['request'] for c in again.calls] == [c['request'] for c in off.calls]
