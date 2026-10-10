"""Round 3 (amendment 3): second judge without extra weights (Qwen, no thinking, short reasoning) and a small
second family (Gemma 3 4B FP8). Same gated rows, two independent replicates each. No gold.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.round3 --outdir outputs/think_gate_20261010
"""
import argparse
import json
import os

from experiments.four_arms_20261010.arms import SYS, THINK_TAIL, VERDICT_Q
from experiments.prosecutor_judge_20261010.build import selected
from experiments.prosecutor_judge_20261010.pj import context
from experiments.think_gate_20261010.build import gated
from experiments.think_gate_20261010.cascade import K
from experiments.think_gate_20261010.gemma import gemma_body


def qcot_body(prompt, turn):
    """Qwen without thinking mode: short visible reasoning + final VERDICT line (Gemma-style request);
    Qwen's recommended non-thinking sampling."""
    return dict(messages=[dict(role='system', content=SYS),
                          dict(role='user', content=context(prompt) + '\n\n' + VERDICT_Q.format(turn=turn) + THINK_TAIL)],
                n=K, max_tokens=4096, temperature=0.7, top_p=0.8, top_k=20,
                chat_template_kwargs=dict(enable_thinking=False))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    sel = {x['key']: x for x in selected()}
    g = gated()
    q = [dict(id=f'qcot{r}|{p}|{k}', body=qcot_body(sel[k]['prompt'], sel[k]['turn'])) for r in (1, 2) for p, k in g]
    s = [dict(id=f'g4b{r}|{p}|{k}', body=gemma_body(sel[k]['prompt'], sel[k]['turn'])) for r in (1, 2) for p, k in g]
    json.dump(q, open(os.path.join(a.outdir, 'jobs_qcot.json'), 'w'), ensure_ascii=False)
    json.dump(s, open(os.path.join(a.outdir, 'jobs_g4b.json'), 'w'), ensure_ascii=False)
    print(len(q), len(s))


if __name__ == '__main__':
    main()
