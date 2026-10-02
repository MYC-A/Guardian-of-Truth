"""Offline tests for §5 budget phases, exactly-once finalize, and the
endpoint+credential-slot+model circuit breaker. No network: the llm module
is stubbed before install(); native transport is a controllable fake.
"""
import hashlib
import os
import sys
import tempfile
import time
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix='budget_breaker_'))
os.environ['GUARDIAN_MODULAR_RESULTS'] = str(TMP)
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'src'), str(ROOT / 'service'),
                str(ROOT / 'experiments/searh_23/hybrid_service_v1'),
                str(ROOT / 'experiments/searh_23/three_architectures')]

import types

# ---- stub llm module (no openai import, no network) ----
llm = types.ModuleType('llm')
llm.CACHE_DIR = TMP / 'cache'
llm.PROVIDERS = {'ollama': ('https://ollama.com/v1', 'test-slot-key')}


class _Completions:
    def __init__(self):
        self.calls = 0
        self.fail_with = None


class _Chat:
    def __init__(self, comp):
        self.completions = comp


class _Client:
    def __init__(self, comp):
        self.chat = _Chat(comp)
        self.api_key = 'test-slot-key'


comp = _Completions()
client = _Client(comp)


def _fake_client(model):
    return model, client


def _fake_chat(model, messages, **kwargs):
    resolved, cl = llm._client(model)
    r = cl.chat.completions.create(model=resolved, messages=messages,
                                   max_tokens=kwargs.get('max_tokens', 0))
    return {'content': r['content'], 'usage': r.get('usage', {}), 'cached': False,
            'model': resolved, 'elapsed': 0.0, 'caller': kwargs.get('caller', '')}


llm._client = _fake_client
llm.chat = _fake_chat
llm._provider_of = lambda model: 'ollama' if model in ('gemma4:31b', 'glm-5.3-flash') else 'unknown'
sys.modules['llm'] = llm

from modular_common import Budget, BudgetStop, ChannelOpenError, budget_phase
from channel_breaker import ChannelBreaker, classify_transport, safe_retry_after

MODEL = 'glm-5.3-flash'
KEY = ChannelBreaker.key_for('https://ollama.com/v1', 'slot', MODEL)
SLOT = hashlib.sha256(b'test-slot-key').hexdigest()[:12]


def _fresh_budget():
    """Isolated ledger file per test; same frozen dev2 ceilings."""
    b = Budget('dev2')
    b.path = TMP / f'dev2_{time.time_ns()}_budget.sqlite'
    from channel_breaker import ChannelBreaker as CB
    b.breaker = CB(b.path)
    with b.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, module TEXT, '
                   'model TEXT, key TEXT, status TEXT, tokens INTEGER, seconds REAL, started REAL, api INTEGER)')
    return b


def _ok_answer(**kw):
    comp.fail_with = None
    comp.calls += 1
    return {'content': 'ok', 'usage': {'total_tokens': 10}}


def _create(**kwargs):
    comp.calls += 1
    if comp.fail_with is not None:
        raise comp.fail_with
    return _ok_answer()


comp.create = _create
client.chat.completions.create = _create


class Fake402(Exception):
    status_code = 402


class Fake429(Exception):
    status_code = 429

    class _Resp:
        headers = {'retry-after': '1'}

    response = _Resp()


def test_phase_limits_and_separation():
    b = Budget('dev2')
    assert b.limits['max_actual_api_attempts'] == 300
    assert b.limits['max_known_provider_tokens'] == 1000000
    assert b.limits['max_unknown_transport_upper_bound_tokens'] == 200000
    # frozen phases unchanged
    p = Budget('pilot')
    assert p.limits['max_actual_api_attempts'] == 300  # from protocol.json


def test_budget_phase_wiring():
    # user fix #1: runners resolve the phase explicitly — dev continuation
    # charges dev2, sealed stays on the frozen heldout phase, and the env
    # override pins a launch. Budget() without an explicit phase can never
    # silently charge the exhausted legacy 'pilot' ledger again.
    assert budget_phase('dev') == 'dev2'
    assert budget_phase('sealed') == 'heldout'
    os.environ['GUARDIAN_MODULAR_BUDGET_PHASE'] = 'dev2'
    try:
        b = Budget()  # runner-style construction (negative_review_pilot etc.)
        assert b.phase == 'dev2'
        assert b.path.name == 'dev2_budget.sqlite'
        assert b.limits['max_actual_api_attempts'] == 300
    finally:
        del os.environ['GUARDIAN_MODULAR_BUDGET_PHASE']
    assert Budget().phase == 'dev2'  # default resolution, no env var needed


