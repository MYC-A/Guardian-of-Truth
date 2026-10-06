"""Study-wide inference budget, shared by every process and model (file lock + append-only ledger).
Before each HTTP try a reservation (1 request, estimated tokens, estimated USD at confirmed list prices) is written; the
call is refused when any cap would be exceeded. One try per call: 5xx/timeout are NOT retried (they count as used);
HTTP 429 (rate limit, no inference) releases the reservation and is retried visibly at most 3 times, each try logged.
Tariffs (USD per 1M tokens, list price, docs.mistral.ai model pages fetched for this study):
  ministral-14b-2512  in 0.20 / out 0.20
  mistral-large-4     in 1.36 / out 4.18   (launch discount 0.68 / 2.09 exists; list price used = upper bound)"""
import fcntl, json, os, threading, time
from pathlib import Path

from guardian_truth.integrated import transport as T

ROOT = Path(__file__).resolve().parents[2]
DIR = ROOT / 'outputs/guardian_semantic/budget'
LEDGER, LOCK = DIR / 'ledger.jsonl', DIR / '.lock'
TARIFF = {'ministral-14b-2512': (0.20, 0.20), 'mistral-large-4': (1.36, 4.18)}
CAPS = dict(requests=250, tokens=2_000_000, usd=20.0)
MIN_INTERVAL = 2.2
_pace, _last = threading.Lock(), [0.0]


def usd(model, tin, tout):
    a, b = TARIFF[model]
    return (tin * a + tout * b) / 1e6


def totals():
    req = tok = 0
    cost = 0.0
    open_res = {}
    if LEDGER.exists():
        for e in map(json.loads, LEDGER.read_text().splitlines()):
            if e['ev'] == 'RESERVE':
                open_res[e['rid']] = e
            elif e['ev'] == 'RELEASE':
                open_res.pop(e['rid'], None)
            elif e['ev'] == 'ACTUAL':
                r = open_res.pop(e['rid'], None)
                req += 1; tok += e['tokens']; cost += e['usd']
    for r in open_res.values():                 # in flight (or crashed): count the estimate
        req += 1; tok += r['est_tokens']; cost += r['est_usd']
    return dict(requests=req, tokens=tok, usd=round(cost, 4))


def _log(e):
    with open(LEDGER, 'a') as f:
        f.write(json.dumps(e) + '\n'); f.flush(); os.fsync(f.fileno())


def sender(url, key, payload, timeout=240):
    DIR.mkdir(parents=True, exist_ok=True)
    model = payload['model']
    if model not in TARIFF:
        return None, dict(status='UNKNOWN_TARIFF_REFUSED')
    est_in = len(json.dumps(payload, ensure_ascii=False)) // 3
    est_out = int(payload.get('max_tokens') or 4000)
    for k in range(4):
        rid = f'{os.getpid()}-{time.time_ns()}'
        with open(LOCK, 'w') as lk:
            fcntl.flock(lk, fcntl.LOCK_EX)
            t = totals()
            est_usd = usd(model, est_in, est_out)
            if t['requests'] + 1 > CAPS['requests'] or t['tokens'] + est_in + est_out > CAPS['tokens'] or t['usd'] + est_usd > CAPS['usd']:
                _log(dict(ev='REFUSED', rid=rid, model=model, at=time.time(), totals=t))
                return None, dict(status='BUDGET_REFUSED')
            _log(dict(ev='RESERVE', rid=rid, model=model, at=time.time(), est_tokens=est_in + est_out, est_usd=est_usd, try_index=k))
        with _pace:
            w = _last[0] + MIN_INTERVAL - time.time()
            if w > 0:
                time.sleep(w)
            _last[0] = time.time()
        data, log = T.post(url, key, payload, timeout=timeout)
        if log.get('status') == 429:
            _log(dict(ev='RELEASE', rid=rid, model=model, at=time.time(), status=429))
            time.sleep(6 * (k + 1))
            continue
        u = (data or {}).get('usage') or {}
        tin, tout = u.get('prompt_tokens') or 0, u.get('completion_tokens') or 0
        if not u:                                  # failed try: charge the estimate (conservative)
            tin, tout = est_in, 0
        _log(dict(ev='ACTUAL', rid=rid, model=model, at=time.time(), status=log.get('status'), seconds=log.get('seconds'),
                  tokens=tin + tout, prompt_tokens=tin, completion_tokens=tout, usd=usd(model, tin, tout),
                  response_model=(data or {}).get('model')))
        return data, log
    return None, dict(status='RATE_LIMITED_GAVE_UP')
