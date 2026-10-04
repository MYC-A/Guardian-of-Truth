"""Crash recovery and phase identity checks without any network access."""
import importlib.util
import json
from pathlib import Path
import sqlite3
import urllib.error

import pytest


PATH = (Path(__file__).resolve().parents[1] / 'experiments' / 'searh_23'
        / 'evidence_graph_search_probe' / 'api_worker_v2.py')
SPEC = importlib.util.spec_from_file_location('evidence_graph_api_worker_v2', PATH)
worker = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(worker)


def phase(tmp_path, count=2):
    config = {'model_id': 'frozen-model', 'limits': {'http': 10, 'tokens': 100000}, 'timeout': 10}
    config['protocol_sha256'] = worker.digest(config)
    worker.write(tmp_path / 'protocol.json', config)
    entries = []
    for index in range(count):
        body = {'model': config['model_id'], 'max_tokens': 20,
                'messages': [{'role': 'user', 'content': str(index)}]}
        entries.append({'request_sha256': worker.digest(body), 'task': 'EFFECT', 'wire_body': body})
    queue = tmp_path / 'initial.jsonl'
    queue.write_text(''.join(json.dumps(entry) + '\n' for entry in entries), encoding='utf-8')
    worker.write(queue.with_suffix('.seal.json'), {
        'queue_sha256': worker.hashlib.sha256(queue.read_bytes()).hexdigest(),
        'protocol_sha256': config['protocol_sha256'], 'requests': count})
    return config, entries, queue


def receipt(directory, config, entry, status='OK', **overrides):
    record = {'protocol_sha256': config['protocol_sha256'], 'model_id': config['model_id'],
              'request_sha256': entry['request_sha256'], 'task': entry['task'],
              'status': status, 'known_tokens': 7, 'unknown_usage_upper_bound': 0, 'seconds': 1.25}
    if status == 'OK':
        record['provider_response'] = {'usage': {'total_tokens': 7}, 'choices': []}
    elif status == 'HTTP_ERROR':
        record.update(http_status=429, known_tokens=0, unknown_usage_upper_bound=200)
    elif status == 'TRANSPORT_ERROR':
        record.update(error_type='TimeoutError', known_tokens=0, unknown_usage_upper_bound=200)
    record.update(overrides)
    worker.write(directory / 'raw' / (entry['request_sha256'] + '.json'), record)
    return record


def saved_attempt(directory, entry, status='RESERVED', known=0, unknown=200, seconds=0):
    with sqlite3.connect(directory / 'budget.sqlite') as db:
        db.execute('CREATE TABLE IF NOT EXISTS attempts(id INTEGER PRIMARY KEY, '
                   'request_sha TEXT UNIQUE, status TEXT, known_tokens INTEGER, '
                   'unknown_bound INTEGER, seconds REAL)')
        db.execute('INSERT INTO attempts(request_sha,status,known_tokens,unknown_bound,seconds) '
                   'VALUES(?,?,?,?,?)', (entry['request_sha256'], status, known, unknown, seconds))


@pytest.fixture(autouse=True)
def forbid_http(monkeypatch):
    def forbidden(*args, **kwargs):
        raise AssertionError('No HTTP call is allowed in recovery tests')
    monkeypatch.setattr(worker, '_open_http', forbidden)
    monkeypatch.setattr(worker, 'credentials', lambda: {
        'MISTRAL_API_KEY': 'test-secret-never-written', 'MISTRAL_MODEL': 'frozen-model'})


@pytest.mark.parametrize('status', ['HTTP_ERROR', 'TRANSPORT_ERROR'])
def test_saved_raw_error_stops_later_http_and_stays_stopped(tmp_path, status):
    config, entries, queue = phase(tmp_path)
    # Reproduce interruption after raw save, before ledger/breaker updates.
    saved_attempt(tmp_path, entries[0])
    receipt(tmp_path, config, entries[0], status)
    result = worker.run(tmp_path, queue)
    assert result['breaker_open'] and not result['queue_finished']
    assert result['attempts'] == 1 and result['pending'] == 0
    assert worker.read(tmp_path / 'breaker.json')['automatic_retries'] == 0
    assert not (tmp_path / 'raw' / (entries[1]['request_sha256'] + '.json')).exists()
    assert not worker.run(tmp_path, queue)['queue_finished']


def test_saved_error_outside_current_queue_also_stops_phase(tmp_path):
    config, entries, queue = phase(tmp_path, count=1)
    outside = {**entries[0], 'request_sha256': 'a' * 64}
    receipt(tmp_path, config, outside, 'HTTP_ERROR')
    result = worker.run(tmp_path, queue)
    assert result['stop_reason'] == 'HTTP_429'
    assert result['attempts'] == 1


def test_sqlite_error_without_receipt_stops_later_http(tmp_path):
    _, entries, queue = phase(tmp_path)
    saved_attempt(tmp_path, entries[0], status='HTTP_ERROR')
    result = worker.run(tmp_path, queue)
    assert result['stop_reason'] == 'SAVED_HTTP_ERROR'
    assert result['breaker_open'] and result['attempts'] == 1


def test_reserved_without_response_never_retries_or_advances(tmp_path):
    _, entries, queue = phase(tmp_path)
    # Even a different queue entry cannot pass an unknown prior attempt.
    outside = {**entries[0], 'request_sha256': 'b' * 64}
    saved_attempt(tmp_path, outside)
    result = worker.run(tmp_path, queue)
    assert result['stop_reason'] == 'PRIOR_ATTEMPT_WITHOUT_SAVED_RESPONSE_NO_RETRY'
    assert result['attempts'] == result['pending'] == 1
    assert result['breaker_open']
    assert worker.run(tmp_path, queue)['attempts'] == 1


