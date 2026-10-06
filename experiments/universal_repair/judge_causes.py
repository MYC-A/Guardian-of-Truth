"""Run the source-seeing cause judge (contract 5b) over every positive prediction of the given arms.
Dedup by (set, row id, accusation text); judge calls are a separate ledger (cache/judge). Variance: --attempt 1 on a subset."""
import argparse
import json
from collections import Counter

from guardian_truth.repair.cause import judge, gold_causes, CORRECT
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import decide
from .run import OUT, MODEL, inputs, paced
from .score import gold_for, arm_records
from guardian_truth.integrated import Transport


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arms', default='V4r,R_comb'); ap.add_argument('--mode', default='live')
    ap.add_argument('--sets', required=True); ap.add_argument('--attempt', type=int, default=0)
    ap.add_argument('--limit', type=int, default=0); ap.add_argument('--max-calls', type=int, default=600)
    a = ap.parse_args()
    live = Transport('mistral', MODEL, OUT / 'cache' / 'judge', max_calls=a.max_calls, retry_failed=2, sender=paced)
    client = ReadThrough('mistral', MODEL, [], live=live)
    outp = OUT / 'cause' / f'judgements_a{a.attempt}.jsonl'; outp.parent.mkdir(parents=True, exist_ok=True)
    done = set()
    if outp.exists():
        for l in outp.read_text(encoding='utf-8').splitlines():
            r = json.loads(l)
            if r['judgement'].get('category') != 'technical_unjudged':
                done.add((r['set'], r['id'], r['acc_text']))
    todo = []
    for sr in a.sets.split(','):
        s, rep = sr.split(':'); rep = int(rep)
        rows = {r['id']: r for r in inputs(s)}; g = gold_for(s)
        for arm in a.arms.split(','):
            recs = None
            for mode in (['offline', a.mode] if arm == 'V4r' else [a.mode]):
                try:
                    recs, _ = arm_records(s, rep, arm, mode); break
                except FileNotFoundError:
                    continue
            if recs is None:
                print('skip', sr, arm); continue
            for i, rec in recs.items():
                if i not in g: continue
                p, acc = decide(rec)
                if not p: continue
                key = (s, i, (acc or {}).get('text') or '')
                if key in done: continue
                if a.limit and len(todo) >= a.limit: break
                done.add(key)
                todo.append((s, rep, arm, i, rows[i], acc or {}, g[i], key[2]))
    import threading
    from concurrent.futures import ThreadPoolExecutor
    lock = threading.Lock()

    def one(t):
        s, rep, arm, i, row, acc, gi, text = t
        j = judge(client, MODEL, row, acc, gold_causes(gi), attempt=a.attempt)
        with lock, open(outp, 'a', encoding='utf-8', newline='\n') as f:
            f.write(json.dumps(dict(set=s, rep=rep, arm=arm, id=i, label=gi['label'], origin=acc.get('origin'),
                                    acc_text=text, judgement=j), ensure_ascii=False) + '\n')
    with ThreadPoolExecutor(3) as ex:
        list(ex.map(one, todo))
    print('judged', len(todo), live.counts)


if __name__ == '__main__':
    main()
