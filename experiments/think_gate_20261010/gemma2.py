"""Round 2 (docs/think_gate_20261010/PROTOCOL.md, amendment 2). No gold.
gconf: fresh repeat of the Qwen-gated Gemma jobs (confirmation); gscore: Gemma 1-token YES/NO score on every
row-pass; gall: Gemma reasoning verdict (n=3) on every row-pass (Gemma as the lead model, no Qwen gate).
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.gemma2 --out outputs/think_gate_20261010/jobs_gemma2.json
"""
import argparse
import json

from experiments.four_arms_20261010.arms import score_body
from experiments.prosecutor_judge_20261010.build import selected
from experiments.think_gate_20261010.build import gated
from experiments.think_gate_20261010.gemma import gemma_body


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    sel = {x['key']: x for x in selected()}
    jobs = [dict(id=f'gconf|{p}|{k}', body=gemma_body(sel[k]['prompt'], sel[k]['turn'])) for p, k in gated()]
    allp = [(p, k) for k, x in sel.items() for p in range(x['passes'])]
    for p, k in allp:
        b = score_body(sel[k]['prompt'], sel[k]['turn'])
        b.pop('chat_template_kwargs')
        jobs.append(dict(id=f'gscore|{p}|{k}', body=b))
    jobs += [dict(id=f'gall|{p}|{k}', body=gemma_body(sel[k]['prompt'], sel[k]['turn'])) for p, k in allp]
    json.dump(jobs, open(a.out, 'w'), ensure_ascii=False)
    print({t: sum(j['id'].startswith(t + '|') for j in jobs) for t in ('gconf', 'gscore', 'gall')})


if __name__ == '__main__':
    main()
