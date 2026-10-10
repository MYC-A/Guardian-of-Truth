import math
import threading

import pytest

from guardian_truth.cascade import triage
from guardian_truth.cascade.calibrate import auc, best_threshold, escalation_curve, metrics
from guardian_truth.cascade.controller import Dispatcher, Estimator, Policy, final_label, priority
from guardian_truth.cascade.cli import triage_row


def reply(pairs, chosen=None):
    top = [dict(token=t, logprob=l) for t, l in pairs]
    first = dict(token=chosen or pairs[0][0], logprob=pairs[0][1], top_logprobs=top)
    return dict(choices=[dict(logprobs=dict(content=[first]), finish_reason='length')])


def test_score_violation_and_compliance_polarity():
    data = reply([('1', math.log(0.8)), ('0', math.log(0.2))])
    assert triage.score_view(data, 'violation') == pytest.approx(0.8)
    assert triage.score_view(data, 'compliance') == pytest.approx(0.2)


def test_score_absent_digit_and_unreadable():
    data = reply([('1', -0.01), ('Да', -5.0)])
    assert triage.score_view(data, 'violation') > 0.99
    assert triage.score_view(reply([('Да', -0.1)]), 'violation') is None
    assert triage.score_view(dict(choices=[dict()]), 'violation') is None
    assert triage.combine([None, 0.4, 0.6]) == pytest.approx(0.5)
    assert triage.combine([None]) is None


def test_fit_prompt_keeps_system_and_newest_block():
    prompt = '⟦SYSTEM⟧\n' + 'P' * 5000 + ''.join(f'⟦USER⟧\nu{i} ' + 'x' * 3000 for i in range(30))
    prompt += '⟦USER⟧\nLAST'
    text, info = triage.fit_prompt(prompt, max_chars=20000)
    assert text.startswith('⟦SYSTEM⟧') and text.endswith('LAST')
    assert info['dropped'] > 0 and len(text) <= 20000 + 200
    assert 'u29' in text and 'u0 ' not in text


def test_fit_prompt_clips_one_huge_block():
    prompt = '⟦SYSTEM⟧ policy ⟦USER⟧ ' + 'y' * 100000
    text, info = triage.fit_prompt(prompt, max_chars=10000)
    assert 'policy' in text and len(text) < 11000 and info['dropped'] == 0


def test_request_is_prefix_shared_between_views():
    row = dict(id='a', prompt='⟦SYSTEM⟧ p ⟦USER⟧ q', response='r')
    a, _ = triage.build_request(row, 'violation', 'm')
    b, _ = triage.build_request(row, 'compliance', 'm')
    assert a['max_tokens'] == 1 and a['logprobs'] and a['messages'][0] == b['messages'][0]
    ua, ub = a['messages'][1]['content'], b['messages'][1]['content']
    common = len(ua) - len(triage.VIEWS['violation']['question'])
    assert ua[:common] == ub[:common]
    with pytest.raises(ValueError):
        triage.build_request(row, 'nope', 'm')


def test_policy_defaults_preserve_b2():
    p = Policy()
    for score in (None, 0.0, 0.99):
        assert final_label(score, 1, p) == (1, 'B2')
        assert final_label(score, 0, p) == (0, 'B2')
    assert final_label(0.7, None, p) == (1, 'TRIAGE')
    assert final_label(None, None, p) == (0, 'DEFAULT_ZERO')
    assert final_label(0.95, 0, Policy(or_threshold=0.9)) == (1, 'B2_OR_TRIAGE')


def test_priority_order_and_skip():
    scores = dict(a=0.1, b=0.9, c=None, d=0.5)
    assert priority(scores, Policy()) == ['c', 'b', 'd', 'a']
    assert priority(scores, Policy(skip_below=0.3)) == ['c', 'b', 'd']


def test_estimator_is_conservative():
    e = Estimator(prior_seconds=100)
    assert e.estimate() == 100
    for s in (10, 10, 10, 200):
        e.add(s)
    assert e.estimate() >= 200


class Clock:
    def __init__(self):
        self.t = 0.0
        self.lock = threading.Lock()

    def __call__(self):
        with self.lock:
            return self.t

    def advance(self, dt):
        with self.lock:
            self.t += dt


def test_dispatcher_runs_all_with_ample_budget():
    d = Dispatcher(lambda i: int(i in 'ac'), workers=2, deadline=1e9, reserve=0, estimator=Estimator(1), poll=0.01)
    out = d.run(list('abcd'))
    assert out['results'] == dict(a=1, b=0, c=1, d=0) and not out['abandoned'] and not out['skipped_budget']


def test_dispatcher_stops_admitting_when_budget_short():
    clock = Clock()

    def run(i):
        clock.advance(100)
        return 1
    d = Dispatcher(run, workers=1, deadline=250, reserve=0, estimator=Estimator(prior_seconds=100, prior_weight=1),
                   clock=clock, poll=0.01)
    out = d.run(list('abcde'))
    assert set(out['results']) == {'a', 'b'} and out['skipped_budget'] == ['c', 'd', 'e']


def test_dispatcher_abandons_hung_rows_at_hard_deadline():
    clock = Clock()
    gate = threading.Event()

    def run(i):
        gate.wait(5)
        return 1
    d = Dispatcher(run, workers=2, deadline=10, reserve=2, estimator=Estimator(prior_seconds=1), clock=clock,
                   poll=0.01)
    timer = threading.Timer(0.1, lambda: clock.advance(100))
    timer.start()
    out = d.run(['a', 'b'])
    gate.set()
    assert out['abandoned'] == ['a', 'b'] and out['results'] == {}


def test_dispatcher_swallows_row_exceptions():
    def run(i):
        raise RuntimeError('boom')
    out = Dispatcher(run, 1, 1e9, 0, Estimator(1), poll=0.01).run(['a'])
    assert out['results'] == {'a': None}


class FakeClient:
    def __init__(self, replies):
        self.replies, self.requests = list(replies), []

    def complete(self, request, tag=''):
        self.requests.append(request)
        data, status = self.replies.pop(0)
        return data, dict(status=status, http_status=400 if status == 'HTTP' else None)


def test_triage_row_retries_context_overflow_with_smaller_prompt():
    row = dict(id='r', prompt='⟦SYSTEM⟧ ' + 'p' * 50000, response='x')
    client = FakeClient([(None, 'HTTP'), (reply([('1', math.log(0.6)), ('0', math.log(0.4))]), 200)])
    p, views, receipts = triage_row(client, row, ['violation'], 'llamacpp', 40000)
    assert p == pytest.approx(0.6) and len(receipts) == 2
    first, second = (len(r['messages'][1]['content']) for r in client.requests)
    assert second < first


def test_calibration_helpers():
    labels = dict(a=1, b=1, c=0, d=0)
    scores = dict(a=0.9, b=0.4, c=0.3, d=0.1)
    assert auc(scores, labels) == 1.0
    best = best_threshold(scores, labels)
    assert best['threshold'] == 0.4 and best['F1'] == 1.0
    b2 = dict(a=1, b=0, c=0, d=0)
    curve = escalation_curve(scores, labels, b2, direct_threshold=0.95)
    assert curve[0]['TP'] == 0 and curve[-1] == dict(k=4, **metrics([(1, 1), (1, 0), (0, 0), (0, 0)]))
