"""Offline tests for the single transport instrumentation layer (§4 fix).

User bug 2026-10-02 §4: system_v2_pilot installed a Budget, then
modular_runtime.guarded_llm() installed a SECOND Budget over the
already-wrapped transport — one native call was recorded as two API
attempts and usage doubled; after a 429 cooldown the nested guard could
reject with PROBE_IN_FLIGHT while the ledger already held an API attempt.

These tests pin the fixed invariants (assignment §4 «Проверь» 1–5):
 1. single and repeated install: one native call -> one attempt, one usage;
 2. runner -> runtime -> model chain adds no second layer;
 3. after cooldown exactly ONE real probe transport call, concurrent
    callers vetoed with no phantom API row;
 4. cache hit is not a new API call; native inference is separate;
 5. exceptions and reservations finalize exactly once.

No network: the llm module is stubbed before install(); the native
transport is a controllable fake with an optional blocking gate.
"""
import hashlib
import json
import os
import sqlite3
import sys
import tempfile
import threading
import time
import types
from pathlib import Path

TMP = Path(tempfile.mkdtemp(prefix='single_layer_'))
os.environ['GUARDIAN_MODULAR_RESULTS'] = str(TMP)
ROOT = Path(__file__).resolve().parents[3]
sys.path[:0] = [str(Path(__file__).resolve().parent), str(ROOT / 'src'), str(ROOT / 'service'),
                str(ROOT / 'experiments/searh_23/hybrid_service_v1'),
                str(ROOT / 'experiments/searh_23/three_architectures')]

# ---- stub llm module (no openai import, no network) ----
llm = types.ModuleType('llm')
llm.CACHE_DIR = TMP / 'cache'
llm.PROVIDERS = {'ollama': ('https://ollama.com/v1', 'test-slot-key')}


class _Completions:
    def __init__(self):
        self.calls = 0
        self.fail_with = None
        self.cached = False
        self.gate = None          # {'entered': Event, 'release': Event}


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
    if comp.cached:
        return {'content': 'ok', 'usage': {'total_tokens': 10}, 'cached': True,
                'model': model, 'elapsed': 0.0, 'caller': kwargs.get('caller', '')}
    resolved, cl = llm._client(model)
    r = cl.chat.completions.create(model=resolved, messages=messages,
                                   max_tokens=kwargs.get('max_tokens', 0))
    return {'content': getattr(r, 'content', 'ok'), 'cached': False,
            'usage': {'total_tokens': getattr(getattr(r, 'usage', None), 'total_tokens', 0)},
            'model': resolved, 'elapsed': 0.0, 'caller': kwargs.get('caller', '')}


class _Answer:
    """Mimics the OpenAI SDK response object: attribute access to usage."""
    def __init__(self):
        self.usage = types.SimpleNamespace(total_tokens=10)
        self.content = 'ok'


def _create(**kwargs):
    comp.calls += 1
    if comp.gate is not None:
        comp.gate['entered'].set()
        comp.gate['release'].wait(timeout=30)
    if comp.fail_with is not None:
        raise comp.fail_with
    return _Answer()


llm._client = _fake_client
llm.chat = _fake_chat
llm._provider_of = lambda model: 'ollama' if model in ('gemma4:31b', 'glm-5.3-flash') else 'unknown'
sys.modules['llm'] = llm

from modular_common import Budget, BudgetPhaseConflict, BudgetStop, ChannelOpenError, budget_phase
from channel_breaker import ChannelBreaker

MODEL = 'glm-5.3-flash'
SLOT = hashlib.sha256(b'test-slot-key').hexdigest()[:12]
KEY = ChannelBreaker.key_for('https://ollama.com/v1', SLOT, MODEL)


def _budget_at(path):
    """Budget bound to an isolated ledger file (same frozen dev2 ceilings)."""
    b = Budget('dev2')
    b.path = Path(path)
    b.breaker = ChannelBreaker(b.path)
    with b.connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, module TEXT, '
                   'model TEXT, key TEXT, status TEXT, tokens INTEGER, seconds REAL, started REAL, api INTEGER)')
    return b


def _fresh_budget():
    return _budget_at(TMP / f'dev2_{time.time_ns()}_budget.sqlite')


def _reset_llm():
    """Restore the pristine stub so each test installs exactly one layer."""
    llm._client = _fake_client
    llm.chat = _fake_chat
    if hasattr(llm, '_budget_layer_owner'):
        del llm._budget_layer_owner
    client.chat.completions.create = _create
    comp.calls = 0
    comp.fail_with = None
    comp.cached = False
    comp.gate = None


def _rows(b):
    with b.connect() as db:
        return db.execute('SELECT id,module,status,tokens,api,seconds FROM attempts ORDER BY id').fetchall()