@pytest.mark.parametrize('field,value,cause', [
    ('protocol_sha256', '0' * 64, 'CACHE_PROTOCOL_MISMATCH'),
    ('model_id', 'other-model', 'CACHE_MODEL_MISMATCH'),
    ('request_sha256', 'c' * 64, 'CACHE_FILENAME_OR_REQUEST_MISMATCH'),
    ('task', 'INVENTORY', 'CACHE_TASK_MISMATCH'),
])
def test_wrong_cache_identity_stops_before_http(tmp_path, field, value, cause):
    config, entries, queue = phase(tmp_path)
    receipt(tmp_path, config, entries[0], **{field: value})
    with pytest.raises(ValueError, match=cause):
        worker.run(tmp_path, queue)


def test_renamed_cache_file_is_rejected(tmp_path):
    config, entries, queue = phase(tmp_path)
    receipt(tmp_path, config, entries[0])
    path = tmp_path / 'raw' / (entries[0]['request_sha256'] + '.json')
    path.rename(path.with_name('copied.json'))
    with pytest.raises(ValueError, match='CACHE_FILENAME_OR_REQUEST_MISMATCH'):
        worker.run(tmp_path, queue)


def test_valid_cache_skipped_and_charged_without_credentials(tmp_path, monkeypatch):
    config, entries, queue = phase(tmp_path, count=1)
    receipt(tmp_path, config, entries[0])
    def no_credentials():
        raise AssertionError('Cached requests do not need credentials')
    monkeypatch.setattr(worker, 'credentials', no_credentials)
    result = worker.run(tmp_path, queue)
    assert result['queue_finished'] and result['stop_reason'] is None
    assert result['attempts'] == 1 and result['known_tokens'] == 7
    assert worker.run(tmp_path, queue)['attempts'] == 1


def test_reserved_with_saved_success_reconciles_without_retry(tmp_path):
    config, entries, queue = phase(tmp_path, count=1)
    saved_attempt(tmp_path, entries[0])
    receipt(tmp_path, config, entries[0])
    result = worker.run(tmp_path, queue)
    assert result['queue_finished'] and result['pending'] == 0
    assert result['known_tokens'] == 7 and result['unknown_bound'] == 0


def test_database_cannot_be_rebound_to_changed_protocol(tmp_path):
    config, entries, queue = phase(tmp_path, count=1)
    receipt(tmp_path, config, entries[0])
    worker.run(tmp_path, queue)
    (tmp_path / 'raw' / (entries[0]['request_sha256'] + '.json')).unlink()
    config.pop('protocol_sha256')
    config['limits']['http'] += 1
    config['protocol_sha256'] = worker.digest(config)
    worker.write(tmp_path / 'protocol.json', config)
    seal = worker.read(queue.with_suffix('.seal.json'))
    seal['protocol_sha256'] = config['protocol_sha256']
    worker.write(queue.with_suffix('.seal.json'), seal)
    with pytest.raises(ValueError, match='BUDGET_PROTOCOL_OR_MODEL_MISMATCH'):
        worker.run(tmp_path, queue)


def test_first_live_error_is_reserved_saved_and_never_retried(tmp_path, monkeypatch):
    _, entries, queue = phase(tmp_path)
    called = []
    def http_error(request, timeout):
        called.append(request.full_url)
        raise urllib.error.HTTPError(request.full_url, 429, 'rate limit', {}, None)
    monkeypatch.setattr(worker, '_open_http', http_error)
    result = worker.run(tmp_path, queue)
    assert called == [worker.ENDPOINT]
    assert result['stop_reason'] == 'HTTP_429' and result['attempts'] == 1
    assert result['unknown_bound'] > 0 and result['known_tokens'] == 0
    raw = tmp_path / 'raw' / (entries[0]['request_sha256'] + '.json')
    assert worker.read(raw)['status'] == 'HTTP_ERROR'
    assert 'test-secret' not in raw.read_text(encoding='utf-8')
    assert not worker.run(tmp_path, queue)['queue_finished']
    assert called == [worker.ENDPOINT]


def test_crash_before_receipt_save_keeps_reservation_and_prevents_retry(tmp_path, monkeypatch):
    _, _, queue = phase(tmp_path)
    called = []
    class Response:
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
        def read(self):
            return b'{"usage":{"total_tokens":9},"choices":[]}'
    def success(request, timeout):
        called.append(request.full_url)
        return Response()
    monkeypatch.setattr(worker, '_open_http', success)
    real_write = worker.write
    def crash(path, obj):
        if path.parent.name == 'raw':
            raise OSError('simulated crash before durable receipt')
        return real_write(path, obj)
    monkeypatch.setattr(worker, 'write', crash)
    with pytest.raises(OSError, match='simulated crash'):
        worker.run(tmp_path, queue)
    monkeypatch.setattr(worker, 'write', real_write)
    result = worker.run(tmp_path, queue)
    assert result['pending'] == result['attempts'] == 1
    assert result['stop_reason'] == 'PRIOR_ATTEMPT_WITHOUT_SAVED_RESPONSE_NO_RETRY'
    assert called == [worker.ENDPOINT]


def test_tampered_request_body_rejected_even_with_fresh_queue_seal(tmp_path):
    _, entries, queue = phase(tmp_path)
    entries[1]['wire_body']['max_tokens'] += 1
    queue.write_text(''.join(json.dumps(entry) + '\n' for entry in entries), encoding='utf-8')
    seal = worker.read(queue.with_suffix('.seal.json'))
    seal['queue_sha256'] = worker.hashlib.sha256(queue.read_bytes()).hexdigest()
    worker.write(queue.with_suffix('.seal.json'), seal)
    with pytest.raises(ValueError, match='REQUEST_CHANGED'):
        worker.run(tmp_path, queue)
