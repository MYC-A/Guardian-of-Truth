"""Standalone server-side HTTP worker, using only the Python standard library.

Consumes already frozen exact wire requests. One attempt, durable reservation,
raw provider response, no automatic retries. No examined agent tools run here.
Credentials are loaded only on the server and never serialized.
"""
import argparse
from contextlib import closing
import hashlib
import json
import os
from pathlib import Path
import sqlite3
import time
import urllib.error
import urllib.request


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':')).encode()).hexdigest()


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n'); f.flush(); os.fsync(f.fileno())
    temp.replace(path)


def credentials():
    env = {}
    for name in ['/workspace/.env', '/workspace/guardian/secrets/mistral.env',
                 '/workspace/guardian/secrets/api_keys.env']:
        path = Path(name)
        if path.is_file():
            for line in path.read_text().splitlines():
                line = line.strip().removeprefix('export ')
                if not line.startswith('#') and '=' in line:
                    key, value = line.split('=', 1)
                    if key.strip() in ('MISTRAL_API_KEY', 'MISTRAL_MODEL'):
                        env[key.strip()] = value.strip().strip('"').strip("'")
    return {key: os.environ.get(key) or env.get(key) for key in
            ['MISTRAL_API_KEY', 'MISTRAL_MODEL']}


def snapshot(db_path, breaker):
    with closing(sqlite3.connect(db_path)) as db:
        row = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens),0),'
                         'COALESCE(SUM(unknown_bound),0),'
                         "COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
    return dict(zip(['attempts', 'known_tokens', 'unknown_bound', 'pending'], row),
                breaker_open=breaker.exists())


def run(directory, request_file):
    config = json.loads((directory / 'protocol.json').read_text())
    expected = config.pop('protocol_sha256')
    if digest(config) != expected:
        raise ValueError('PROTOCOL_CHANGED')
    config['protocol_sha256'] = expected
    env = credentials()
    if env['MISTRAL_MODEL'] != config['model_id'] or not env['MISTRAL_API_KEY']:
        raise ValueError('SERVER_MODEL_OR_CREDENTIAL_CONFIGURATION_CHANGED')
    db_path, breaker = directory / 'budget.sqlite', directory / 'breaker.json'
    with closing(sqlite3.connect(db_path)) as db, db:
        db.execute('CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, '
                   'request_sha TEXT UNIQUE, status TEXT, known_tokens INTEGER, '
                   'unknown_bound INTEGER, seconds REAL)')
    requests = [json.loads(s) for s in request_file.read_text().splitlines() if s.strip()]
    if len({r['request_sha256'] for r in requests}) != len(requests):
        raise ValueError('DUPLICATE_QUEUE_ENTRY')
    plan = json.loads(request_file.with_suffix('.seal.json').read_text())
    if hashlib.sha256(request_file.read_bytes()).hexdigest() != plan['queue_sha256']:
        raise ValueError('QUEUE_CHANGED')
    if plan['protocol_sha256'] != expected:
        raise ValueError('QUEUE_PROTOCOL_MISMATCH')
    stopped = None
    for entry in requests:
        request_sha = entry['request_sha256']
        body = entry['wire_body']
        if digest(body) != request_sha or body['model'] != config['model_id']:
            raise ValueError('REQUEST_CHANGED')
        path = directory / 'raw' / (request_sha + '.json')
        if path.exists():
            continue
        if breaker.exists():
            stopped = 'PERSISTENT_BREAKER_OPEN'; break
        raw = json.dumps(body, ensure_ascii=False).encode()
        bound = len(raw) + body['max_tokens']
        with closing(sqlite3.connect(db_path, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute('SELECT status FROM attempts WHERE request_sha=?', (request_sha,)).fetchone()
            if prior:
                stopped = 'PRIOR_ATTEMPT_WITHOUT_SAVED_RESPONSE_NO_RETRY'; break
            count, charged = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens+unknown_bound),0) FROM attempts').fetchone()
            if count >= config['limits']['http'] or charged + bound > config['limits']['tokens']:
                stopped = 'PHASE_BUDGET_STOP'; break
            db.execute('INSERT INTO attempts(request_sha,status,known_tokens,unknown_bound,seconds) '
                       'VALUES(?,?,?,?,?)', (request_sha, 'RESERVED', 0, bound, 0))
        started, data, usage = time.monotonic(), None, None
        record = {'protocol_sha256': expected, 'request_sha256': request_sha,
                  'model_id': config['model_id'], 'task': entry['task']}
        try:
            request = urllib.request.Request('https://api.mistral.ai/v1/chat/completions',
                data=raw, headers={'Content-Type': 'application/json',
                                  'Authorization': 'Bearer ' + env['MISTRAL_API_KEY']})
            with urllib.request.urlopen(request, timeout=config['timeout']) as response:
                data = json.loads(response.read())
            usage = data.get('usage')
            record.update(status='OK', provider_response=data)
        except urllib.error.HTTPError as error:
            # Error bodies can contain request data; only a status is saved.
            record.update(status='HTTP_ERROR', http_status=error.code)
            stopped = 'HTTP_' + str(error.code)
        except Exception as error:
            record.update(status='TRANSPORT_ERROR', error_type=type(error).__name__)
            stopped = 'TRANSPORT_' + type(error).__name__
        record['seconds'] = time.monotonic() - started
        tokens = (usage or {}).get('total_tokens')
        known = tokens if type(tokens) is int and tokens >= 0 else 0
        unknown = 0 if type(tokens) is int and tokens >= 0 else bound
        record.update(known_tokens=known, unknown_usage_upper_bound=unknown)
        # Save raw response BEFORE parsing or admitting any model claims.
        write(path, record)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute('UPDATE attempts SET status=?,known_tokens=?,unknown_bound=?,seconds=? '
                       'WHERE request_sha=?', (record['status'], known, unknown, record['seconds'], request_sha))
        if stopped:
            write(breaker, {'reason': stopped, 'opened_at': time.time(), 'automatic_retries': 0})
        write(directory / 'progress.json', {**snapshot(db_path, breaker), 'last_task': entry['task'],
              'last_request': request_sha, 'stop_reason': stopped, 'queue': request_file.name})
        print(json.dumps({'task': entry['task'], 'status': record['status'], 'known_tokens': known}), flush=True)
        if stopped:
            break
    result = {**snapshot(db_path, breaker), 'stop_reason': stopped,
              'queue': request_file.name, 'queue_finished': stopped is None}
    write(directory / (request_file.stem + '.completed.json'), result)
    print(json.dumps(result), flush=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('requests', type=Path)
    args = parser.parse_args()
    run(args.directory, args.requests)