def _reset_runtime():
    import modular_runtime
    modular_runtime._llm = None
    modular_runtime._budget = None


class Fake429(Exception):
    status_code = 429

    class _Resp:
        headers = {'retry-after': '1'}

    response = _Resp()


class Fake402(Exception):
    status_code = 402


# ---- §4 check 1: single and repeated install ----
def test_repeated_install_one_attempt_one_usage():
    _reset_llm()
    path = TMP / 'idem_budget.sqlite'
    b1 = _budget_at(path)
    llm1 = b1.install()
    r = llm1.chat(MODEL, [{'role': 'user', 'content': 'hi'}], caller='t1')
    assert r['content'] == 'ok'
    # second install on the SAME ledger: idempotent reuse, no second layer
    b2 = _budget_at(path)
    llm2 = b2.install()
    assert llm2 is llm
    assert getattr(llm, '_budget_layer_owner') is b1
    r = llm2.chat(MODEL, [{'role': 'user', 'content': 'hi again'}], caller='t1')
    assert r['content'] == 'ok'
    assert comp.calls == 2, f'expected 2 native calls, got {comp.calls}'
    snap = b1.snapshot()
    assert snap['actual_api_attempts'] == 2, snap
    assert snap['known_provider_tokens'] == 20, snap   # 2 calls x usage 10, never 40
    assert len(_rows(b1)) == 2
    # usage=10 must give known tokens 10 per call (user repro: was 20)
    _reset_llm()


# ---- §4 check 2: runner -> runtime -> model adds no second layer ----
def test_runner_runtime_chain_single_layer():
    _reset_llm()
    _reset_runtime()
    import modular_runtime
    b_runner = _budget_at(TMP / 'dev2_budget.sqlite')   # runner-style default path
    b_runner.install()
    llm_rt = modular_runtime.guarded_llm()
    assert llm_rt is llm
    # the runtime drives the LIVE OWNER wired into the transport, not a shadow
    assert modular_runtime._budget is b_runner, 'runtime must share the runner budget owner'
    before = b_runner.snapshot()['actual_api_attempts']
    r = llm_rt.chat(MODEL, [{'role': 'user', 'content': 'chain'}], caller='t2')
    assert r['content'] == 'ok'
    snap = b_runner.snapshot()
    assert snap['actual_api_attempts'] == before + 1, snap
    assert comp.calls == 1, comp.calls
    # per-request limit binds through the shared owner: the first in-window
    # call succeeds, the second is stopped before any transport attempt.
    modular_runtime._budget.begin_request(max_api_attempts=1)
    calls_before = comp.calls
    try:
        r = llm_rt.chat(MODEL, [{'role': 'user', 'content': 'in-window ok'}], caller='t2')
        assert r['content'] == 'ok'
        try:
            llm_rt.chat(MODEL, [{'role': 'user', 'content': 'in-window stop'}], caller='t2')
            raise AssertionError('expected per-request BudgetStop on the second call')
        except BudgetStop:
            pass
        assert comp.calls == calls_before + 1, 'the stopped call must not reach transport'
    finally:
        modular_runtime._budget.end_request()
    _reset_llm()
    _reset_runtime()


def test_phase_conflict_is_explicit():
    _reset_llm()
    b1 = _budget_at(TMP / 'conflict_a_budget.sqlite')
    b1.install()
    b_other = Budget('heldout')              # different ledger (frozen phase)
    try:
        b_other.install()
        raise AssertionError('expected BudgetPhaseConflict')
    except BudgetPhaseConflict as exc:
        msg = str(exc)
        assert 'budget_phase_conflict' in msg and 'heldout' in msg and 'dev2' in msg, msg
    # the live layer is unchanged and still exactly one
    assert getattr(llm, '_budget_layer_owner') is b1
    r = llm.chat(MODEL, [{'role': 'user', 'content': 'still one layer'}], caller='t3')
    assert r['content'] == 'ok'
    assert b1.snapshot()['actual_api_attempts'] == 1
    assert comp.calls == 1
    _reset_llm()


def test_runtime_phase_mismatch_surfaces():
    _reset_llm()
    _reset_runtime()
    import modular_runtime
    b_runner = _budget_at(TMP / 'dev2_budget.sqlite')
    b_runner.install()
    os.environ['GUARDIAN_MODULAR_BUDGET_PHASE'] = 'heldout'
    try:
        try:
            modular_runtime.guarded_llm()
            raise AssertionError('expected BudgetPhaseConflict from guarded_llm')
        except BudgetPhaseConflict:
            pass
    finally:
        del os.environ['GUARDIAN_MODULAR_BUDGET_PHASE']
    _reset_llm()
    _reset_runtime()


