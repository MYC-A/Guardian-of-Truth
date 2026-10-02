"""One HTTP attempt, persistent breaker, explicit cost; no 402/429 polling."""
import hashlib
from contextlib import closing
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request


class ModelTransport:
    def __init__(self, directory, *, max_calls=150, max_tokens=500000,
                 max_output_tokens=2400, timeout=120, provider='mistral', model=None):
        self.directory = Path(directory)
        self.directory.mkdir(parents=True, exist_ok=True)
        self.cache = self.directory / 'cache'
        self.cache.mkdir(exist_ok=True)
        self.ledger = self.directory / 'attempts.jsonl'
        self.database = self.directory / 'budget.sqlite'
        self.breaker = self.directory / 'breaker.json'
        self.max_calls, self.max_tokens = max_calls, max_tokens
        self.max_output_tokens, self.timeout = max_output_tokens, timeout
        env = {}
        for path in (Path('/workspace/.env'), Path('/workspace/guardian/secrets/mistral.env'),
                     Path('/workspace/guardian/secrets/api_keys.env')):
            if path.exists():
                for line in path.read_text().splitlines():
                    line = line.strip().removeprefix('export ')
                    if line and not line.startswith('#') and '=' in line:
                        name, value = line.split('=', 1)
                        if name.strip() in ('MISTRAL_API_KEY', 'MISTRAL_MODEL', 'OLLAMA_API_KEY', 'UKISAI_API_KEY'):
                            env[name.strip()] = value.strip().strip('"').strip("'")
        self.provider = provider
        endpoints = {'mistral': ('https://api.mistral.ai/v1', 'MISTRAL_API_KEY', None),
            'ollama': ('https://ollama.com/v1', 'OLLAMA_API_KEY', None),
            'ukisai': ('https://ukisai.com/api/swift/v1', 'UKISAI_API_KEY', 'none'),
            'vireonix': ('https://vireonix.ai/v1', None, 'unused'),
            'aihorde': ('https://oai.aihorde.net/v1', None, '0000000000')}
        if provider not in endpoints:
            raise ValueError('provider not in configured allowlist')
        self.base, variable, fallback = endpoints[provider]
        self.key = (os.environ.get(variable) or env.get(variable) or fallback) if variable else fallback
        self.model = model or (os.environ.get('MISTRAL_MODEL') or env.get('MISTRAL_MODEL') if provider == 'mistral' else None)
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('CREATE TABLE IF NOT EXISTS attempts (id INTEGER PRIMARY KEY, '
                'request_sha TEXT, status TEXT, known_tokens INTEGER, unknown_bound INTEGER, seconds REAL)')

    def snapshot(self):
        with closing(sqlite3.connect(self.database)) as db, db:
            calls, known, unknown, seconds, pending = db.execute(
                "SELECT COUNT(*),COALESCE(SUM(known_tokens),0),COALESCE(SUM(unknown_bound),0),"
                "COALESCE(SUM(seconds),0),COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
        return {'actual_api_attempts': calls, 'known_provider_tokens': known,
            'unknown_usage_upper_bounds': unknown, 'model_seconds': seconds, 'pending_reservations': pending,
            'breaker_open': self.breaker.exists(), 'model': self.model, 'provider': self.provider,
            'limits': {'max_calls': self.max_calls, 'max_tokens_or_unknown_bound': self.max_tokens}}

    def __call__(self, messages):
        body = {'model': self.model, 'messages': messages, 'temperature': 0,
                'max_tokens': self.max_output_tokens, 'response_format': {'type': 'json_object'}}
        raw = json.dumps(body, ensure_ascii=False).encode()
        sha = hashlib.sha256(self.provider.encode() + b'\x00' + raw).hexdigest()
        cached = self.cache / (sha + '.json')
        if cached.exists():
            return {**json.loads(cached.read_text()), 'cached': True, 'seconds': 0.0}
        if not self.key or not self.model:
            return {'status': 'UNAVAILABLE', 'reason': 'provider_env_not_configured', 'cached': False}
        if self.breaker.exists():
            return {'status': 'UNAVAILABLE', 'reason': 'provider_circuit_open', 'cached': False}
        bound = len(raw) + self.max_output_tokens
        # A killed process keeps its pending reservation; resume cannot regain it.
        with closing(sqlite3.connect(self.database, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            calls, charged = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens+unknown_bound),0) FROM attempts').fetchone()
            if calls >= self.max_calls or charged + bound > self.max_tokens:
                return {'status': 'BUDGET_STOP', 'reason': 'approved_phase_budget_exhausted', 'cached': False}
            rowid = db.execute('INSERT INTO attempts(request_sha,status,known_tokens,unknown_bound,seconds) '
                'VALUES(?,?,?,?,?)', (sha, 'RESERVED', 0, bound, 0)).lastrowid
        request = urllib.request.Request(self.base + '/chat/completions', data=raw,
            headers={'Content-Type': 'application/json', 'Authorization': 'Bearer ' + self.key}, method='POST')
        started = time.monotonic()
        usage, data = None, None
        try:
            with urllib.request.urlopen(request, timeout=self.timeout) as reply:
                data = json.loads(reply.read())
            usage = data.get('usage')
            content = data['choices'][0]['message'].get('content')
            if isinstance(content, list):
                content = ''.join(item.get('text', '') for item in content if isinstance(item, dict))
            if not isinstance(content, str) or not content.strip():
                raise ValueError('provider_content_invalid')
            record = {'status': 'OK', 'content': content, 'usage': usage, 'model': self.model,
                'served_model': data.get('model'), 'finish_reason': data['choices'][0].get('finish_reason'),
                'request_sha256': sha, 'cached': False, 'seconds': time.monotonic() - started}
        except urllib.error.HTTPError as exc:
            record = {'status': 'UNAVAILABLE', 'reason': f'http_{exc.code}', 'http_status': exc.code,
                'model': self.model, 'request_sha256': sha, 'cached': False,
                'seconds': time.monotonic() - started}
            # The whole provider phase stops, rather than trying every case/model.
            if exc.code in (400, 401, 402, 403, 422, 429) or exc.code >= 500:
                self.breaker.write_text(json.dumps({'http_status': exc.code, 'opened_at': time.time(),
                    'reason': 'manual_resume_after_external_state_change_no_auto_poll'}), encoding='utf-8')
        except Exception as exc:
            record = {'status': 'UNAVAILABLE', 'reason': 'transport_or_contract/' + type(exc).__name__,
                'model': self.model, 'request_sha256': sha, 'cached': False,
                'seconds': time.monotonic() - started}
            if isinstance(data, dict):
                record['provider_choices'] = data.get('choices')
                record['usage'] = usage
                record['served_model'] = data.get('model')
        tokens = (usage or {}).get('total_tokens')
        ledger_row = {k: v for k, v in record.items() if k != 'content'}
        ledger_row.update({'known_tokens': tokens if type(tokens) is int else 0,
                          'unknown_usage_bound': bound if type(tokens) is not int else 0})
        with closing(sqlite3.connect(self.database)) as db, db:
            db.execute('UPDATE attempts SET status=?,known_tokens=?,unknown_bound=?,seconds=? WHERE id=?',
                (record['status'], ledger_row['known_tokens'], ledger_row['unknown_usage_bound'], record['seconds'], rowid))
        with self.ledger.open('a', encoding='utf-8') as file:
            file.write(json.dumps(ledger_row, ensure_ascii=False) + '\n')
            file.flush()
            os.fsync(file.fileno())
        if record['status'] == 'OK':
            cached.write_text(json.dumps(record, ensure_ascii=False), encoding='utf-8')
        return record
