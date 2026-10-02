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


class Budget:
    def __init__(self, phase='pilot'):
        self.phase = phase
        RESULTS.mkdir(parents=True, exist_ok=True)
        self.path = RESULTS / f'{phase}_budget.sqlite'
        self.limits = json.loads((HERE / 'protocol.json').read_text(encoding='utf-8'))['budgets'][phase]
        with self.connect() as db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, module TEXT, model TEXT, key TEXT, status TEXT, tokens INTEGER, seconds REAL, started REAL, api INTEGER)')

    def connect(self):
        return sqlite3.connect(str(self.path), timeout=30)

    def reserve(self, module, model, key, tokens, *, api=True):
        with self.connect() as db:
            db.execute('BEGIN IMMEDIATE')
            n, used_tokens, seconds = db.execute('SELECT COALESCE(SUM(api),0),COALESCE(SUM(tokens),0),COALESCE(SUM(seconds),0) FROM attempts').fetchone()
            if (n + int(api) > self.limits['max_actual_api_attempts'] or
                used_tokens + tokens > self.limits['max_logical_tokens'] or
                seconds >= self.limits['max_model_seconds']):
                raise BudgetStop('shared_phase_budget_exhausted')
            cursor = db.execute('INSERT INTO attempts(module,model,key,status,tokens,seconds,started,api) VALUES(?,?,?,?,?,?,?,?)',
                (module, model, key, 'RESERVED', tokens, 0, time.time(), int(api)))
            return cursor.lastrowid

    def finish(self, rowid, tokens, seconds, status):
        with self.connect() as db:
            db.execute('UPDATE attempts SET tokens=?,seconds=?,status=? WHERE id=?', (tokens, seconds, status, rowid))

    def snapshot(self):
        with self.connect() as db:
            n, tokens, seconds, pending = db.execute("SELECT COALESCE(SUM(api),0),COALESCE(SUM(tokens),0),COALESCE(SUM(seconds),0),COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
            by_module = db.execute('SELECT module,SUM(api),SUM(tokens),SUM(seconds) FROM attempts GROUP BY module').fetchall()
        return {'actual_api_attempts': n, 'logical_tokens': tokens, 'model_seconds': seconds,
                'pending_reservations': pending, 'modules': by_module}

    def install(self):
        """Intercept actual SDK transport. Original callers/prompts/retries preserved.

        SDK max_retries remains zero. Content/model/parameters plus checkout and
        normalization versions namespace the cache; IDs alone are never keys.
        """
        import llm
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
                    # UTF-8 bytes is a conservative upper bound on input tokens.
                    bound = len(json.dumps(kwargs['messages'], ensure_ascii=False).encode()) + kwargs.get('max_tokens', 0)
                    key = sha(kwargs)
                    rowid = self.reserve(active['module'], kwargs['model'], key, bound)
                    began = time.monotonic()
                    try:
                        answer = native_create(**kwargs)
                    except Exception:
                        self.finish(rowid, bound, time.monotonic() - began, 'TRANSPORT_ERROR_USAGE_UNKNOWN_UPPER_BOUND')
                        raise
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