def test_exactly_once_finalize():
    b = _fresh_budget()
    rowid = b.reserve('m', MODEL, 'k', 100)
    assert b.finish(rowid, 90, 1.0, 'COMPLETE') is True
    assert b.finish(rowid, 5, 0.0, 'COMPLETE') is False  # no-op second finalize
    snap = b.snapshot()
    assert snap['known_provider_tokens'] == 90, snap


def test_unknown_cap_triggers_stop():
    b = _fresh_budget()
    big = b.limits['max_unknown_transport_upper_bound_tokens'] + 1
    try:
        b.reserve('m', MODEL, 'k', big)
        raise AssertionError('expected BudgetStop')
    except BudgetStop as exc:
        assert 'unknown_usage_upper_bound' in str(exc)


def test_breaker_veto_after_402():
    b = _fresh_budget()
    llm2 = b.install()
    comp.fail_with = Fake402('402 payment required')
    try:
        llm2.chat(MODEL, [{'role': 'user', 'content': 'hi'}], caller='t402')
        raise AssertionError('expected Fake402')
    except Fake402:
        pass
    first_calls = comp.calls
    # second call: breaker OPEN_PERMANENT -> no transport attempt at all
    try:
        llm2.chat(MODEL, [{'role': 'user', 'content': 'hi'}], caller='t402')
        raise AssertionError('expected ChannelOpenError')
    except ChannelOpenError:
        pass
    assert comp.calls == first_calls, 'vetoed call must not touch transport'
    snap = b.snapshot()
    assert snap['breaker_skipped_calls'] >= 1, snap
    # probe-marked call passes OPEN_PERMANENT and a success clears the channel
    comp.fail_with = None
    r = llm2.chat(MODEL, [{'role': 'user', 'content': 'say ok'}],
                  caller='channel-probe')
    assert r['content'] == 'ok'
    guard = b.breaker.guard(ChannelBreaker.key_for('https://ollama.com/v1', SLOT, MODEL))
    assert guard is None, guard


def test_429_cooldown_and_cycles():
    b = Budget('dev2')
    br = b.breaker
    key = KEY
    br.record_failure(key, '429_RATE_LIMIT', retry_after=2)
    st = br.guard(key)
    assert st is not None and st[0] == 'OPEN_COOLDOWN'
    br.record_success(key)  # a live success clears cooldown
    assert br.guard(key) is None
    br.record_failure(key, '429_RATE_LIMIT', None)   # cycle 1
    br.record_failure(key, '429_RATE_LIMIT', None)   # cycle 2
    br.record_failure(key, '429_RATE_LIMIT', None)   # cycle 3 -> permanent
    st = br.guard(key)
    assert st is not None and st[0] == 'OPEN_PERMANENT' and st[1] == '429_REPEATED'
    assert br.guard(key, is_probe=True) is None  # probe may pass


def test_classify_and_retry_after():
    assert classify_transport(402) == '402_QUOTA'
    assert classify_transport(401) == '401_403_ACCESS'
    assert classify_transport(403) == '401_403_ACCESS'
    assert classify_transport(429) == '429_RATE_LIMIT'
    assert classify_transport(503) == '5XX'
    assert classify_transport(None, 'Request timed out.') == 'TIMEOUT'
    assert classify_transport(400) == 'OTHER'
    assert safe_retry_after(Fake429()) == 1.0
    assert safe_retry_after(Fake402()) is None


def test_snapshot_known_unknown_split():
    b = _fresh_budget()
    r1 = b.reserve('m', MODEL, 'k1', 100)
    b.finish(r1, 90, 1.0, 'COMPLETE')
    r2 = b.reserve('m', MODEL, 'k2', 500)
    b.finish(r2, 500, 1.0, 'TRANSPORT_ERROR_429_RATE_LIMIT_USAGE_UNKNOWN_UPPER_BOUND')
    r3 = b.reserve('m', MODEL, 'k3', 700)
    b.finish(r3, 700, 1.0, 'COMPLETE_USAGE_UNKNOWN_UPPER_BOUND')
    r4 = b.reserve('m', MODEL, 'k4', 50, api=False)
    b.finish(r4, 50, 0.0, 'CACHE_HIT')
    snap = b.snapshot()
    assert snap['known_provider_tokens'] == 90, snap
    assert snap['unknown_upper_bound_tokens'] == 1200, snap   # transport + completion-unknown
    assert snap['logical_tokens'] == 1340, snap               # everything incl. cache


