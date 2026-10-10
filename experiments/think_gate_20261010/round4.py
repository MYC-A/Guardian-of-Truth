"""Round 4 (amendment 4): Q-CoT with n=6, fire iff >=4/6 VIOLATION; two fresh replicates. No gold.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.round4 --out outputs/think_gate_20261010/jobs_q6.json
"""
import argparse
import json

from experiments.prosecutor_judge_20261010.build import selected
from experiments.think_gate_20261010.build import gated
from experiments.think_gate_20261010.round3 import qcot_body

N6, V6 = 6, 4


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    sel = {x['key']: x for x in selected()}
    jobs = []
    for r in (1, 2):
        for p, k in gated():
            b = qcot_body(sel[k]['prompt'], sel[k]['turn'])
            b['n'] = N6
            jobs.append(dict(id=f'q6r{r}|{p}|{k}', body=b))
    json.dump(jobs, open(a.out, 'w'), ensure_ascii=False)
    print(len(jobs))


if __name__ == '__main__':
    main()
