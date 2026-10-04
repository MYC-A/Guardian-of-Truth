"""Standalone, one-attempt server worker for frozen Mistral requests.

Reservations survive crashes. Every saved receipt is checked before any HTTP,
and a saved error or an attempt without a saved receipt stops the whole phase.
Credentials are loaded on the server only and never serialized.
"""
import argparse
from contextlib import closing
import hashlib
import json
import math
import os
from pathlib import Path
import re
import sqlite3
import time
import urllib.error
import urllib.request


ENDPOINT = 'https://api.mistral.ai/v1/chat/completions'
ERROR_STATUSES = {'HTTP_ERROR', 'TRANSPORT_ERROR'}
STATUSES = ERROR_STATUSES | {'OK', 'RESERVED'}


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, request, response, code, message, headers, new_url):
        # A redirect would be another unreserved HTTP request and could carry
        # credentials away from the sole allowed endpoint. Treat it as error.
        return None


def _open_http(request, timeout):
    return urllib.request.build_opener(_NoRedirect()).open(request, timeout=timeout)


def digest(obj):
    return hashlib.sha256(json.dumps(obj, sort_keys=True, ensure_ascii=False,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def _object(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_JSON_KEY')
        result[key] = value
    return result


def _constant(value):
    raise ValueError('NONFINITE_JSON_NUMBER')


def loads(value):
    return json.loads(value, object_pairs_hook=_object, parse_constant=_constant)


def read(path):
    return loads(path.read_text(encoding='utf-8'))


def write(path, obj):
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix('.tmp')
    with temp.open('w', encoding='utf-8') as f:
        json.dump(obj, f, ensure_ascii=False, indent=2, allow_nan=False)
        f.write('\n')
        f.flush()
        os.fsync(f.fileno())
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


def _sha(value):
    return isinstance(value, str) and re.fullmatch('[0-9a-f]{64}', value) is not None


def _integer(value):
    return type(value) is int and value >= 0


def _seconds(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def _validate_inputs(directory, request_file):
    config = read(directory / 'protocol.json')
    expected = config.pop('protocol_sha256')
    if not _sha(expected) or digest(config) != expected:
        raise ValueError('PROTOCOL_CHANGED')
    config['protocol_sha256'] = expected
    if not isinstance(config['model_id'], str) or not config['model_id']:
        raise ValueError('INVALID_MODEL_CONFIGURATION')
    if not all(_integer(config['limits'][key]) for key in ('http', 'tokens')):
        raise ValueError('INVALID_BUDGET_CONFIGURATION')
    if not _seconds(config['timeout']) or config['timeout'] == 0:
        raise ValueError('INVALID_TIMEOUT_CONFIGURATION')
    plan = read(request_file.with_suffix('.seal.json'))
    queue_bytes = request_file.read_bytes()
    if hashlib.sha256(queue_bytes).hexdigest() != plan['queue_sha256']:
        raise ValueError('QUEUE_CHANGED')
    if plan['protocol_sha256'] != expected:
        raise ValueError('QUEUE_PROTOCOL_MISMATCH')
    requests = [loads(line) for line in queue_bytes.decode('utf-8').splitlines() if line.strip()]
    seen = set()
    for entry in requests:
        key, body = entry['request_sha256'], entry['wire_body']
        if not _sha(key) or digest(body) != key or body['model'] != config['model_id']:
            raise ValueError('REQUEST_CHANGED')
        if not isinstance(entry['task'], str) or not entry['task']:
            raise ValueError('INVALID_REQUEST_TASK')
        if not _integer(body['max_tokens']) or body['max_tokens'] == 0:
            raise ValueError('INVALID_REQUEST_TOKEN_BOUND')
        if key in seen:
            raise ValueError('DUPLICATE_QUEUE_ENTRY')
        seen.add(key)
    if 'requests' in plan and plan['requests'] != len(requests):
        raise ValueError('QUEUE_COUNT_MISMATCH')
    return config, requests


def _receipts(directory, config, requests):
    entries = {r['request_sha256']: r for r in requests}
    records = {}
    for path in sorted((directory / 'raw').glob('*.json')):
        record = read(path)
        key = record['request_sha256']
        if not _sha(key) or path.name != key + '.json' or key in records:
            raise ValueError('CACHE_FILENAME_OR_REQUEST_MISMATCH')
        if record['protocol_sha256'] != config['protocol_sha256']:
            raise ValueError('CACHE_PROTOCOL_MISMATCH')
        if record['model_id'] != config['model_id']:
            raise ValueError('CACHE_MODEL_MISMATCH')
        if not isinstance(record['task'], str) or not record['task']:
            raise ValueError('CACHE_TASK_MISMATCH')
        if key in entries and record['task'] != entries[key]['task']:
            raise ValueError('CACHE_TASK_MISMATCH')
        if (record['status'] not in STATUSES - {'RESERVED'}
                or not _integer(record['known_tokens'])
                or not _integer(record['unknown_usage_upper_bound'])
                or not _seconds(record['seconds'])):
            raise ValueError('INVALID_CACHE_RECEIPT')
        if record['status'] == 'OK' and not isinstance(record.get('provider_response'), dict):
            raise ValueError('INVALID_CACHE_PROVIDER_RESPONSE')
        if record['status'] == 'HTTP_ERROR' and (
                type(record.get('http_status')) is not int or not 100 <= record['http_status'] <= 599):
            raise ValueError('INVALID_CACHE_HTTP_ERROR')
        if record['status'] == 'TRANSPORT_ERROR' and (
                not isinstance(record.get('error_type'), str) or not record['error_type']):
            raise ValueError('INVALID_CACHE_TRANSPORT_ERROR')
        records[key] = record
    return records


def _open_breaker(path, reason, request_sha=None):
    if not path.exists():
        write(path, {'reason': reason, 'opened_at': time.time(),
                     'automatic_retries': 0, 'request_sha256': request_sha})
    return reason


def _recover(db_path, breaker, config, records):
    """Reconcile crash-window receipts, charging every attempt before proceeding."""
    with closing(sqlite3.connect(db_path, timeout=30)) as db, db:
        db.execute('BEGIN IMMEDIATE')
        db.execute('CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, '
                   'request_sha TEXT UNIQUE, status TEXT, known_tokens INTEGER, '
                   'unknown_bound INTEGER, seconds REAL)')
        db.execute('CREATE TABLE IF NOT EXISTS phase_identity('
                   'id INTEGER PRIMARY KEY CHECK(id=1), protocol_sha TEXT, model_id TEXT)')
        identity = db.execute('SELECT protocol_sha,model_id FROM phase_identity WHERE id=1').fetchone()
        expected = (config['protocol_sha256'], config['model_id'])
        if identity and identity != expected:
            raise ValueError('BUDGET_PROTOCOL_OR_MODEL_MISMATCH')
        rows = db.execute('SELECT request_sha,status,known_tokens,unknown_bound,seconds '
                          'FROM attempts ORDER BY id').fetchall()
        for key, status, known, unknown, seconds in rows:
            if (not _sha(key) or status not in STATUSES or not _integer(known)
                    or not _integer(unknown) or not _seconds(seconds)):
                raise ValueError('INVALID_SAVED_ATTEMPT')
            receipt = records.get(key)
            if receipt and status != 'RESERVED' and (
                    status != receipt['status'] or known != receipt['known_tokens']
                    or unknown != receipt['unknown_usage_upper_bound'] or seconds != receipt['seconds']):
                raise ValueError('CACHE_LEDGER_MISMATCH')
        # An older ledger without an identity can only resume after all its
        # successful receipts prove the same phase. Missing/error rows stop below.
        if not identity:
            db.execute('INSERT INTO phase_identity VALUES(1,?,?)', expected)
        prior = {row[0] for row in rows}
        for key, record in records.items():
            values = (record['status'], record['known_tokens'],
                      record['unknown_usage_upper_bound'], record['seconds'], key)
            if key in prior:
                db.execute('UPDATE attempts SET status=?,known_tokens=?,unknown_bound=?,seconds=? '
                           'WHERE request_sha=?', values)
            else:
                db.execute('INSERT INTO attempts(status,known_tokens,unknown_bound,seconds,request_sha) '
                           'VALUES(?,?,?,?,?)', values)
        # Check the pre-reconciliation ledger too: a recorded error can never
        # be erased by a later receipt or an absent breaker file.
        first_error = next((row for row in rows if row[1] in ERROR_STATUSES), None)
        if first_error:
            return _open_breaker(breaker, 'SAVED_' + first_error[1], first_error[0])
        first_error = next((r for r in records.values() if r['status'] in ERROR_STATUSES), None)
        if first_error:
            reason = ('HTTP_' + str(first_error['http_status']) if first_error['status'] == 'HTTP_ERROR'
                      else 'TRANSPORT_' + first_error['error_type'])
            return _open_breaker(breaker, reason, first_error['request_sha256'])
        missing = next((row for row in rows if row[0] not in records), None)
        if missing:
            return _open_breaker(breaker, 'PRIOR_ATTEMPT_WITHOUT_SAVED_RESPONSE_NO_RETRY', missing[0])
    return 'PERSISTENT_BREAKER_OPEN' if breaker.exists() else None


def snapshot(db_path, breaker):
    with closing(sqlite3.connect(db_path)) as db:
        row = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens),0),'
                         'COALESCE(SUM(unknown_bound),0),'
                         "COALESCE(SUM(status='RESERVED'),0) FROM attempts").fetchone()
    return dict(zip(['attempts', 'known_tokens', 'unknown_bound', 'pending'], row),
                breaker_open=breaker.exists())


def run(directory, request_file):
    directory, request_file = Path(directory), Path(request_file)
    config, requests = _validate_inputs(directory, request_file)
    records = _receipts(directory, config, requests)
    db_path, breaker = directory / 'budget.sqlite', directory / 'breaker.json'
    stopped = _recover(db_path, breaker, config, records)
    env = None
    for entry in requests:
        if stopped:
            break
        request_sha, body = entry['request_sha256'], entry['wire_body']
        if request_sha in records:
            continue
        if breaker.exists():
            stopped = 'PERSISTENT_BREAKER_OPEN'
            break
        if env is None:
            env = credentials()
            if env['MISTRAL_MODEL'] != config['model_id'] or not env['MISTRAL_API_KEY']:
                raise ValueError('SERVER_MODEL_OR_CREDENTIAL_CONFIGURATION_CHANGED')
        raw = json.dumps(body, ensure_ascii=False, allow_nan=False).encode()
        bound = len(raw) + body['max_tokens']
        with closing(sqlite3.connect(db_path, timeout=30)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            prior = db.execute("SELECT request_sha FROM attempts WHERE status!='OK' "
                               'OR request_sha=? ORDER BY id LIMIT 1', (request_sha,)).fetchone()
            if prior:
                stopped = _open_breaker(breaker, 'PRIOR_ATTEMPT_WITHOUT_SAVED_RESPONSE_NO_RETRY', prior[0])
                break
            if breaker.exists():
                stopped = 'PERSISTENT_BREAKER_OPEN'
                break
            count, charged = db.execute('SELECT COUNT(*),COALESCE(SUM(known_tokens+unknown_bound),0) '
                                        'FROM attempts').fetchone()
            if count >= config['limits']['http'] or charged + bound > config['limits']['tokens']:
                stopped = 'PHASE_BUDGET_STOP'
                break
            db.execute('INSERT INTO attempts(request_sha,status,known_tokens,unknown_bound,seconds) '
                       'VALUES(?,?,?,?,?)', (request_sha, 'RESERVED', 0, bound, 0))
        started, usage = time.monotonic(), None
        record = {'protocol_sha256': config['protocol_sha256'], 'request_sha256': request_sha,
                  'model_id': config['model_id'], 'task': entry['task']}
        try:
            request = urllib.request.Request(ENDPOINT, data=raw,
                headers={'Content-Type': 'application/json',
                         'Authorization': 'Bearer ' + env['MISTRAL_API_KEY']})
            with _open_http(request, timeout=config['timeout']) as response:
                data = loads(response.read())
            if not isinstance(data, dict):
                raise ValueError('INVALID_PROVIDER_RESPONSE')
            usage = data.get('usage')
            record.update(status='OK', provider_response=data)
        except urllib.error.HTTPError as error:
            # Error bodies may include request data; save only their status.
            record.update(status='HTTP_ERROR', http_status=error.code)
            stopped = 'HTTP_' + str(error.code)
        except Exception as error:
            record.update(status='TRANSPORT_ERROR', error_type=type(error).__name__)
            stopped = 'TRANSPORT_' + type(error).__name__
        # Open the breaker before writing less essential output. A crash at any
        # earlier point still leaves RESERVED and prevents another HTTP attempt.
        if stopped:
            _open_breaker(breaker, stopped, request_sha)
        record['seconds'] = time.monotonic() - started
        tokens = usage.get('total_tokens') if isinstance(usage, dict) else None
        known = tokens if _integer(tokens) else 0
        unknown = 0 if _integer(tokens) else bound
        record.update(known_tokens=known, unknown_usage_upper_bound=unknown)
        write(directory / 'raw' / (request_sha + '.json'), record)
        with closing(sqlite3.connect(db_path)) as db, db:
            db.execute('UPDATE attempts SET status=?,known_tokens=?,unknown_bound=?,seconds=? '
                       'WHERE request_sha=?', (record['status'], known, unknown, record['seconds'], request_sha))
        records[request_sha] = record
        write(directory / 'progress.json', {**snapshot(db_path, breaker), 'last_task': entry['task'],
              'last_request': request_sha, 'stop_reason': stopped, 'queue': request_file.name})
        print(json.dumps({'task': entry['task'], 'status': record['status'], 'known_tokens': known}), flush=True)
    result = {**snapshot(db_path, breaker), 'stop_reason': stopped,
              'queue': request_file.name, 'queue_finished': stopped is None}
    write(directory / (request_file.stem + '.completed.json'), result)
    print(json.dumps(result), flush=True)
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('directory', type=Path)
    parser.add_argument('requests', type=Path)
    args = parser.parse_args()
    run(args.directory, args.requests)