def test_unknown_cap_counts_inflight_reservations():
    # user fix #3 repro: under a 200k ceiling two 150k reservations must not
    # both be admitted; after both fail and retain their upper bounds the
    # committed total would be 300k without in-flight accounting.
    b = _fresh_budget()
    assert b.limits['max_unknown_transport_upper_bound_tokens'] == 200000
    r1 = b.reserve('m', MODEL, 'k1', 150000)          # RESERVED, in flight
    try:
        b.reserve('m', MODEL, 'k2', 150000)
        raise AssertionError('expected BudgetStop: second in-flight reservation')
    except BudgetStop as exc:
        assert 'unknown_usage_upper_bound' in str(exc)
    b.finish(r1, 150000, 1.0, 'TRANSPORT_ERROR_429_RATE_LIMIT_USAGE_UNKNOWN_UPPER_BOUND')
    try:
        b.reserve('m', MODEL, 'k3', 60000)             # 150k committed + 60k > 200k
        raise AssertionError('expected BudgetStop over committed bound')
    except BudgetStop:
        pass
    r4 = b.reserve('m', MODEL, 'k4', 50000)           # 150k + 50k == cap, admitted
    b.finish(r4, 50000, 1.0, 'COMPLETE')              # becomes known provider spend
    snap = b.snapshot()
    assert snap['unknown_upper_bound_tokens'] == 150000, snap
    assert snap['known_provider_tokens'] == 50000, snap


def test_atomic_single_admission_after_cooldown():
    # user fix #2 repro: after the cooldown expires, exactly ONE caller is
    # admitted; the concurrent caller is vetoed before the first finishes.
    b = _fresh_budget()
    k = KEY
    b.breaker.record_failure(k, '429_RATE_LIMIT', retry_after=0.2)
    time.sleep(0.35)                      # cooldown expires
    second = ChannelBreaker(b.path)       # separate object == separate process
    first = b.breaker.guard(k)
    other = second.guard(k)
    admitted = [g for g in (first, other) if g is None]
    assert len(admitted) == 1, (first, other)
    veto = other if first is None else first
    assert veto[0] == 'PROBING' and veto[1] == 'PROBE_IN_FLIGHT', veto
    b.breaker.record_success(k)           # the admitted request succeeded
    assert second.guard(k) is None        # channel clear for everyone


def test_probe_claim_inherits_429_cycles():
    # The claimant's next 429 is consecutive cycle 2 (not a reset); a third
    # cycle opens the channel permanently.
    b = _fresh_budget()
    k = KEY
    b.breaker.record_failure(k, '429_RATE_LIMIT', retry_after=0.2)   # cycle 1
    time.sleep(0.35)
    assert b.breaker.guard(k) is None                               # claim admitted
    b.breaker.record_failure(k, '429_RATE_LIMIT', retry_after=0.2)  # cycle 2
    row = b.breaker._row(k)
    assert row[0] == 'OPEN_COOLDOWN' and row[3] == 2, row
    time.sleep(0.35)
    assert b.breaker.guard(k) is None                               # second claim
    b.breaker.record_failure(k, '429_RATE_LIMIT', retry_after=0.2)  # cycle 3
    row = b.breaker._row(k)
    assert row[0] == 'OPEN_PERMANENT' and row[1] == '429_REPEATED', row


def test_transient_failure_releases_probe_claim():
    # 5xx during an admitted probe releases the claim instead of pinning the
    # channel in PROBING for the whole claim window.
    b = _fresh_budget()
    k = KEY
    b.breaker.record_failure(k, '429_RATE_LIMIT', retry_after=0.2)
    time.sleep(0.35)
    assert b.breaker.guard(k) is None          # claim admitted (PROBING)
    b.breaker.record_failure(k, '5XX')
    assert b.breaker.guard(k) is None          # claim released, channel closed


if __name__ == '__main__':
    failures = 0
    for name, fn in sorted(globals().items()):
        if name.startswith('test_') and callable(fn):
            try:
                fn()
                print(f'PASS {name}')
            except AssertionError as exc:
                failures += 1
                print(f'FAIL {name}: {exc!r}')
    sys.exit(1 if failures else 0)
