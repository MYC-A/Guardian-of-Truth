"""Content identities, exact provenance, and shared actual-attempt budgets.

Distinct module name avoids shadowing the original parser's ``common``.
"""
from __future__ import annotations
import hashlib
import json
import math
import os
from pathlib import Path
import sqlite3
import subprocess
import sys
import time

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT / 'service'),
               str(ROOT / 'experiments/searh_23/hybrid_service_v1'),
               str(ROOT / 'experiments/searh_23/three_architectures')]
RESULTS = Path(os.environ.get('GUARDIAN_MODULAR_RESULTS', '/workspace/guardian/results/modular_steps_20261002'))
NORMALIZATION_VERSION = 'verbatim-source/1-no-alias-rewrite'


def _phase_limits(phase):
    """Phase ceilings: frozen protocol.json for pilot/heldout; separately
    authorized continuation phases live in budget_phases.json (history
    inherited, legacy shared counter never reset)."""
    for source in ('budget_phases.json', 'protocol.json'):
        path = HERE / source
        if path.exists():
            data = json.loads(path.read_text(encoding='utf-8'))
            phases = data.get('phases') or data.get('budgets') or {}
            if phase in phases:
                return phases[phase]
    raise ValueError(f'unknown_budget_phase:{phase}')


def budget_phase(split='dev'):
    """Explicit phase wiring for every runner (user fix 2026-10-02 #1).

    Continuation runners charge the authorized dev2 phase from
    budget_phases.json; sealed runs stay on the frozen heldout phase. The
    legacy pilot ledger (699667/700000) is history-only and is never reset.
    GUARDIAN_MODULAR_BUDGET_PHASE overrides the resolution for explicitly
    pinned launches and ad-hoc probes; runners that know their split pass it
    here instead of hardcoding 'pilot'.
    """
    override = os.environ.get('GUARDIAN_MODULAR_BUDGET_PHASE')
    if override:
        return override
    return 'heldout' if split == 'sealed' else 'dev2'


def sha(value):
    if not isinstance(value, bytes):
        value = json.dumps(value, sort_keys=True, ensure_ascii=False, separators=(',', ':')).encode()
    return hashlib.sha256(value).hexdigest()


def source_sha(row):
    return hashlib.sha256((row['prompt'] + '\0' + row['response']).encode()).hexdigest()


