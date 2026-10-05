"""verification-v2 runner (protocol §7).
  python -m experiments.verification_v2.run --set lb_long|lb_short|valid46 [--ids a,b] [--workers 3] [--rep 1]
Inference sees only prompt/response. Records are appended per row; on resume the last record per id
wins and rows containing a transport failure are re-run (successful steps replay from the cache)."""
import argparse, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.integrated import transport as T
from guardian_truth.verification import run_row

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/verification_v2'
MODEL = 'ministral-14b-2512'
MAX_CALLS = 1400   # amendment 2 (was 900)
_lock, _last = threading.Lock(), [0.0]
MIN_INTERVAL = 1.2


def paced(url, key, payload, timeout=180):
    with _lock:
        wait = _last[0] + MIN_INTERVAL - time.time()
        if wait > 0:
            time.sleep(wait)
        _last[0] = time.time()
    return T.post(url, key, payload, timeout=timeout)


def inputs(name):
    if name == 'valid46':
        import pandas as pd
        return [dict(id=r.id, prompt=r.prompt, response=r.response) for r in pd.read_parquet(ROOT / 'valid.parquet').itertuples()]
    box, sub = {'lb_long': ('lockbox', 'long'), 'lb_short': ('lockbox', 'short'), 'lb2_long': ('lockbox2', 'long')}[name]
    return [json.loads(x) for x in (OUT / box / sub / 'inputs.jsonl').read_text().splitlines()]


def failed(rec):
    steps = list(rec.get('A', {}).get('steps', []))
    for k in ('B', 'C', 'E', 'Av'):
        x = rec.get(k)
        if x:
            steps.append(x)
            if x.get('verify'):
                steps.append(x['verify'])
    return 'error' in rec or any(s.get('admission') == 'TRANSPORT_FAILURE' for s in steps)


def load(path):
    recs = {}
    if path.exists():
        for line in path.read_text().splitlines():
            r = json.loads(line)
            recs[r['id']] = r
    return recs


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True)
    ap.add_argument('--ids')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--offline', action='store_true')
    ap.add_argument('--mechanisms', default='B,C')
    ap.add_argument('--tag', default='')
    a = ap.parse_args()
    client = Transport('mistral', MODEL, OUT / 'cache' / 'mistral', max_calls=MAX_CALLS, retry_failed=3, sender=paced, offline=a.offline)
    path = OUT / 'runs' / a.set / f'rep{a.rep}{a.tag}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    have = load(path)
    rows = [r for r in inputs(a.set) if (not a.ids or r['id'] in a.ids.split(',')) and (r['id'] not in have or failed(have[r['id']]))]
    lock = threading.Lock()

    def one(r):
        try:
            rec = run_row(r, client, model=MODEL, attempt=a.rep - 1, mechanisms=tuple(a.mechanisms.split(',')))
        except Exception as e:
            rec = dict(error=f'{type(e).__name__}: {e}'[:300])
        rec = dict(id=r['id'], rep=a.rep, **rec)
        with lock:
            with open(path, 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                f.flush(); os.fsync(f.fileno())
            c, b, e = rec.get('C') or {}, rec.get('B') or {}, rec.get('E') or {}
            print(a.set, r['id'][:40], 'A', (rec.get('A') or {}).get('final'), 'B', b.get('decision'), (b.get('verify') or {}).get('verdict'),
                  'C', c.get('original_status'), (c.get('verify') or {}).get('verdict'), 'E', e.get('admission'), bool(e.get('candidate')), (e.get('verify') or {}).get('verdict'), 'Av', (rec.get('Av') or {}).get('verdict'),
                  'FAIL' if failed(rec) else '', rec.get('error', ''), flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, rows))
    print('counts', client.counts, 'sent', client.sent)


if __name__ == '__main__':
    main()
