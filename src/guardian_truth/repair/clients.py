"""Read-through model client (stability contract). Exact cache key = (provider, endpoint, model, request, attempt),
identical to integrated.transport.Transport. Frozen caches are read-only; a miss goes to the live transport if one
is given, otherwise it is reported as NOT_EXECUTED_OFFLINE (content None) and counted — never invented."""
from __future__ import annotations

from collections import Counter
import json
from pathlib import Path
import threading

from ..integrated.transport import PROVIDERS, sha


class ReadThrough:
    def __init__(self, provider, model, frozen_dirs, live=None):
        self.provider, self.model = provider, model
        self.endpoint = PROVIDERS[provider][0]
        self.frozen = [Path(d) for d in frozen_dirs]
        self.live = live
        self.counts = Counter()
        self.lock = threading.Lock()
        self.missing = []

    def key(self, request, attempt):
        return sha(dict(provider=self.provider, endpoint=self.endpoint, model=self.model, request=request, attempt=attempt))

    def call(self, request, attempt=0, tag=''):
        if request.get('model') != self.model:
            raise ValueError('REQUEST_MODEL_MISMATCH')
        key = self.key(request, attempt)
        for i, d in enumerate(self.frozen):
            p = d / key[:2] / f'{key}.json'
            if p.exists():
                with self.lock:
                    self.counts[f'frozen{i}'] += 1
                return dict(json.loads(p.read_text(encoding='utf-8')), cached=True)
        if self.live is not None:
            r = self.live.call(request, attempt=attempt, tag=tag)
            with self.lock:
                self.counts['live_cached' if r.get('cached') else 'live_sent'] += 1
            return r
        with self.lock:
            self.counts['not_executed'] += 1
            self.missing.append(dict(tag=tag, key=key))
        return dict(key=key, content=None, cached=False, transport=dict(status='NOT_EXECUTED_OFFLINE'), usage=None, tag=tag)