def write(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + '.' + str(os.getpid()) + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    os.replace(tmp, path)


def append(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(value, ensure_ascii=False, sort_keys=True) + '\n')
        f.flush()
        os.fsync(f.fileno())


def load_input(split='dev', ids=None):
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    path = HERE / f'dataset/{split}_input.jsonl'
    if sha(path.read_bytes()) != manifest['splits'][split]['input_sha256']:
        raise ValueError('frozen_input_hash_mismatch')
    rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
    if ids is not None:
        by_id = {r['id']: r for r in rows}
        if len(set(ids)) != len(ids) or any(i not in by_id for i in ids):
            raise ValueError('selection_not_in_frozen_input')
        rows = [by_id[i] for i in ids]
    return rows


def exact_quotes(items, sources):
    """Validate EVERY supplied nonempty quote, not just the first match."""
    if not isinstance(items, list):
        return False
    for item in items:
        if not isinstance(item, dict):
            return False
        source, quote = item.get('source_id'), item.get('quote')
        if not isinstance(quote, str) or not quote or source not in sources or quote not in sources[source]:
            return False
        if 'start' in item or 'end' in item:
            if type(item.get('start')) is not int or type(item.get('end')) is not int:
                return False
            if sources[source][item['start']:item['end']] != quote:
                return False
    return True


class BudgetStop(BaseException):
    """Escapes model/service broad Exception fallbacks; an incomplete run stops."""


class ChannelOpenError(Exception):
    """Raised when the breaker vetoes a call on an OPEN channel (no transport
    attempt was made). Carries no status code so bounded retry loops stop."""


class Budget:
    def __init__(self, phase=None):
        # phase=None resolves explicitly through budget_phase(): the exhausted
        # legacy 'pilot' phase is never an implicit default again (user fix #1).
        self.phase = phase or budget_phase()
        self.request_limit = None
        self.request_attempts = 0
        RESULTS.mkdir(parents=True, exist_ok=True)
        self.path = RESULTS / f'{self.phase}_budget.sqlite'
        self.limits = _phase_limits(self.phase)
        from channel_breaker import ChannelBreaker
        self.breaker = ChannelBreaker(self.path)
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, module TEXT, model TEXT, key TEXT, status TEXT, tokens INTEGER, seconds REAL, started REAL, api INTEGER)')

    def connect(self):
        return sqlite3.connect(str(self.path), timeout=30)

    def reserve(self, module, model, key, tokens, *, api=True):
        if api and self.request_limit is not None and self.request_attempts >= self.request_limit:
            raise BudgetStop('per_request_actual_api_limit')
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            n, used_tokens, seconds = db.execute('SELECT COALESCE(SUM(api),0),COALESCE(SUM(tokens),0),COALESCE(SUM(seconds),0) FROM attempts').fetchone()
            if (n + int(api) > self.limits['max_actual_api_attempts'] or
                used_tokens + tokens > self.limits['max_logical_tokens'] or
                seconds >= self.limits['max_model_seconds']):
                raise BudgetStop('shared_phase_budget_exhausted')
            if api:
                # In-flight RESERVED api rows count toward the unknown ceiling
                # until exactly-once finalization (user fix 2026-10-02 #3): a
                # reservation whose eventual usage is not yet known IS unknown
                # spend. Without it two concurrent 150k reservations pass a
                # 200k cap and land 300k of retained upper bounds after both
                # fail (the reported repro).
                unknown = db.execute(
                    "SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE status LIKE 'TRANSPORT%' "
                    "OR status='COMPLETE_USAGE_UNKNOWN_UPPER_BOUND' OR (status='RESERVED' AND api=1)"
                ).fetchone()[0]
                cap_unknown = self.limits.get('max_unknown_transport_upper_bound_tokens')
                if cap_unknown is not None and unknown + tokens > cap_unknown:
                    raise BudgetStop('unknown_usage_upper_bound_ceiling')
                known = db.execute("SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE status='COMPLETE'").fetchone()[0]
                cap_known = self.limits.get('max_known_provider_tokens')
                if cap_known is not None and known + tokens > cap_known:
                    raise BudgetStop('known_provider_tokens_ceiling')
            cursor = db.execute('INSERT INTO attempts(module,model,key,status,tokens,seconds,started,api) VALUES(?,?,?,?,?,?,?,?)',
                (module, model, key, 'RESERVED', tokens, 0, time.time(), int(api)))
            if api:
                self.request_attempts += 1
            return cursor.lastrowid

    def begin_request(self, max_api_attempts=20):
        if self.request_limit is not None:
            raise RuntimeError('request_budget_already_active')
        self.request_limit, self.request_attempts = max_api_attempts, 0

    def end_request(self):
        self.request_limit = None

    def finish(self, rowid, tokens, seconds, status):
        """Exactly-once finalization: only a RESERVED row updates; a second
        finalize is a counted no-op (returns False)."""
        with self.connect() as db:
            cursor = db.execute("UPDATE attempts SET tokens=?,seconds=?,status=? WHERE id=? AND status='RESERVED'", (tokens, seconds, status, rowid))
            return cursor.rowcount == 1

    def snapshot(self):
        with self.connect() as db:
            n, tokens, seconds, pending = db.execute("SELECT COALESCE(SUM(api),0),COALESCE(SUM(tokens),0),COALESCE(SUM(seconds),0),COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
            known = db.execute("SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE status='COMPLETE'").fetchone()[0]
            # Same predicate as the admission check in reserve(): in-flight
            # api reservations are visible as unknown spend until finalized.
            unknown = db.execute(
                "SELECT COALESCE(SUM(tokens),0) FROM attempts WHERE status LIKE 'TRANSPORT%' "
                "OR status='COMPLETE_USAGE_UNKNOWN_UPPER_BOUND' OR (status='RESERVED' AND api=1)"
            ).fetchone()[0]
            by_module = db.execute('SELECT module,SUM(api),SUM(tokens),SUM(seconds) FROM attempts GROUP BY module').fetchall()
            skipped = db.execute("SELECT COUNT(*) FROM attempts WHERE status='BREAKER_OPEN_SKIPPED'").fetchone()[0]
        return {'actual_api_attempts': n, 'logical_tokens': tokens, 'model_seconds': seconds,
                'pending_reservations': pending, 'modules': by_module,
                'known_provider_tokens': known, 'unknown_upper_bound_tokens': unknown,
                'breaker_skipped_calls': skipped}

    def install(self):
        """Intercept actual SDK transport. Original callers/prompts/retries preserved.

        SDK max_retries remains zero. Content/model/parameters plus checkout and
        normalization versions namespace the cache; IDs alone are never keys.
        """
        import llm
        from channel_breaker import ChannelBreaker, classify_transport, safe_retry_after
        original_client, original_chat = llm._client, llm.chat
        revision = subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip()
        namespace = sha({'revision': revision, 'normalization': NORMALIZATION_VERSION,
                         'protocol': json.loads((HERE / 'protocol.json').read_text(encoding='utf-8'))})
        llm.CACHE_DIR = RESULTS / 'cache' / namespace
        patched_clients = set()
        active = {'module': 'unspecified'}

        def client_proxy(model):
            resolved, client = original_client(model)
            if id(client) not in patched_clients:
                patched_clients.add(id(client))
                native_create = client.chat.completions.create

                def create(**kwargs):
                    # Mistral rejects OpenAI's `seed` request field. Its native
                    # endpoint uses random_seed; preserve sampling semantics.
                    if llm._provider_of(model) == 'mistral' and 'seed' in kwargs:
                        kwargs['extra_body'] = dict(kwargs.get('extra_body') or {}, random_seed=kwargs.pop('seed'))
                    # Circuit breaker: veto on OPEN channels BEFORE any transport
                    # attempt (no per-row useless requests). Probe-marked calls
                    # pass an OPEN_PERMANENT channel so recovery is testable.
                    call_model = kwargs.get('model') or model
                    # Resolve the provider from the ORIGINAL (unsplilt) model
                    # name: the resolved kwargs['model'] loses the provider
                    # prefix for 'provider/model' syntax and would map every
                    # such channel onto the 'unknown' endpoint.
                    provider = llm._provider_of(model)
                    endpoint = llm.PROVIDERS.get(provider, ('unknown',))[0]
                    slot = hashlib.sha256(str(getattr(client, 'api_key', '') or '').encode()).hexdigest()[:12]
                    bkey = ChannelBreaker.key_for(endpoint, slot, call_model)
                    is_probe = active['module'] == 'channel-probe'
                    blocked = self.breaker.guard(bkey, is_probe=is_probe)
                    if blocked:
                        rowid = self.reserve(active['module'], call_model, sha(kwargs), 0, api=False)
                        self.finish(rowid, 0, 0.0, 'BREAKER_OPEN_SKIPPED')
                        raise ChannelOpenError(f'channel_open:{blocked[1]}')
                    # UTF-8 bytes is a conservative upper bound on input tokens.
                    bound = len(json.dumps(kwargs['messages'], ensure_ascii=False).encode()) + kwargs.get('max_tokens', 0)
                    key = sha(kwargs)
                    rowid = self.reserve(active['module'], call_model, key, bound)
                    began = time.monotonic()
                    try:
                        answer = native_create(**kwargs)
                    except Exception as exc:
                        status_code = getattr(exc, 'status_code', None)
                        classification = classify_transport(status_code, str(exc))
                        retry_after = safe_retry_after(exc)
                        self.breaker.record_failure(bkey, classification, retry_after)
                        self.finish(rowid, bound, time.monotonic() - began,
                                    f'TRANSPORT_ERROR_{classification}_USAGE_UNKNOWN_UPPER_BOUND')
                        append(RESULTS / 'transport_failures.jsonl', {
                            'attempt_id': rowid, 'caller': active['module'], 'model': call_model,
                            'request_sha256': key, 'error_type': type(exc).__name__,
                            'http_status': status_code, 'classification': classification,
                            'retry_after_seconds': retry_after})
                        raise
                    self.breaker.record_success(bkey)
                    usage = getattr(answer, 'usage', None)
                    actual = getattr(usage, 'total_tokens', None) if usage else None
                    self.finish(rowid, actual if actual is not None else bound,
                                time.monotonic() - began, 'COMPLETE' if actual is not None else 'COMPLETE_USAGE_UNKNOWN_UPPER_BOUND')
                    return answer
                client.chat.completions.create = create
            return resolved, client

        def chat_proxy(model, messages, **kwargs):
            previous = active['module']
            active['module'] = kwargs.get('caller', 'unspecified')
            try:
                result = original_chat(model, messages, **kwargs)
                if result.get('cached'):
                    tokens = int((result.get('usage') or {}).get('total_tokens') or 0)
                    rowid = self.reserve(active['module'], model, sha({'model': model, 'messages': messages, 'parameters': kwargs}), tokens, api=False)
                    self.finish(rowid, tokens, 0, 'CACHE_HIT')
                # Avoid persisting arbitrary provider errors containing URLs/keys.
                if result.get('error'):
                    result = dict(result, error='provider_failure_details_redacted')
                return result
            finally:
                active['module'] = previous
        llm._client = client_proxy
        llm.chat = chat_proxy
        return llm
