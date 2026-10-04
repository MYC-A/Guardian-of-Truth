"""Cached, resumable model calls. Cache key = sha256(request body) + attempt index.
Completed calls are never re-sent; every raw reply, usage and transport log is retained."""
import json, os, threading, time
from experiments.evidence_packer_v2.llm_eval import post, sha
from experiments.multipacket_v1.common import OUT

PROVIDERS = {'mistral': ('https://api.mistral.ai/v1/chat/completions', 'MISTRAL_API_KEY'),
             'ollama': ('https://ollama.com/v1/chat/completions', 'OLLAMA_API_KEY')}
_locks, _glock = {}, threading.Lock()
CACHE = OUT / 'cache'
DRY = os.environ.get('MP_DRY') == '1'   # count/cost estimate only: never sends, never writes


class DryRun(Exception):
    pass


def call(request, provider='mistral', attempt=0, tag=''):
    key = sha(dict(request=request, attempt=attempt))
    path = CACHE / key[:2] / f'{key}.json'
    with _glock:
        lock = _locks.setdefault(key, threading.Lock())
    with lock:
        if path.exists():
            rec = json.loads(path.read_text()); rec['cached'] = True
            return rec
        if DRY:
            raise DryRun(len(json.dumps(request, ensure_ascii=False).encode()))
        url, env = PROVIDERS[provider]
        t = time.time()
        data, log = post(url, os.environ[env], request)
        rec = dict(key=key, request_sha256=sha(request), attempt=attempt, provider=provider, model=request['model'], tag=tag,
                   request_bytes=len(json.dumps(request, ensure_ascii=False).encode()), seconds=round(time.time() - t, 2),
                   transport=log, usage=(data or {}).get('usage'),
                   content=(data or {}).get('choices', [{}])[0].get('message', {}).get('content') if data else None)
        if data is None:      # transport failure: logged in the returned record, never cached
            rec['cached'] = False
            return rec
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(rec, ensure_ascii=False))
        req = OUT / 'requests' / f'{rec["request_sha256"]}.json'   # gitignored; reconstructible from code + cache
        req.parent.mkdir(parents=True, exist_ok=True)
        if not req.exists():
            req.write_text(json.dumps(request, ensure_ascii=False))
        rec['cached'] = False
        return rec
