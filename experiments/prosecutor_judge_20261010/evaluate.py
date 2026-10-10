"""Evaluate out.json per docs/prosecutor_judge_20261010/PROTOCOL.md. Gold is read only here.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.prosecutor_judge_20261010.evaluate --out out.json
"""
import argparse
import collections
import json

from experiments.contract_lint_20261010.lint import lint
from experiments.escalation_probe_20261010.probe import parse_answer
from experiments.guardian_local_a100.run_local import rows
from experiments.guardian_local_a100.score_local import gold_for
from experiments.prosecutor_judge_20261010.build import selected
from experiments.prosecutor_judge_20261010.pj import decide

TB = ['outputs/token_budget_20261010/valid46_tb_traces.jsonl',
      'outputs/determinism_voting_20261010/valid46_tb2_traces.jsonl',
      'outputs/determinism_voting_20261010/valid46_tb3_traces.jsonl']


def f1(gold, pred):
    tp = sum(1 for k in gold if gold[k] and pred[k]); fp = sum(1 for k in gold if not gold[k] and pred[k])
    fn = sum(1 for k in gold if gold[k] and not pred[k])
    return round(2 * tp / (2 * tp + fp + fn), 4), fp


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    ap.add_argument('--show', action='store_true')
    a = ap.parse_args()
    out = json.load(open(a.out))
    sel = {x['key']: x for x in selected()}
    golds = {}
    for x in sel.values():
        golds.setdefault(x['pool'], {i: g['label'] for i, g in gold_for(x['pool']).items() if g.get('label') in (0, 1)})
    print('startup', out.get('startup_s'), 'failure', out.get('failure'))
    fires = []                                   # per pass: {key: {'R1','R2','why','check'}}
    for p in out['passes']:
        f = {}
        for it in p['items']:
            x = sel[it['key']]
            j = it.get('judge')
            d = decide(x['prompt'], x['turn'], parse_answer(j.get('content')) if j and 'error' not in j else None) \
                if it['check'] == 'ok' else dict(R1=False, R2=False, why='no_accusation')
            f[it['key']] = dict(d, check=it['check'])
        fires.append(f)
        errs = sum('error' in it['prosecutor'] or (it.get('judge') or {}).get('error') is not None for it in p['items'])
        print(f"pass: rows {len(p['items'])} prosecutor {p['prosecutor_s']}s judge {p['judge_s']}s errors {errs}",
              'checks', dict(collections.Counter(v['check'] for v in f.values())),
              'judge', dict(collections.Counter(v['why'] for v in f.values() if v['check'] == 'ok')))
    # decision pools (pass 0 only; base B2 Q8 rep1 == 0)
    for rule in ('R1', 'R2'):
        c = collections.Counter()
        for k, v in fires[0].items():
            x = sel[k]
            if x['pool'] == 'valid46' or x['id'] not in golds[x['pool']]:
                continue
            g = golds[x['pool']][x['id']]
            c['neg' if not g else 'pos'] += 1
            if v[rule]:
                c['newTP' if g else 'newFP'] += 1
        prec = c['newTP'] / max(1, c['newTP'] + c['newFP'])
        print(f"decision pools {rule}: {dict(c)} precision {prec:.2f}")
    G = {i: g['label'] for i, g in gold_for('valid46').items()}
    R = {r['id']: r for r in rows('valid46')}
    L = {k for k in G if any(f['check'] == 'UNKNOWN_TOOL' for f in lint(R[k]['prompt'], R[k]['response'] or ''))}
    vk = {x['id']: k for k, x in sel.items() if x['pool'] == 'valid46'}
    tb = [{json.loads(l)['id']: int(json.loads(l)['binary']) for l in open(p)} for p in TB]
    bases = [{k: int(t[k] or k in L) for k in G} for t in tb]
    print('valid46 base (tb+lint)', [f1(G, b) for b in bases])
    for rule in ('R1', 'R2'):
        res = [[f1(G, {k: int(b[k] or fires[p][vk[k]][rule]) for k in G}) for b in bases] for p in range(len(fires))]
        mean = sum(r[0] for row in res for r in row) / 9
        newfp = [sum(1 for k in G if not G[k] and fires[p][vk[k]][rule]) for p in range(len(fires))]
        print(f'valid46 {rule}: per pass x base {res} mean {mean:.4f} fires-on-negatives per pass {newfp}')
        fired = sorted({x for p in range(len(fires)) for x in G if fires[p][vk[x]][rule]})
        print('   fired rows:', [(x[:30], G[x], sum(fires[p][vk[x]][rule] for p in range(len(fires)))) for x in fired])
    if a.show:
        for it in out['passes'][0]['items']:
            x = sel[it['key']]
            if it['check'] == 'ok' and x['pool'] != 'valid46' and golds[x['pool']].get(x['id']) == 0 and fires[0][it['key']]['R1']:
                acc = parse_answer(it['prosecutor']['content'])
                print('FP', x['pool'], x['id'][:30], '|', str(acc.get('violation'))[:200])


if __name__ == '__main__':
    main()