# ---- §4 check 3: after cooldown exactly one probe; concurrent callers vetoed ----
def test_cooldown_one_probe_no_phantom_api_row():
    _reset_llm()
    b = _fresh_budget()
    b.install()
    comp.fail_with = Fake429('rate limited')
    try:
        llm.chat(MODEL, [{'role': 'user', 'content': 'first'}], caller='t4')
        raise AssertionError('expected Fake429')
    except Fake429:
        pass
    comp.fail_with = None
    time.sleep(1.15)                       # cooldown (retry-after=1s) expires
    gate = {'entered': threading.Event(), 'release': threading.Event()}
    comp.gate = gate
    results = []
    errors = []

    def admitted():
        try:
            results.append(llm.chat(MODEL, [{'role': 'user', 'content': 'probe'}], caller='t4'))
        except Exception as exc:
            errors.append(exc)

    def concurrent():
        try:
            results.append(llm.chat(MODEL, [{'role': 'user', 'content': 'concurrent'}], caller='t4'))
        except Exception as exc:
            errors.append(exc)

    t1 = threading.Thread(target=admitted)
    t1.start()
    assert gate['entered'].wait(timeout=10), 'admitted caller never reached native transport'
    t2 = threading.Thread(target=concurrent)
    t2.start()
    # deterministic: the concurrent caller must hit the PROBING claim while
    # the admitted call is still inside the transport (gate NOT released yet).
    t2.join(timeout=30)
    gate['release'].set()
    t1.join(timeout=30)
    # exactly ONE native transport call happened
    assert comp.calls == 2, f'expected 2 native calls total (1 failing + 1 probe), got {comp.calls}'
    vetoes = [e for e in errors if isinstance(e, ChannelOpenError)]
    assert len(vetoes) == 1, [type(e).__name__ for e in errors]
    assert 'PROBE_IN_FLIGHT' in str(vetoes[0]), str(vetoes[0])
    # ledger: 1 failing api row + 1 probe api row; the vetoed caller left an
    # api=0 BREAKER_OPEN_SKIPPED row — NEVER a phantom api=1 row without a
    # native call (the old double-layer signature).
    api_rows = [r for r in _rows(b) if r[4] == 1]
    assert len(api_rows) == 2, _rows(b)
    assert all(r[2] != 'BREAKER_OPEN_SKIPPED' for r in _rows(b) if r[4] == 1)
    skipped = [r for r in _rows(b) if r[2] == 'BREAKER_OPEN_SKIPPED']
    assert len(skipped) == 1 and skipped[0][4] == 0, _rows(b)
    snap = b.snapshot()
    assert snap['pending_reservations'] == 0, snap
    assert snap['breaker_skipped_calls'] == 1, snap
    _reset_llm()


# ---- §4 check 4: cache hit is not an API call ----
def test_cache_hit_not_new_api_call():
    _reset_llm()
    b = _fresh_budget()
    b.install()
    comp.cached = True
    r = llm.chat(MODEL, [{'role': 'user', 'content': 'from cache'}], caller='t5')
    assert r['cached'] is True
    assert comp.calls == 0, 'cache hit must not touch native transport'
    rows = _rows(b)
    assert len(rows) == 1 and rows[0][2] == 'CACHE_HIT' and rows[0][4] == 0, rows
    snap = b.snapshot()
    assert snap['actual_api_attempts'] == 0, snap
    assert snap['logical_tokens'] == 10, snap       # usage of the cached answer recorded
    assert snap['known_provider_tokens'] == 0, snap  # cache is not new provider spend
    _reset_llm()


# ---- §4 check 5: exceptions/reservations finalize exactly once ----
def test_exception_finalized_exactly_once():
    _reset_llm()
    b = _fresh_budget()
    b.install()
    comp.fail_with = Fake402('payment required')
    try:
        llm.chat(MODEL, [{'role': 'user', 'content': 'boom'}], caller='t6')
        raise AssertionError('expected Fake402')
    except Fake402:
        pass
    rows = _rows(b)
    assert len(rows) == 1, rows
    assert rows[0][2].startswith('TRANSPORT_ERROR_402') and rows[0][4] == 1, rows
    snap = b.snapshot()
    assert snap['pending_reservations'] == 0, snap            # finalized, not dangling
    assert snap['unknown_upper_bound_tokens'] == rows[0][3], snap
    failures = (TMP / 'transport_failures.jsonl')
    entries = [json.loads(s) for s in failures.read_text().splitlines()] if failures.exists() else []
    mine = [e for e in entries if e.get('caller') == 't6']
    assert len(mine) == 1, mine                             # one failure receipt, not two
    # direct double finalize stays a no-op
    rowid = b.reserve('t6', MODEL, 'k', 100)
    assert b.finish(rowid, 90, 1.0, 'COMPLETE') is True
    assert b.finish(rowid, 5, 0.0, 'COMPLETE') is False
    assert b.snapshot()['pending_reservations'] == 0
    _reset_llm()


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
