"""Evaluate round 2 (amendment 2). Gold read only here.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.evaluate2 --out outputs/think_gate_20261010/out_gemma2.json
"""
import argparse
import json

from experiments.four_arms_20261010.arms import p_yes
from experiments.four_arms_20261010.evaluate import Data
from experiments.think_gate_20261010.cascade import VOTES, votes

GRID = [0.9, 0.8, 0.7, 0.6, 0.5, 0.4, 0.3, 0.2, 0.1, 0.05, 0.02, 0.01, 0.005, 0.002, 0.001, 0.0]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pj', default='outputs/prosecutor_judge_20261010/out.json')
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    d = Data(a.pj)
    o = json.load(open(a.out))
    print('kind_seconds', o.get('kind_seconds'), 'startup', o.get('startup_s'), 'failure', o.get('failure'),
          'errors', sum('error' in r for r in o['results'].values()))
    R = {}
    for j, r in o['results'].items():
        kind, p, k = j.split('|')
        R.setdefault(kind, {})[(int(p), k)] = r
    nv = {kind: {pk: votes(r.get('samples')) for pk, r in R[kind].items()} for kind in ('gconf', 'gall')}
    ps = {pk: p_yes(r.get('top')) for pk, r in R['gscore'].items()}
    print('gscore parsed', sum(v is not None for v in ps.values()), '/', len(ps))
    # C: confirmation of the round-1 diagnostic (prereg primary of round 2)
    d.report('C gconf >=2/3 [prereg]', lambda p, k: nv['gconf'].get((p, k), 0) >= VOTES)
    # L1: Gemma lead, no gate
    d.report('L1 gall >=2/3 no gate', lambda p, k: nv['gall'].get((p, k), 0) >= VOTES)
    # L2: Gemma's own score gate; t chosen on decision pools only: max pool TP s.t. pool FP <= 3, ties -> highest t
    best = None
    for t in GRID:
        f = lambda p, k, t=t: (ps.get((p, k)) or 0) >= t and nv['gall'].get((p, k), 0) >= VOTES
        tp = fp = 0
        for k, x in d.sel.items():
            g = d.gold[x['pool']].get(x['id']) if x['pool'] != 'valid46' else None
            if g is None or not f(0, k):
                continue
            tp, fp = tp + (g == 1), fp + (g == 0)
        if fp <= 3 and (best is None or tp > best[1]):
            best = (t, tp)
    print('L2 t* (pools only) =', best)
    if best:
        d.report(f'L2 gscore>={best[0]} & gall', lambda p, k: (ps.get((p, k)) or 0) >= best[0] and nv['gall'].get((p, k), 0) >= VOTES)
    # L3: Gemma standalone instead of the base (valid46 only; diagnostic)
    f1s = []
    for p in range(3):
        pred = {i: nv['gall'].get((p, d.vkey[i]), 0) >= VOTES for i in d.G}
        tp = sum(d.G[i] and pred[i] for i in d.G); fp = sum((not d.G[i]) and pred[i] for i in d.G)
        fn = sum(d.G[i] and not pred[i] for i in d.G)
        f1s.append(round(2 * tp / max(1, 2 * tp + fp + fn), 4))
        print(f'L3 standalone pass {p}: TP {tp} FP {fp} FN {fn} F1 {f1s[-1]}')
    print('L3 standalone mean F1', round(sum(f1s) / 3, 4), '(base .800)')


if __name__ == '__main__':
    main()
