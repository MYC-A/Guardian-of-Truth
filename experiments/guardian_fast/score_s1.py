"""python -m experiments.guardian_fast.score_s1 SET[,SET] -> S1/S1F variants alone and OR-ed with N0 (audit only on N0=NO_ERROR rows)."""
import json, sys, statistics
from experiments.guardian_local_a100.score_local import gold_for
from experiments.guardian_fast.run_fast import OUT


def load(p):
    try:
        return {json.loads(l)['id']: json.loads(l) for l in open(p)}
    except FileNotFoundError:
        return {}


def conf(pairs):
    tp = sum(y and p for y, p in pairs); fp = sum((not y) and p for y, p in pairs)
    fn = sum(y and not p for y, p in pairs); tn = sum((not y) and (not p) for y, p in pairs)
    P = tp / (tp + fp) if tp + fp else 0; R = tp / (tp + fn) if tp + fn else 0
    return f'TP{tp} FP{fp} FN{fn} TN{tn} F1={2*P*R/(P+R) if P+R else 0:.3f}'


if __name__ == '__main__':
    for s in sys.argv[1].split(','):
        g = gold_for(s); d = OUT / 'ministral-14b-2512/runs' / s
        n0 = load(d / 'N0.jsonl')
        for name in ('S1', 'S1F'):
            rs = load(d / f'{name}.jsonl')
            if not rs: continue
            ok = [r for r in rs.values() if 'verdict' in r and g.get(r['id'], {}).get('label') is not None]
            err = len(rs) - len(ok)
            ct = statistics.mean(r['usage']['completion_tokens'] for r in ok); sec = statistics.mean(r['wall_s'] for r in ok)
            for key in ('binary_raw', 'binary_grounded', 'binary_any'):
                print(s, name, key, len(ok), conf([(int(g[r['id']]['label']), r[key]) for r in ok]), f'ctok={ct:.0f} s={sec:.1f} err={err}')
            if n0:
                pr = [(int(g[r['id']]['label']), int(bool(n0[r['id']]['binary']) or bool(r['binary_grounded']))) for r in ok if r['id'] in n0]
                print(s, name, 'N0 OR grounded', len(pr), conf(pr))
