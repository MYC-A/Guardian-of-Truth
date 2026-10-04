"""Run arms over a suite with resumable cached calls; writes per-case JSONL (no packets, no gold).

    python -m experiments.multipacket_v1.run --suite valid46|syn_m1 --arms A,C1,... --run 1 --workers 6"""
import argparse, json, threading, time, traceback
from concurrent.futures import ThreadPoolExecutor
from experiments.multipacket_v1 import arms as AR
from experiments.multipacket_v1.common import OUT, valid_rows


def suite_rows(name):
    if name == 'valid46':
        return list(valid_rows())
    return [json.loads(l) for l in open(OUT / 'suite_syn_m1/inputs.jsonl')]


def slim_step(s):
    out = {k: s.get(k) for k in ('key', 'admission', 'decision', 'usage', 'request_bytes', 'cached', 'seconds')}
    if s.get('admitted') is not None:
        out['admitted'] = s['admitted']
    if s.get('answers') is not None:
        out['answers'] = s['answers']
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--suite', default='valid46'); ap.add_argument('--arms', required=True)
    ap.add_argument('--run', type=int, default=1); ap.add_argument('--workers', type=int, default=6)
    a = ap.parse_args()
    rows = suite_rows(a.suite)
    names = a.arms.split(',')
    if a.suite != 'valid46':
        assert not set(names) & set(AR.ORACLE_ARMS), 'oracle arms need gold references (valid46 ref15 only)'
    out_dir = OUT / 'runs' / a.suite / f'run{a.run}'; out_dir.mkdir(parents=True, exist_ok=True)
    lock = threading.Lock()
    done = {}
    for n in names:
        f = out_dir / f'{n}.jsonl'
        done[n] = {json.loads(l)['id'] for l in open(f)} if f.exists() else set()

    def job(item):
        n, row = item
        AR.RUN.set(a.run)
        t = time.time()
        try:
            r = AR.ARMS[n](row)
            if r is None:
                return
            if any(s.get('admission') == 'TRANSPORT_FAILURE' for s in r['steps']):
                print('transport failure, will retry on next invocation:', n, row['id'][:40], flush=True)
                return
            rec = dict(id=row['id'], arm=n, run=a.run, decision=r['decision'],
                       steps=[slim_step(s) for s in r['steps']],
                       **{k: v for k, v in r.items() if k not in ('decision', 'steps')}, seconds=round(time.time() - t, 1))
        except Exception as e:
            rec = dict(id=row['id'], arm=n, run=a.run, decision=None, error=f'{type(e).__name__}:{e}'[:300],
                       tb=traceback.format_exc(limit=4)[-800:])
            if 'TRANSPORT' in str(e):
                return
        with lock:
            with open(out_dir / f'{n}.jsonl', 'a') as f:
                f.write(json.dumps(rec, ensure_ascii=False, default=str) + '\n')
            print(n, row['id'][:40], rec['decision'], rec.get('error', '')[:80], flush=True)

    todo = [(n, r) for n in names for r in rows if r['id'] not in done[n]]
    print('jobs', len(todo), flush=True)
    with ThreadPoolExecutor(a.workers) as ex:
        list(ex.map(job, todo))


if __name__ == '__main__':
    main()
