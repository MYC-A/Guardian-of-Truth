"""Evaluate the THINK cascade (docs/think_gate_20261010/PROTOCOL.md). Gold is read only here.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.evaluate --out outputs/think_gate_20261010/out.json
"""
import argparse
import collections
import json

from experiments.four_arms_20261010.evaluate import Data
from experiments.think_gate_20261010.cascade import VOTES, votes


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--pj', default='outputs/prosecutor_judge_20261010/out.json')
    ap.add_argument('--out', required=True)
    ap.add_argument('--gemma')
    a = ap.parse_args()
    d = Data(a.pj)
    o = json.load(open(a.out))
    print('kind_seconds', o.get('kind_seconds'), 'startup', o.get('startup_s'), 'failure', o.get('failure'),
          'errors', sum('error' in r for r in o['results'].values()))
    ap_g = json.load(open(a.gemma))['results'] if a.gemma else {}
    o['results'].update(ap_g)
    NV = {}
    for arm in ('thinkA', 'thinkB', 'gemma'):
        res = {(int(j.split('|')[1]), j.split('|')[2]): r for j, r in o['results'].items() if j.startswith(arm + '|')}
        if not res:
            continue
        fin = collections.Counter(s['finish'] for r in res.values() for s in r.get('samples', []))
        toks = [r['completion_tokens'] / max(1, len(r['samples'])) for r in res.values() if 'samples' in r]
        print(f'{arm}: requests {len(res)}, sample finish {dict(fin)}, mean tokens/sample {sum(toks) / max(1, len(toks)):.0f}')
        nv = {pk: votes(r.get('samples')) for pk, r in res.items()}
        d.report(f'{arm} >={VOTES}of3 [prereg]', lambda p, k: nv.get((p, k), 0) >= VOTES)
        d.report(f'{arm} >=1of3 [diag]', lambda p, k: nv.get((p, k), 0) >= 1)
        d.report(f'{arm} 3of3 [diag]', lambda p, k: nv.get((p, k), 0) >= 3)
        NV[arm] = nv
    if 'thinkA' in NV and 'gemma' in NV:
        qa, ge = NV['thinkA'], NV['gemma']
        d.report('Qwen-A AND Gemma [prereg]', lambda p, k: qa.get((p, k), 0) >= VOTES and ge.get((p, k), 0) >= VOTES)
        d.report('pooled >=4of6 [diag]', lambda p, k: qa.get((p, k), 0) + ge.get((p, k), 0) >= 4)
        d.report('Qwen-A OR Gemma [diag]', lambda p, k: qa.get((p, k), 0) >= VOTES or ge.get((p, k), 0) >= VOTES)


if __name__ == '__main__':
    main()
