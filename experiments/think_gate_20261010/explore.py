"""EXPLORATORY (post-hoc) analysis: gate THINK by Qwen score p and by agreement across 3 think samples."""
from experiments.four_arms_20261010.arms import p_yes, think_verdict
from experiments.four_arms_20261010.evaluate import Data, load
d = Data('outputs/prosecutor_judge_20261010/out.json')
q = load('outputs/four_arms_20261010/out_qwen.json')
th = {(p, k): think_verdict(r.get('content') or '', r.get('finish')) for (kind, p, k), r in q.items() if kind == 'think'}
ps = {(p, k): p_yes(r.get('top')) or 0 for (kind, p, k), r in q.items() if kind == 'score'}
V = lambda p, k: th.get((p, k)) == 'VIOLATION'
nv = lambda k: sum(V(p, k) for p in range(3))
d.report('think single', V)
d.report('think 2of3', lambda p, k: nv(k) >= 2)
d.report('think 3of3', lambda p, k: nv(k) == 3)
for t in [0.005, 0.01, 0.02, 0.03]:
    d.report(f'think & p>={t}', lambda p, k, t=t: V(p, k) and ps[(p, k)] >= t)
    d.report(f'think2of3 & p>={t}', lambda p, k, t=t: nv(k) >= 2 and ps[(p, k)] >= t)
n = {}
for k, x in d.sel.items():
    if x['pool'] == 'valid46' or x['id'] not in d.gold[x['pool']]: continue
    g = d.gold[x['pool']][x['id']]
    print('pool', 'POS' if g else 'neg', nv(k), round(ps[(0, k)], 3), x['id'][:45])
for i in d.G:
    k = d.vkey[i]
    print('valid', 'POS' if d.G[i] else 'neg', 'base' + ''.join(str(b[i]) for b in d.bases), nv(k), round(ps[(0, k)], 3), i[:45])
