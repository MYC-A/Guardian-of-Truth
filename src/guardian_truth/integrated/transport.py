"""Durable single-attempt model transport with exact-equivalence cache, budget and network tripwire.

* Cache key = sha256(provider, endpoint, model, request body, attempt index). A cached reply is reused
  only for that exact wire/config; any change of request/model/endpoint/attempt is a new key.
* Every network attempt (and every refusal) is appended to an attempts ledger (JSONL, fsync'ed).
  Budget counters are rebuilt from the ledger on start, so resume / replay never resets them.
* One HTTP attempt per call, no hidden retry, no provider/model substitution. A transport failure is
  logged and NOT cached; `retry_failed` (explicit, default 0) allows that many re-sends per key on resume.
* offline=True: any cache miss raises NetworkTripwire (zero HTTP replay).
Keys are read from environment variables at call time and never written anywhere.
"""
from __future__ import annotations

import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.request
from pathlib import Path

PROVIDERS = {'mistral': ('https://api.mistral.ai/v1/chat/completions', 'MISTRAL_API_KEY'),
             'ollama': ('https://ollama.com/v1/chat/completions', 'OLLAMA_API_KEY')}


class NetworkTripwire(RuntimeError):
    pass


class BudgetExhausted(RuntimeError):
    pass


def sha(x):
    return hashlib.sha256(json.dumps(x, ensure_ascii=False, sort_keys=True).encode()).hexdigest()


def post(url, key, payload, timeout=180):
    req = urllib.request.Request(url, data=json.dumps(payload).encode(), method='POST',
                                 headers={'Authorization': f'Bearer {key}', 'Content-Type': 'application/json'})
    t = time.time()
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return json.loads(r.read()), dict(status=200, seconds=round(time.time() - t, 2))
    except urllib.error.HTTPError as e:
        return None, dict(status=e.code, seconds=round(time.time() - t, 2), body=e.read()[:300].decode('utf-8', 'replace'))
    except Exception as e:  # timeout / connection / decode
        return None, dict(status='EXC', seconds=round(time.time() - t, 2), error=type(e).__name__)


