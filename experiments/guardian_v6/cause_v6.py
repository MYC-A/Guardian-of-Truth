"""Cause quality of v6 positives with the frozen judge v2 (same prompt/invariants as universal_repair_v2).
MODEL-certificate accusations are identical to R_fix's -> reuse stored v2 judgements; MECHANICAL ones are judged new.
  python -m experiments.guardian_v6.cause_v6 run|report [--sets ...]"""
import argparse, json, threading
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from guardian_truth.integrated import Transport
from guardian_truth.repair.cause import judge_v2, gold_causes
from guardian_truth.repair.clients import ReadThrough
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.score import gold_for
from experiments.universal_repair.judge_v2 import load, classify

V6 = OUT.parent / 'guardian_v6'
V2 = OUT.parent / 'universal_repair_v2'
DEV = ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h']


def positives(sets):
    for s in sets:
        for p in sorted((V6 / 'runs' / s).glob('rep*.jsonl')):
            for r in map(json.loads, p.read_text(encoding='utf-8').splitlines()):
                if r['v6'] or r['rfix']:
                    yield s, p.stem, r


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('stage', choices=['run', 'report']); ap.add_argument('--sets', default=','.join(DEV))
    ap.add_argument('--gold', default=None)
    a = ap.parse_args(); sets = a.sets.split(',')
    J2 = load(V2 / 'cause' / 'judgements_v2_a0.jsonl')
    outp = V6 / 'cause_v6.jsonl'
    J6 = {}
    if outp.exists():
        for r in map(json.loads, outp.read_text(encoding='utf-8').splitlines()):
            J6[(r['set'], r['id'], r['acc_text'])] = r
    golds = {s: (json.load(open(a.gold)) if a.gold else gold_for(s)) for s in sets}
    if a.stage == 'run':
        todo, seen = [], set()
        for s, rep, r in positives(sets):
            acc = r['accusation'] or {}
            k = (s, r['id'], acc.get('text') or '')
            if r['v6'] and acc.get('certificate') == 'MECHANICAL' and k not in J6 and k not in seen:
                seen.add(k); todo.append((s, r, acc))
        missing_model = 0
        for s, rep, r in positives(sets):
            for acc in (r['rfix_acc'], r['accusation'] if (r['accusation'] or {}).get('certificate') == 'MODEL' else None):
                k = (s, r['id'], (acc or {}).get('text') or '')
                if acc and k not in J2 and k not in J6 and k not in seen:
                    seen.add(k); todo.append((s, r, acc)); missing_model += 1
        print('todo', len(todo), Counter(t[0] for t in todo), 'of which MODEL', len(missing_model), flush=True)
        live = Transport('mistral', MODEL, V2 / 'cache' / 'judge', max_calls=600, retry_failed=2, sender=paced)
        client = ReadThrough('mistral', MODEL, [], live=live)
        rows = {s: {x['id']: x for x in inputs(s)} for s in sets}
        lock = threading.Lock()

        def one(t):
            s, r, acc = t
            gi = golds[s][r['id']]
            j = judge_v2(client, MODEL, rows[s][r['id']], acc, gold_causes(gi), attempt=0)
            with lock, open(outp, 'a', encoding='utf-8') as f:
                f.write(json.dumps(dict(set=s, id=r['id'], label=gi['label'], acc_text=acc.get('text') or '', certificate=acc.get('certificate'),
                                        judgement=j), ensure_ascii=False) + '\n')
        with ThreadPoolExecutor(3) as ex:
            list(ex.map(one, todo))
        print(live.counts); return
    # report: per arm (R_fix vs v6) category counts over TPs (all reps), by certificate
    for arm in ('rfix', 'v6'):
        c, cc = Counter(), defaultdict(Counter)
        for s, rep, r in positives(sets):
            if not r[arm] or r['label'] != 1:
                continue
            acc = (r['rfix_acc'] if arm == 'rfix' else r['accusation']) or {}
            k = (s, r['id'], acc.get('text') or '')
            j = (J6.get(k) or J2.get(k) or {}).get('judgement'); cert = acc.get('certificate', 'MODEL')
            cat = classify(j, 1) if j else 'missing'
            c[cat] += 1; cc[cert][cat] += 1
        print(arm, sum(c.values()), dict(c)); [print('   ', k, dict(v)) for k, v in cc.items()]


if __name__ == '__main__':
    main()
