"""Second family (Gemma 3 27B FP8) on the same gated rows: same question, full context, explicit reasoning
(Gemma has no thinking mode), n=3, Gemma's recommended sampling. No gold.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.gemma --out outputs/think_gate_20261010/jobs_gemma.json
"""
import argparse
import json

from experiments.four_arms_20261010.arms import SYS, THINK_TAIL, VERDICT_Q
from experiments.prosecutor_judge_20261010.build import selected
from experiments.prosecutor_judge_20261010.pj import context
from experiments.think_gate_20261010.build import gated
from experiments.think_gate_20261010.cascade import K

GEMMA_EXTRA = ('--max-model-len 40960 --limit-mm-per-prompt {"image":0}')


def gemma_body(prompt, turn):
    return dict(messages=[dict(role='system', content=SYS),
                          dict(role='user', content=context(prompt) + '\n\n' + VERDICT_Q.format(turn=turn) + THINK_TAIL)],
                n=K, max_tokens=4096, temperature=1.0, top_p=0.95, top_k=64)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    sel = {x['key']: x for x in selected()}
    jobs = [dict(id=f'gemma|{p}|{k}', body=gemma_body(sel[k]['prompt'], sel[k]['turn'])) for p, k in gated()]
    json.dump(jobs, open(a.out, 'w'), ensure_ascii=False)
    print(len(jobs), 'jobs x n=3')


if __name__ == '__main__':
    main()
