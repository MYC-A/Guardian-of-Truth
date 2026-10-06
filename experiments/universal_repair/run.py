"""Universal-repair runner (docs/universal_repair/PROTOCOL.md, RUNBOOK.md).
  python -X utf8 -m experiments.universal_repair.run --set lb2_long --rep 1 --arm R_comb [--live] [--workers 3]
Offline (default): frozen caches only; misses -> NOT_EXECUTED. --live: misses go to Mistral through a budgeted,
ledgered transport (outputs/universal_repair/cache/mistral). Records append per row; resume re-runs failed rows."""
import argparse, json, os, threading, time
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.integrated import transport as T
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.records import failed
from guardian_truth.repair.v5 import ARMS, run_v5

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/universal_repair'
MODEL = 'ministral-14b-2512'
FROZEN = [ROOT / 'outputs/verification_v2/cache/mistral', Path('/data/gi/outputs/verification_v2/cache/mistral')]
MAX_CALLS = 2500
_lock, _last = threading.Lock(), [0.0]
MIN_INTERVAL = 2.1      # ministral-14b tier: 30 requests/minute (x-ratelimit-limit-req-minute)


def paced(url, key, payload, timeout=180):
    """Pacing + bounded backoff on 429/5xx inside one ledgered attempt (every HTTP try is logged separately)."""
    for k in range(5):
        with _lock:
            wait = _last[0] + MIN_INTERVAL - time.time()
            if wait > 0:
                time.sleep(wait)
            _last[0] = time.time()
        data, log = T.post(url, key, payload, timeout=timeout)
        with open(OUT / 'cache' / 'http_tries.jsonl', 'a', encoding='utf-8') as f:
            f.write(json.dumps(dict(at=time.time(), status=log.get('status'), seconds=log.get('seconds'), try_index=k)) + '\n')
        if log.get('status') in (429, 500, 502, 503, 504, 'EXC'):
            time.sleep(4 * (k + 1))
            continue
        return data, log
    return data, log


def inputs(name):
    if name == 'valid46':
        import pandas as pd
        return [dict(id=r.id, prompt=r.prompt, response=r.response) for r in pd.read_parquet(ROOT / 'valid.parquet').itertuples()]
    if name.startswith('ext_'):
        p = ROOT / 'outputs/verification_v4/external' / name[4:] / 'inputs.jsonl'
    elif name.startswith('hold_'):
        p = ROOT / 'outputs/universal_repair/holdout' / name[5:] / 'inputs.jsonl'
    else:
        box = {'lb_long': 'lockbox', 'lb2_long': 'lockbox2', 'lb3_long': 'lockbox3'}[name]
        p = ROOT / 'outputs/verification_v2' / box / 'long/inputs.jsonl'
    return [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines() if x.strip()]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--set', required=True)
    ap.add_argument('--rep', type=int, default=1)
    ap.add_argument('--arm', required=True, choices=sorted(ARMS))
    ap.add_argument('--live', action='store_true')
    ap.add_argument('--cb', action='store_true', help='also run CB (shadow)')
    ap.add_argument('--workers', type=int, default=3)
    ap.add_argument('--ids')
    ap.add_argument('--runs-dir', default='runs', help='output subdir of outputs/universal_repair (v2: ../universal_repair_v2/runs)')
    ap.add_argument('--with-live-cache', action='store_true',
                    help='offline: also read the committed live cache (outputs/universal_repair/cache/mistral) exact-key')
    a = ap.parse_args()
    live = None
    if a.live:
        (OUT / 'cache').mkdir(parents=True, exist_ok=True)
        live = Transport('mistral', MODEL, OUT / 'cache' / 'mistral', max_calls=MAX_CALLS, retry_failed=3, sender=paced)
    frozen = FROZEN + ([OUT / 'cache' / 'mistral'] if a.with_live_cache and not a.live else [])
    client = ReadThrough('mistral', MODEL, frozen, live=live)
    mode = 'live' if a.live else 'offline'
    path = OUT / a.runs_dir / a.set / f'rep{a.rep}_{a.arm}{"_cb" if a.cb else ""}_{mode}.jsonl'
    path.parent.mkdir(parents=True, exist_ok=True)
    have = {}
    if path.exists():
        for line in path.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            have[r['id']] = r
    rows = [r for r in inputs(a.set) if (not a.ids or r['id'] in a.ids.split(',')) and (r['id'] not in have or failed(have[r['id']]))]
    lock = threading.Lock()
    flags = ARMS[a.arm] | ({'confirm'} if a.cb and a.arm != 'V4r' else set())

    def one(r):
        try:
            rec = run_v5(r, client, flags=flags, attempt=a.rep - 1, with_cb=a.cb)
        except Exception as e:
            rec = dict(error=f'{type(e).__name__}: {e}'[:300])
        rec = dict(id=r['id'], rep=a.rep, arm=a.arm, mode=mode, **rec)
        with lock:
            with open(path, 'a', encoding='utf-8', newline='\n') as f:
                f.write(json.dumps(rec, ensure_ascii=False) + '\n')
                f.flush(); os.fsync(f.fileno())
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(one, rows))
    print(a.set, a.rep, a.arm, mode, 'rows', len(rows), dict(client.counts), 'live' if live is None else live.counts, flush=True)


if __name__ == '__main__':
    main()
