"""Evaluate amendments 4+5. Gold read only here. ACCEPT an arm only if both replicates pass.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.evaluate5 --q6 out_q6.json --mq out_mq.json
"""
import argparse
import json

from experiments.four_arms_20261010.arms import p_yes
from experiments.four_arms_20261010.evaluate import Data
from experiments.think_gate_20261010.cascade import votes
from experiments.think_gate_20261010.round4 import V6

SCORE_T = 0.05      # Qwen score threshold from the four-arms post-hoc analysis (fixed, not re-tuned)


def load(path):
    o = json.load(open(path))
    print(path, 'kind_seconds', o.get('kind_seconds'), 'failure', o.get('failure'),
          'errors', sum('error' in r for r in o['results'].values()))
    out = {}
    for j, r in o['results'].items():
        kind, p, k = j.split('|')
        out.setdefault(kind, {})[(int(p), k)] = votes(r.get('samples'))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--q6')
    ap.add_argument('--mq')
    a = ap.parse_args()
    d = Data('outputs/prosecutor_judge_20261010/out.json')
    q = json.load(open('outputs/four_arms_20261010/out_qwen.json'))['results']
    ps = {(int(j.split('|')[1]), j.split('|')[2]): p_yes(r.get('top')) or 0 for j, r in q.items() if j.startswith('score|')}
    arms = {}
    if a.q6:
        v = load(a.q6)
        for r in (1, 2):
            nv = v[f'q6r{r}']
            arms.setdefault('A4 Q-CoT n6 >=4/6', []).append(
                d.report(f'A4 q6 rep{r}', lambda p, k, nv=nv: nv.get((p, k), 0) >= V6))
            arms.setdefault('A5a score>=.05 OR q6', []).append(
                d.report(f'A5a score|q6 rep{r}', lambda p, k, nv=nv: ps.get((p, k), 0) >= SCORE_T or nv.get((p, k), 0) >= V6))
    if a.mq:
        v = load(a.mq)
        for r in (1, 2):
            tot = {}
            for f in ('F1', 'F2', 'F3'):
                for pk, n in v[f'mq{f}r{r}'].items():
                    tot[pk] = tot.get(pk, 0) + n
            arms.setdefault('A5b 3 framings >=2/3', []).append(
                d.report(f'A5b mq rep{r}', lambda p, k, tot=tot: tot.get((p, k), 0) >= 2))
            for f in ('F1', 'F2', 'F3'):
                nv = v[f'mq{f}r{r}']
                d.report(f'  diag {f} alone rep{r}', lambda p, k, nv=nv: nv.get((p, k), 0) >= 1)
    for name, oks in arms.items():
        print(f'{name:28} ->', 'ACCEPT (both replicates)' if all(oks) else 'reject')


if __name__ == '__main__':
    main()
