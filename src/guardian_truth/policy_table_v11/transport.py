"""Single shared budget, provider-specific quota breakers, no automatic HTTP retry."""
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request
from guardian_truth.source_search.transport import ModelTransport


class Transport:
    def __init__(self, directory, provider, model=None, *, reasoning_effort=None,
                 max_output_tokens=8192, timeout=180, max_calls=450, max_tokens=3000000):
        self.directory = Path(directory); self.directory.mkdir(parents=True, exist_ok=True)
        self.cache = self.directory / 'cache'; self.cache.mkdir(exist_ok=True)
        # Reuse the existing credential allowlist loader; no values are serialized.
        source = ModelTransport(self.directory / ('credentials_' + provider), provider=provider, model=model)
        self.base, self.key, self.model = source.base, source.key, source.model
        self.provider, self.reasoning_effort = provider, reasoning_effort
        self.max_output_tokens, self.timeout = max_output_tokens, timeout
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.database = self.directory / 'budget.sqlite'
        self.breaker = self.directory / ('breaker_' + provider + '.json')
        self.auth_breaker = self.directory / 'authentication_stop.json'
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, request_sha TEXT, provider TEXT, '
                       'model TEXT, status TEXT, known_tokens INTEGER, unknown_bound INTEGER, seconds REAL)')

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as db:
            row = db.execute("SELECT COUNT(*),COALESCE(SUM(known_tokens),0),COALESCE(SUM(unknown_bound),0),SUM(status='RESERVED') FROM attempts").fetchone()
        return {'http_attempts': row[0], 'known_tokens': row[1], 'unknown_upper_bound': row[2], 'pending': row[3] or 0,
            'limits': {'http': self.max_calls, 'tokens': self.max_tokens},
            'auth_stop': self.auth_breaker.exists(), 'provider_breakers': [p.stem for p in self.directory.glob('breaker_*.json')]}

    def __call__(self, messages, *, fresh_sample=None):
        body = {'model': self.model, 'messages': messages, 'temperature': 0,
                'max_tokens': self.max_output_tokens}
        if self.reasoning_effort is not None: body['reasoning_effort'] = self.reasoning_effort
        return self._http('POST', '/chat/completions', body, fresh_sample=fresh_sample)

    def list_models(self): return self._http('GET', '/models', None)

    def _http(self, method, endpoint, body, *, fresh_sample=None):
        raw = json.dumps(body, ensure_ascii=False).encode('utf-8') if body else None
        fingerprint = self.provider + '\x00' + method + endpoint + '\x00' + (raw.decode() if raw else '') + '\x00' + str(fresh_sample)
        sha = hashlib.sha256(fingerprint.encode()).hexdigest(); cached = self.cache / (sha + '.json')
        if cached.exists(): return {**json.loads(cached.read_text(encoding='utf-8')), 'cached': True}
        if self.auth_breaker.exists(): return {'status': 'AUTH_STOP'}
        if self.breaker.exists(): return {'status': 'PROVIDER_STOP', 'provider': self.provider}
        if not self.key or method == 'POST' and not self.model: return {'status': 'UNAVAILABLE', 'reason': 'credential_or_model_missing'}
        bound = len(raw or b'') + self.max_output_tokens if method == 'POST' else 0
        with closing(sqlite3.connect(self.database, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            count, charged = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens+unknown_bound),0) FROM attempts').fetchone()
            if count >= self.max_calls or charged + bound > self.max_tokens: return {'status': 'BUDGET_STOP', 'reservation_upper_bound': bound}
            rowid = db.execute('INSERT INTO attempts VALUES(NULL,?,?,?,?,?,?,?)',
                (sha, self.provider, self.model, 'RESERVED', 0, bound, 0)).lastrowid
        started = time.monotonic(); usage = None; provider_data = None
        try:
            req = urllib.request.Request(self.base + endpoint, data=raw, method=method,
                headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key})
            with urllib.request.urlopen(req, timeout=self.timeout) as reply: provider_data = json.loads(reply.read())
            usage = provider_data.get('usage')
            record = {'status': 'OK', 'provider': self.provider, 'model': self.model,
                      'served_model': provider_data.get('model'), 'provider_response': provider_data}
            if method == 'POST': record['content'] = provider_data['choices'][0]['message'].get('content')
            else: record['models'] = [m['id'] for m in provider_data.get('data', []) if isinstance(m, dict) and 'id' in m]
        except urllib.error.HTTPError as exc:
            record = {'status': 'UNAVAILABLE', 'reason': 'http_' + str(exc.code), 'http_status': exc.code,
                      'provider': self.provider, 'model': self.model}
            if exc.code in (401, 403):
                self.auth_breaker.write_text(json.dumps({'provider': self.provider, 'http': exc.code}), encoding='utf-8')
            elif exc.code in (402, 429):
                self.breaker.write_text(json.dumps({'provider': self.provider, 'http': exc.code}), encoding='utf-8')
        except Exception as exc:
            record = {'status': 'UNAVAILABLE', 'reason': type(exc).__name__, 'provider': self.provider, 'model': self.model}
            if provider_data is not None: record['provider_response'] = provider_data
        known = (usage or {}).get('total_tokens')
        if method == 'GET': known = 0
        known_valid = type(known) is int and known >= 0
        record.update({'request_sha256': sha, 'attempt_id': rowid, 'known_tokens': known if known_valid else 0,
            'unknown_upper_bound': 0 if known_valid else bound, 'seconds': time.monotonic() - started,
            'cached': False})
        # All successful and unsuccessful raw replies are saved before parsing/admission.
        (self.directory / ('reply_' + str(rowid) + '.json')).write_text(json.dumps(record, ensure_ascii=False, indent=2), encoding='utf-8')
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE attempts SET status=?,known_tokens=?,unknown_bound=?,seconds=? WHERE id=?',
                (record['status'], record['known_tokens'], record['unknown_upper_bound'], record['seconds'], rowid))
        with (self.directory / 'attempts.jsonl').open('a', encoding='utf-8') as file:
            file.write(json.dumps({k: v for k, v in record.items() if k not in ('content', 'provider_response')}) + '\n')
            file.flush(); os.fsync(file.fileno())
        if record['status'] == 'OK': cached.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return record
