"""Evaluate probe_out.json per docs/escalation_probe_20261010/PROTOCOL.md. Gold is read only here.

    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.escalation_probe_20261010.evaluate --probe probe_out.json
"""
import argparse
import collections
import json

from experiments.contract_lint_20261010.lint import lint
from experiments.escalation_probe_20261010.build import triggered
from experiments.escalation_probe_20261010.probe import parse_answer, verify
from experiments.guardian_complementarity.combine import QW, runs
from experiments.guardian_local_a100.run_local import rows
from experiments.guardian_local_a100.score_local import gold_for

TB = ['outputs/token_budget_20261010/valid46_tb_traces.jsonl',
      'outputs/determinism_voting_20261010/valid46_tb2_traces.jsonl',
      'outputs/determinism_voting_20261010/valid46_tb3_traces.jsonl']


def f1(gold, pred):
    tp = sum(1 for k in gold if gold[k] and pred[k]); fp = sum(1 for k in gold if not gold[k] and pred[k])
    fn = sum(1 for k in gold if gold[k] and not pred[k])
    return round(2 * tp / (2 * tp + fp + fn), 4)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--probe', required=True)
    a = ap.parse_args()
    out = json.load(open(a.probe))
    trig = {x['key']: x for x in triggered()}
    golds = {}
    for x in trig.values():
        golds.setdefault(x['pool'], {i: g['label'] for i, g in gold_for(x['pool']).items()})
    b2q8 = {}
    for x in trig.values():
        if x['pool'] != 'valid46':
            b2q8.setdefault(x['pool'], runs(QW / x['pool'] / 'B2_rep1.jsonl', 'B2') or {})
    fires = []          # per pass: {key: verified}
    for p in out['passes']:
        f = {}
        for key, res in zip(out['keys'], p['results']):
            ok, why = (False, 'error') if 'error' in res else verify(trig[key]['prompt'], parse_answer(res.get('content')))
            f[key] = (ok, why)
        fires.append(f)
    print('pass seconds', [p['seconds'] for p in out['passes']], 'startup', out.get('startup_s'), out.get('failure'))
    print('reasons per pass', [dict(collections.Counter(w for _, w in f.values())) for f in fires])
    maj = {k: sum(f[k][0] for f in fires) * 2 > len(fires) for k in out['keys']}
    tb = [{json.loads(l)['id']: int(json.loads(l)['binary']) for l in open(p)} for p in TB]
    print('\nrow                                         gold  B2  fires/3')
    tot = collections.Counter()
    for k in out['keys']:
        x = trig[k]; g = golds[x['pool']][x['id']]
        b = ([t[x['id']] for t in tb] if x['pool'] == 'valid46' else [(b2q8[x['pool']].get(x['id']) or {}).get('b')])
        n = sum(f[k][0] for f in fires)
        print(f"{x['pool']:9} {x['id'][:34]:34} {g}  {b}  {n}  {[f[k][1] for f in fires]}")
        for i, f in enumerate(fires + [{k: (maj[k], '')}]):
            tag = f'p{i}' if i < len(fires) else 'maj'
            if f[k][0]:
                tot[tag + ('_trueFire' if g else '_FALSEFire')] += 1
    print('\nfires', dict(tot))
    G = {i: g['label'] for i, g in gold_for('valid46').items()}
    R = {r['id']: r for r in rows('valid46')}
    L = {k for k in G if any(f['check'] == 'UNKNOWN_TOOL' for f in lint(R[k]['prompt'], R[k]['response'] or ''))}
    vkeys = {trig[k]['id']: k for k in out['keys'] if trig[k]['pool'] == 'valid46'}
    for name, fs in [(f'p{i}', {k: v[0] for k, v in f.items()}) for i, f in enumerate(fires)] + [('maj', maj)]:
        res = []
        for t in tb:
            base = {k: int(t[k] or k in L) for k in G}
            res.append((f1(G, base), f1(G, {k: int(base[k] or (k in vkeys and fs[vkeys[k]])) for k in G})))
        print('valid46 tb+lint -> +probe', name, res)


if __name__ == '__main__':
    main()