class Transport:
    def __init__(self, provider, model, cache_dir, *, endpoint=None, offline=False, max_calls=None,
                 max_tokens_total=None, retry_failed=0, timeout=180, sender=None):
        if provider not in PROVIDERS and endpoint is None:
            raise ValueError('UNKNOWN_PROVIDER')
        self.provider, self.model = provider, model
        self.endpoint = endpoint or PROVIDERS[provider][0]
        self.key_env = PROVIDERS.get(provider, (None, None))[1]
        self.cache = Path(cache_dir)
        self.cache.mkdir(parents=True, exist_ok=True)
        self.ledger = self.cache / 'attempts.jsonl'
        self.offline, self.max_calls, self.max_tokens_total = offline, max_calls, max_tokens_total
        self.retry_failed, self.timeout = retry_failed, timeout
        self.sender = sender or post
        self.lock = threading.Lock()
        self.inflight = {}
        self.sent = self.tokens = 0
        self.failures = {}
        if self.ledger.exists():
            for line in self.ledger.read_text().splitlines():
                e = json.loads(line)
                if e.get('event') == 'SENT':
                    self.sent += 1
                    self.tokens += (e.get('usage') or {}).get('total_tokens') or 0
                    if not e.get('ok'):
                        self.failures[e['key']] = self.failures.get(e['key'], 0) + 1
        self.counts = dict(cached=0, executed=0, failed=0, refused_budget=0, refused_offline=0)

    def key(self, request, attempt):
        return sha(dict(provider=self.provider, endpoint=self.endpoint, model=self.model, request=request, attempt=attempt))

    def _log(self, entry):
        with open(self.ledger, 'a') as f:
            f.write(json.dumps(entry, ensure_ascii=False) + '\n')
            f.flush(); os.fsync(f.fileno())

    def call(self, request, attempt=0, tag=''):
        if request.get('model') != self.model:
            raise ValueError('REQUEST_MODEL_MISMATCH')
        key = self.key(request, attempt)
        path = self.cache / key[:2] / f'{key}.json'
        with self.lock:
            lock = self.inflight.setdefault(key, threading.Lock())
        with lock:
            if path.exists():
                rec = json.loads(path.read_text())
                with self.lock:
                    self.counts['cached'] += 1
                return dict(rec, cached=True)
            with self.lock:
                if self.offline:
                    self.counts['refused_offline'] += 1
                    raise NetworkTripwire(f'cache miss {key[:12]} in offline mode')
                prior_fail = self.failures.get(key, 0)
                if prior_fail > self.retry_failed:
                    return dict(key=key, content=None, cached=False, transport=dict(status='PRIOR_FAILURE_NOT_RETRIED'),
                                usage=None, tag=tag)
                if (self.max_calls is not None and self.sent >= self.max_calls) or (
                        self.max_tokens_total is not None and self.tokens >= self.max_tokens_total):
                    self.counts['refused_budget'] += 1
                    self._log(dict(event='REFUSED_BUDGET', key=key, tag=tag, sent=self.sent, tokens=self.tokens))
                    return dict(key=key, content=None, cached=False, transport=dict(status='BUDGET_EXHAUSTED'), usage=None, tag=tag)
                self.sent += 1                       # atomic reservation before the network attempt
            api_key = os.environ.get(self.key_env or '')
            if self.sender is post and not api_key:
                raise RuntimeError(f'missing environment key {self.key_env}')
            data, log = self.sender(self.endpoint, api_key, request, timeout=self.timeout)
            choice = ((data or {}).get('choices') or [{}])[0]
            msg = choice.get('message') or {}
            rec = dict(key=key, request_sha256=sha(request), attempt=attempt, provider=self.provider, endpoint=self.endpoint,
                       model=self.model, response_model=(data or {}).get('model'), tag=tag,
                       request_bytes=len(json.dumps(request, ensure_ascii=False).encode()), transport=log,
                       seconds=log.get('seconds'), usage=(data or {}).get('usage'), finish_reason=choice.get('finish_reason'),
                       content=msg.get('content') if data else None,
                       reasoning=msg.get('reasoning') or msg.get('reasoning_content'), created=time.time())
            ok = data is not None and rec['content'] is not None
            with self.lock:
                self.tokens += (rec['usage'] or {}).get('total_tokens') or 0
                self.counts['executed' if ok else 'failed'] += 1
                if not ok:
                    self.failures[key] = self.failures.get(key, 0) + 1
                self._log(dict(event='SENT', key=key, tag=tag, ok=ok, status=log.get('status'), seconds=log.get('seconds'),
                               usage=rec['usage'], finish_reason=rec['finish_reason'], response_model=rec['response_model'],
                               request_bytes=rec['request_bytes'], at=rec['created']))
            if ok:
                path.parent.mkdir(parents=True, exist_ok=True)
                tmp = path.with_suffix('.tmp')
                tmp.write_text(json.dumps(rec, ensure_ascii=False))
                tmp.replace(path)                    # atomic: a crash never leaves a partial cache entry
                req = self.cache / 'requests' / f"{rec['request_sha256']}.json"
                if not req.exists():
                    req.parent.mkdir(parents=True, exist_ok=True)
                    req.write_text(json.dumps(request, ensure_ascii=False))
            return dict(rec, cached=False)


class StaticClient:
    """Test/replay adapter: returns fixed contents from a callable(request) -> str|None. No network."""

    def __init__(self, fn, model='mock-model'):
        self.fn, self.model, self.calls = fn, model, []

    def call(self, request, attempt=0, tag=''):
        self.calls.append(dict(request=request, attempt=attempt, tag=tag))
        content = self.fn(request)
        return dict(key=sha(dict(request=request, attempt=attempt)), content=content, cached=False, usage=None,
                    transport=dict(status=200 if content is not None else 'MOCK_FAILURE'), finish_reason='stop')
