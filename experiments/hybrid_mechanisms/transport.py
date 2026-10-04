"""Single-attempt research HTTP with one durable, provider-qualified budget.

Reservations precede network access. Interrupted calls remain charged and cannot
be retried. Provider failures stop that provider; separately planned requests to
another provider still share the same global ledger. No data are shortened.
"""
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import re
import time
import urllib.error
import urllib.request

from experiments.research_v3.pilot import credentials, NoRedirect
from guardian_truth.parsing import decode_json
from guardian_truth.source_search.store import digest

ENDPOINTS = {
    'mistral': 'https://api.mistral.ai/v1/chat/completions',
    'ollama': 'https://ollama.com/v1/chat/completions',
}
HTTP_LIMIT = 36
TOKEN_LIMIT = 280000
TIMEOUT = 120


def read(path):
    value, valid = decode_json(Path(path).read_text(encoding='utf-8'))
    if not valid:
        raise ValueError('INVALID_OR_DUPLICATE_JSON')
    return value


def save(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    temp = path.with_suffix(path.suffix + '.tmp')
    with temp.open('w', encoding='utf-8', newline='\n') as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n')
        handle.flush()
        os.fsync(handle.fileno())
    temp.replace(path)


def serialized(body):
    return json.dumps(body, ensure_ascii=False, separators=(',', ':'), allow_nan=False).encode('utf-8')


def bound(body, reservation_fn=None):
    """Callback bounds ALL serialized input, including schema/template overhead.

    The default one-token-per-UTF8-byte bound is conservative for these BPE
    providers, with 2048 additional chat-template tokens and capped output.
    A callback supplies a conservative input-token estimate, not total tokens.
    """
    maximum = body.get('max_tokens')
    if type(maximum) is not int or maximum < 1:
        raise ValueError('OUTPUT_CAP_REQUIRED')
    encoded = serialized(body)
    estimate = len(encoded) if reservation_fn is None else reservation_fn(body)
    if type(estimate) is not int or estimate < 1:
        raise ValueError('INVALID_INPUT_RESERVATION')
    return estimate + maximum + 2048


def valid_usage(data, output_cap=None):
    usage = data.get('usage') if isinstance(data, dict) else None
    if not isinstance(usage, dict):
        return None
    total, prompt, completion = (usage.get(k) for k in ('total_tokens', 'prompt_tokens', 'completion_tokens'))
    if any(type(n) is not int for n in (total, prompt, completion)):
        return None
    if min(prompt, completion) < 0 or total < 1 or prompt + completion != total:
        return None
    if output_cap is not None and completion > output_cap:
        return None
    return total


@contextmanager
def _lock(out):
    """OS-backed lock releases on process death; no stale lock deletion needed."""
    out.mkdir(parents=True, exist_ok=True)
    with (out / '.budget.lock').open('a+b') as handle:
        if os.name == 'nt':
            import msvcrt
            if handle.seek(0, os.SEEK_END) == 0:
                handle.write(b'0'); handle.flush()
            handle.seek(0)
            try:
                msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError as exc:
                raise ValueError('RUN_ALREADY_ACTIVE') from exc
            try:
                yield
            finally:
                handle.seek(0); msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
        else:
            import fcntl
            try:
                fcntl.flock(handle.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except OSError as exc:
                raise ValueError('RUN_ALREADY_ACTIVE') from exc
            try:
                yield
            finally:
                fcntl.flock(handle.fileno(), fcntl.LOCK_UN)


class Client:
    def __init__(self, out, protocol, reservation_fn=None, live=False):
        self.out = Path(out)
        self.protocol = protocol
        self.reservation_fn = reservation_fn
        self.live = live
        self.new_http = 0
        if protocol.get('protocol_sha256') != digest({k: v for k, v in protocol.items() if k != 'protocol_sha256'}):
            raise ValueError('PROTOCOL_CHANGED')
        self.limits = protocol.get('limits', {'http': HTTP_LIMIT, 'tokens': TOKEN_LIMIT})
        if any(type(self.limits.get(k)) is not int or not 1 <= self.limits[k] <= cap
               for k, cap in [('http', HTTP_LIMIT), ('tokens', TOKEN_LIMIT)]):
            raise ValueError('LIMITS_INVALID')
        if not isinstance(protocol.get('providers'), dict) or not protocol['providers']:
            raise ValueError('PROVIDERS_REQUIRED')
        for provider, config in protocol['providers'].items():
            if provider not in ENDPOINTS or config.get('endpoint', ENDPOINTS[provider]) != ENDPOINTS[provider]:
                raise ValueError('ENDPOINT_NOT_APPROVED')
            if not isinstance(config.get('model'), str) or not config['model']:
                raise ValueError('MODEL_REQUIRED')
            if type(config.get('context_limit')) is not int or config['context_limit'] < 1:
                raise ValueError('CONTEXT_LIMIT_REQUIRED')
        self._load()

    def _load(self):
        self.ledger = read(self.out / 'ledger.json') if (self.out / 'ledger.json').exists() else {}
        if not isinstance(self.ledger, dict):
            raise ValueError('LEDGER_INVALID')
        for key, item in self.ledger.items():
            if not re.fullmatch('[0-9a-f]{64}', key) or not isinstance(item, dict):
                raise ValueError('LEDGER_INVALID')
            for field in ('charged_tokens', 'known_tokens', 'reservation_tokens'):
                if type(item.get(field)) is not int or item[field] < 0:
                    raise ValueError('LEDGER_INVALID')
            if item.get('protocol_sha256') != self.protocol['protocol_sha256']:
                raise ValueError('LEDGER_PROTOCOL_CHANGED')
            if item.get('request_sha256') != key or not re.fullmatch('[0-9a-f]{64}', str(item.get('body_sha256', ''))):
                raise ValueError('LEDGER_REQUEST_INVALID')
            if item.get('provider') not in self.protocol['providers'] or type(item.get('unknown_usage')) is not bool:
                raise ValueError('LEDGER_INVALID')
            config = self.protocol['providers'][item['provider']]
            if item.get('model') != config['model'] or item.get('endpoint') != ENDPOINTS[item['provider']]:
                raise ValueError('LEDGER_PROVIDER_CHANGED')
            if item.get('status') not in ('RESERVED', 'OK', 'HTTP_ERROR', 'TRANSPORT_ERROR', 'PROVIDER_JSON_INVALID'):
                raise ValueError('LEDGER_STATUS_INVALID')
            if item['charged_tokens'] < item['known_tokens'] or (item['unknown_usage'] and item['charged_tokens'] < item['reservation_tokens']):
                raise ValueError('LEDGER_CHARGE_INVALID')
            if not item['unknown_usage'] and (item['known_tokens'] < 1 or item['charged_tokens'] != item['known_tokens']):
                raise ValueError('LEDGER_VERIFIED_CHARGE_INVALID')
            if item['status'] == 'RESERVED' and (not item['unknown_usage'] or item['known_tokens'] != 0):
                raise ValueError('LEDGER_PENDING_INVALID')
        if len(self.ledger) > self.limits['http']:
            raise ValueError('LEDGER_HTTP_OVER_LIMIT')
        # A provider reporting more than the conservative reservation is retained
        # honestly, never clipped. It stops all further inference below.
        self.breakers = {item['provider'] for item in self.ledger.values()
                         if item['status'] != 'OK' or item['unknown_usage']}

    def summary(self):
        self._load()
        return {'attempts': len(self.ledger), 'known_tokens': sum(i['known_tokens'] for i in self.ledger.values()),
                'charged_tokens': sum(i['charged_tokens'] for i in self.ledger.values()),
                'unknown_usages': sum(i['unknown_usage'] for i in self.ledger.values()), 'new_http': self.new_http,
                'providers': {p: {'attempts': sum(i['provider'] == p for i in self.ledger.values()),
                                 'known_tokens': sum(i['known_tokens'] for i in self.ledger.values() if i['provider'] == p),
                                 'charged_tokens': sum(i['charged_tokens'] for i in self.ledger.values() if i['provider'] == p)}
                              for p in self.protocol['providers']}}

    def ask(self, name, provider, body):
        with _lock(self.out):
            return self._ask_locked(name, provider, body)

    def _ask_locked(self, name, provider, body):
        self._load()
        if provider not in self.protocol['providers']:
            raise ValueError('UNPLANNED_PROVIDER')
        config = self.protocol['providers'][provider]
        if body.get('model') != config['model']:
            raise ValueError('UNPLANNED_MODEL')
        endpoint = ENDPOINTS[provider]
        reservation = bound(body, self.reservation_fn)
        wire = serialized(body)
        wire_sha = hashlib.sha256(wire).hexdigest()
        key = digest({'provider': provider, 'endpoint': endpoint, 'wire_sha256': wire_sha,
                      'protocol_sha256': self.protocol['protocol_sha256']})
        rawpath, requestpath = self.out / 'raw' / (key + '.json'), self.out / 'requests' / (key + '.json')
        if rawpath.exists():
            if key not in self.ledger:
                raise ValueError('ORPHAN_RAW_RESPONSE')
            item = self.ledger[key]
            if item['status'] == 'RESERVED':
                # Crash after saving raw but before its hash/accounting commit:
                # preserve conservative charge and decline to trust/retry it.
                return None, 'PRIOR_RESERVED_NO_RETRY'
            record = read(rawpath)
            if item.get('raw_sha256') != hashlib.sha256(rawpath.read_bytes()).hexdigest():
                raise ValueError('RAW_CHANGED')
            if not requestpath.exists():
                raise ValueError('REQUEST_CHANGED')
            saved_request = read(requestpath)
            if serialized(saved_request.get('body')) != wire or saved_request != {'body': body, 'request_sha256': key,
                    'body_sha256': wire_sha, 'protocol_sha256': self.protocol['protocol_sha256'],
                    'provider': provider, 'endpoint': endpoint, 'model': config['model'],
                    'reservation_tokens': reservation}:
                raise ValueError('REQUEST_CHANGED')
            for field in ('request_sha256', 'body_sha256', 'protocol_sha256', 'provider', 'endpoint', 'model', 'status',
                          'charged_tokens', 'known_tokens', 'reservation_tokens', 'unknown_usage', 'name'):
                if item.get(field) != record.get(field):
                    raise ValueError('RAW_LEDGER_MISMATCH')
            return record, None
        if key in self.ledger:
            return None, 'PRIOR_RESERVED_NO_RETRY'
        if reservation > config['context_limit']:
            return None, 'CONTEXT_STOP'
        if provider in self.breakers:
            return None, 'PROVIDER_BREAKER_NO_RETRY'
        if len(self.ledger) >= self.limits['http'] or sum(i['charged_tokens'] for i in self.ledger.values()) + reservation > self.limits['tokens']:
            return None, 'BUDGET_STOP'
        if not self.live:
            return None, 'CACHE_MISS_OFFLINE'
        secret = credentials(provider)
        if not secret:
            return None, 'CREDENTIAL_UNAVAILABLE'
        request_record = {'body': body, 'request_sha256': key, 'body_sha256': wire_sha,
                          'protocol_sha256': self.protocol['protocol_sha256'], 'provider': provider,
                          'endpoint': endpoint, 'model': config['model'], 'reservation_tokens': reservation}
        save(requestpath, request_record)
        record = {k: v for k, v in request_record.items() if k != 'body'}
        record.update(name=name, status='RESERVED', charged_tokens=reservation, known_tokens=0, unknown_usage=True)
        self.ledger[key] = dict(record)
        save(self.out / 'ledger.json', self.ledger)
        started = time.monotonic()
        self.new_http += 1
        try:
            request = urllib.request.Request(endpoint, data=wire, headers={
                'Content-Type': 'application/json', 'Authorization': 'Bearer ' + secret})
            with urllib.request.build_opener(NoRedirect()).open(request, timeout=TIMEOUT) as response:
                text = response.read().decode('utf-8')
            data, valid = decode_json(text)
            record['provider_response_text'] = text
            if not valid or not isinstance(data, dict):
                record['status'] = 'PROVIDER_JSON_INVALID'
            else:
                record.update(status='OK', provider_response=data, actual_model=data.get('model'))
        except urllib.error.HTTPError as exc:
            record.update(status='HTTP_ERROR', http_status=exc.code)
        except Exception as exc:
            record.update(status='TRANSPORT_ERROR', error_type=type(exc).__name__)
        usage = valid_usage(record.get('provider_response'), body['max_tokens'])
        record.update(seconds=time.monotonic() - started, known_tokens=usage or 0,
                      charged_tokens=usage if usage is not None else reservation, unknown_usage=usage is None)
        save(rawpath, record)
        self.ledger[key] = {k: v for k, v in record.items()
                            if k not in ('provider_response_text', 'provider_response')}
        self.ledger[key]['raw_sha256'] = hashlib.sha256(rawpath.read_bytes()).hexdigest()
        save(self.out / 'ledger.json', self.ledger)
        return record, None


def preflight(provider, expected_model):
    """Read-only models GET; metadata requests do not consume inference budget."""
    if provider not in ENDPOINTS:
        raise ValueError('UNPLANNED_PROVIDER')
    endpoint = ENDPOINTS[provider].removesuffix('/chat/completions') + '/models'
    secret = credentials(provider)
    if not secret:
        return {'provider': provider, 'expected_model': expected_model, 'status': 'CREDENTIAL_UNAVAILABLE', 'inference_http': 0}
    try:
        request = urllib.request.Request(endpoint, headers={'Authorization': 'Bearer ' + secret})
        with urllib.request.build_opener(NoRedirect()).open(request, timeout=30) as response:
            data, valid = decode_json(response.read().decode('utf-8'))
        if not valid or not isinstance(data, dict) or not isinstance(data.get('data'), list):
            return {'provider': provider, 'expected_model': expected_model, 'status': 'MODELS_JSON_INVALID', 'inference_http': 0}
        models = [m for m in data['data'] if isinstance(m, dict) and m.get('id') == expected_model]
        return {'provider': provider, 'expected_model': expected_model, 'status': 'READY' if len(models) == 1 else 'MODEL_UNAVAILABLE',
                'metadata': models[0] if len(models) == 1 else None, 'inference_http': 0}
    except urllib.error.HTTPError as exc:
        return {'provider': provider, 'expected_model': expected_model, 'status': 'HTTP_ERROR', 'http_status': exc.code, 'inference_http': 0}
    except Exception as exc:
        return {'provider': provider, 'expected_model': expected_model, 'status': 'TRANSPORT_ERROR', 'error_type': type(exc).__name__, 'inference_http': 0}
