"""Build THINK jobs for gated rows (no gold). Gate uses the stored Qwen score p of the four-arms run.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.build --out outputs/think_gate_20261010/jobs.json
"""
import argparse
import json
import os

from experiments.four_arms_20261010.arms import p_yes
from experiments.four_arms_20261010.evaluate import TB
from experiments.contract_lint_20261010.lint import lint
from experiments.guardian_local_a100.run_local import rows
from experiments.prosecutor_judge_20261010.build import selected
from experiments.think_gate_20261010.cascade import gate, think_body

QWEN_OUT = 'outputs/four_arms_20261010/out_qwen.json'


def gated():
    """[(pass, key)] where the cascade would run THINK; valid46 rows already positive in all 3 bases are skipped
    (their prediction cannot change). Bases are model predictions, not gold."""
    res = json.load(open(QWEN_OUT))['results']
    ps = {(int(j.split('|')[1]), j.split('|')[2]): p_yes(r.get('top')) for j, r in res.items() if j.startswith('score|')}
    R = {r['id']: r for r in rows('valid46')}
    L = {i for i, r in R.items() if any(f['check'] == 'UNKNOWN_TOOL' for f in lint(r['prompt'], r['response'] or ''))}
    tb = [{json.loads(l)['id']: int(json.loads(l)['binary']) for l in open(p)} for p in TB]
    allpos = {i for i in R if all(t[i] or i in L for t in tb)}
    out = []
    for x in selected():
        for p in range(x['passes']):
            if x['pool'] == 'valid46' and x['id'] in allpos:
                continue
            if gate(ps.get((p, x['key']))):
                out.append((p, x['key']))
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    os.makedirs(os.path.dirname(a.out), exist_ok=True)
    sel = {x['key']: x for x in selected()}
    g = gated()
    jobs = [dict(id=f'{arm}|{p}|{k}', body=think_body(sel[k]['prompt'], sel[k]['turn'], narrow=(arm == 'thinkB')))
            for arm in ('thinkA', 'thinkB') for p, k in g]
    json.dump(jobs, open(a.out, 'w'), ensure_ascii=False)
    pools = sum(1 for p, k in g if sel[k]['pool'] != 'valid46')
    print(len(g), 'gated (pass,key):', pools, 'pool rows,', len(g) - pools, 'valid46 row-passes;', len(jobs), 'jobs x n=3')


if __name__ == '__main__':
    main()
