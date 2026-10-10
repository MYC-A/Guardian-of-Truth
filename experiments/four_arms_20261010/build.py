"""Build job lists for the four arms (no gold). Uses the stored prosecutor accusations.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.four_arms_20261010.build --pj outputs/prosecutor_judge_20261010/out.json --outdir outputs/four_arms_20261010
"""
import argparse
import json
import os

from experiments.escalation_probe_20261010.probe import parse_answer
from experiments.four_arms_20261010.arms import judge1_body, judge2_body, score_body, think_body
from experiments.prosecutor_judge_20261010.build import selected


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pj', required=True)
    ap.add_argument('--outdir', required=True)
    a = ap.parse_args()
    os.makedirs(a.outdir, exist_ok=True)
    sel = {x['key']: x for x in selected()}
    pj = json.load(open(a.pj))
    qwen, granite = [], []
    for p in range(3):
        for k, x in sel.items():
            if x['passes'] > p:
                qwen.append(dict(id=f'score|{p}|{k}', body=score_body(x['prompt'], x['turn'])))
                qwen.append(dict(id=f'think|{p}|{k}', body=think_body(x['prompt'], x['turn'])))
                granite.append(dict(id=f'score|{p}|{k}', body=score_body(x['prompt'], x['turn'])))
        for it in pj['passes'][p]['items']:
            if it['check'] != 'ok':
                continue
            x, acc = sel[it['key']], parse_answer(it['prosecutor']['content'])
            qwen.append(dict(id=f'judge2|{p}|{it["key"]}', body=judge2_body(x['prompt'], x['turn'], acc)))
            granite.append(dict(id=f'judge1|{p}|{it["key"]}', body=judge1_body(x['prompt'], x['turn'], acc)))
            granite.append(dict(id=f'judge2|{p}|{it["key"]}', body=judge2_body(x['prompt'], x['turn'], acc)))
    for name, jobs in (('qwen', qwen), ('granite', granite)):
        json.dump(jobs, open(os.path.join(a.outdir, f'jobs_{name}.json'), 'w'), ensure_ascii=False)
        print(name, len(jobs), {t: sum(j['id'].startswith(t + '|') for j in jobs) for t in ('score', 'think', 'judge1', 'judge2')})


if __name__ == '__main__':
    main()
