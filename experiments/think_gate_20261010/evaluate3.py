"""Evaluate round 3. Gold read only here. Accept an arm only if BOTH replicates pass.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.think_gate_20261010.evaluate3 outputs/think_gate_20261010/out_qcot.json [out_g4b.json]
"""
import json
import sys

from experiments.four_arms_20261010.evaluate import Data
from experiments.think_gate_20261010.cascade import VOTES, votes


def main(paths):
    d = Data('outputs/prosecutor_judge_20261010/out.json')
    for path in paths:
        o = json.load(open(path))
        print(path, 'kind_seconds', o.get('kind_seconds'), 'startup', o.get('startup_s'), 'failure', o.get('failure'),
              'errors', sum('error' in r for r in o['results'].values()))
        kinds = sorted({j.split('|')[0] for j in o['results']})
        oks = []
        for kind in kinds:
            res = {(int(j.split('|')[1]), j.split('|')[2]): r for j, r in o['results'].items() if j.startswith(kind + '|')}
            fin = {}
            for r in res.values():
                for s in r.get('samples', []):
                    fin[s['finish']] = fin.get(s['finish'], 0) + 1
            toks = [r['completion_tokens'] / len(r['samples']) for r in res.values() if r.get('samples')]
            print(f'  {kind}: finish {fin}, mean tokens/sample {sum(toks) / max(1, len(toks)):.0f}')
            nv = {pk: votes(r.get('samples')) for pk, r in res.items()}
            oks.append(d.report(f'{kind} >=2/3 [prereg]', lambda p, k: nv.get((p, k), 0) >= VOTES))
        print('  ARM', 'ACCEPT (both replicates)' if oks and all(oks) else 'reject')


if __name__ == '__main__':
    main(sys.argv[1:])
