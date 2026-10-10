"""POST-HOC (not preregistered) diagnostics for four arms. Gold read only here.
- extended score-threshold grid (below 0.5), t* still chosen on decision pools only (lowest t with pool FP<=3);
- Granite judge-1 verdict distribution (is cross-judge informative?);
- THINK unparsed reasons.
"""
import collections
import json
import sys

from experiments.escalation_probe_20261010.probe import parse_answer
from experiments.four_arms_20261010.arms import p_yes
from experiments.four_arms_20261010.evaluate import Data, load
from experiments.prosecutor_judge_20261010.pj import _norm

GRID = [0.5, 0.4, 0.3, 0.2, 0.15, 0.1, 0.08, 0.06, 0.05, 0.04, 0.03, 0.02, 0.01, 0.005]


def ext(d, res, label):
    ps = {(p, k): p_yes(r.get('top')) for (kind, p, k), r in res.items() if kind == 'score' and 'error' not in r}
    best = None
    for t in GRID:
        fp = sum(1 for k, x in d.sel.items() if x['pool'] != 'valid46' and d.gold[x['pool']].get(x['id']) == 0
                 and (ps.get((0, k)) or 0) >= t)
        if fp <= 3:
            best = t
    print(f'{label}: post-hoc t* (lowest grid t with pool FP<=3) = {best}')
    for t in GRID:
        d.report(f'{label}@{t} [posthoc]', lambda p, k, t=t: (ps.get((p, k)) or 0) >= t)
    return ps


def main(pj, qwen, granite):
    d = Data(pj)
    q, g = load(qwen), load(granite)
    ext(d, q, 'qwen')
    ext(d, g, 'granite')
    g1 = collections.Counter(_norm((parse_answer(r.get('content')) or {}).get('verdict') if isinstance(parse_answer(r.get('content')), dict) else None).upper()
                             for (kind, p, k), r in g.items() if kind == 'judge1')
    print('granite judge1 verdicts', dict(g1))
    th = collections.Counter((r.get('finish'), '</think>' in (r.get('content') or ''), 'VERDICT' in (r.get('content') or '').split('</think>')[-1].upper())
                             for (kind, p, k), r in q.items() if kind == 'think')
    print('think (finish, closed_think, has_VERDICT):', dict(th))


if __name__ == '__main__':
    main(*sys.argv[1:4])
