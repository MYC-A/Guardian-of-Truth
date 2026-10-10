"""Offline evaluation of Near-Miss per docs/near_miss_20261010/PROTOCOL.md (stored B2 Q8 rep1 binaries).

    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.near_miss_20261010.evaluate \
        --samples raw_samples.jsonl --out result.json
"""
import argparse
import hashlib
import json
from collections import defaultdict

from experiments.contract_lint_20261010.evaluate import decide
from experiments.contract_lint_20261010.lint import parse_catalog
from experiments.near_miss_20261010.detect import near_miss
from experiments.near_miss_20261010.policy import key, split, validate, vote

DECISION = ['ext_tau2', 'hold_tau2h', 'hold_holdout2', 'lb_long', 'lb2_long', 'lb3_long', 'contrast', 'dev', 'devT', 'frozen']
REPORT_ONLY = ['valid46']


def build_maps(samples_path, policies):
    raw = defaultdict(list)
    for line in open(samples_path, encoding='utf-8'):
        s = json.loads(line)
        raw[(s['key'], s['replicate'])].append(s)
    maps, diag = {}, {}
    for k, (policy, catalog_prompt) in policies.items():
        cat = parse_catalog(catalog_prompt)
        for rep in ('A', 'B'):
            vs = [validate(s['text'], policy, cat) if s['finish'] == 'stop' else None for s in raw[(k, rep)]]
            maps[(k, rep)] = vote(vs)
            diag[(k, rep)] = dict(invalid=sum(v is None for v in vs),
                                  dropped=[v['dropped'] for v in vs if v], raw_reqs=[len(v['requires']) for v in vs if v])
    return maps, diag


def req_keys(m):
    return {(r['tool'], r['entity_arg']) for r in m['requires']}


def jaccard(a, b):
    return round(len(a & b) / len(a | b), 4) if a | b else 1.0


def tally(items, arm):
    t = dict(rows=len(items), fires_pos=0, fires_neg=0, new_tp=0, new_fp=0, b2_gaps=0)
    for x in items:
        fired = bool(x[arm])
        if fired:
            t['fires_pos' if x['gold'] else 'fires_neg'] += 1
        if x['b2'] is None:
            t['b2_gaps'] += 1
        elif fired and x['b2'] == 0:
            t['new_tp' if x['gold'] else 'new_fp'] += 1
    n = t['fires_pos'] + t['fires_neg']
    t['fire_precision'] = round(t['fires_pos'] / n, 4) if n else None
    return t


def f1(items, arm=None):
    c = dict(TP=0, FP=0, FN=0, TN=0)
    for x in items:
        if x['b2'] is not None:
            p = int(x['b2'] or (arm is not None and bool(x[arm])))
            c[('TN', 'FP', 'FN', 'TP')[2 * x['gold'] + p]] += 1
    c['F1'] = round(2 * c['TP'] / max(1, 2 * c['TP'] + c['FP'] + c['FN']), 4)
    return c


def main():
    from experiments.guardian_complementarity.combine import QW, runs
    from experiments.guardian_local_a100.run_local import rows
    from experiments.guardian_local_a100.score_local import gold_for
    ap = argparse.ArgumentParser()
    ap.add_argument('--samples', required=True)
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    data, policies = {}, {}
    for pool in DECISION + REPORT_ONLY:
        data[pool] = rows(pool)
        for r in data[pool]:
            s = split(r['prompt'])
            if s:
                policies.setdefault(key(*s), (s[0], r['prompt']))
    maps, diag = build_maps(a.samples, policies)
    stability = {k[:12]: dict(jaccard_requires=jaccard(req_keys(maps[(k, 'A')]), req_keys(maps[(k, 'B')])),
                              mutating_equal=maps[(k, 'A')]['mutating'] == maps[(k, 'B')]['mutating'],
                              n_req_A=len(maps[(k, 'A')]['requires']), n_req_B=len(maps[(k, 'B')]['requires']))
                 for k in policies}
    seen, groups = set(), dict(decision=[], valid46=[])
    for pool in DECISION + REPORT_ONLY:
        gold = {i: g['label'] for i, g in gold_for(pool).items() if g.get('label') in (0, 1)}
        b2 = runs(QW / pool / 'B2_rep1.jsonl', 'B2') or {}
        for r in data[pool]:
            h = hashlib.sha256((r['prompt'] + '\0' + (r['response'] or '')).encode()).hexdigest()
            if r['id'] not in gold or h in seen:
                continue
            seen.add(h)
            s = split(r['prompt'])
            k = key(*s) if s else None
            x = dict(pool=pool, id=r['id'], gold=gold[r['id']], b2=(b2.get(r['id']) or {}).get('b'))
            for rep in ('A', 'B'):
                x[rep] = near_miss(r['prompt'], r['response'] or '', maps.get((k, rep))) if k else []
            groups['decision' if pool in DECISION else 'valid46'].append(x)
    out = dict(protocol='docs/near_miss_20261010/PROTOCOL.md', samples=a.samples,
               policies=len(policies), stability=stability,
               stability_mean_jaccard=round(sum(v['jaccard_requires'] for v in stability.values()) / len(stability), 4),
               diag={f'{k[:12]}:{rep}': v for (k, rep), v in diag.items()},
               maps={f'{k[:12]}:{rep}': v for (k, rep), v in maps.items()})
    for g, items in groups.items():
        out[g] = dict(B2=f1(items))
        for rep in ('A', 'B'):
            t = tally(items, rep)
            per_pool = {p: tally([x for x in items if x['pool'] == p], rep) for p in sorted({x['pool'] for x in items})}
            out[g][rep] = dict(tally=t, arm=f1(items, rep), decision=decide(t), per_pool=per_pool)
        out[g]['fire_agreement_A_B'] = sum(bool(x['A']) == bool(x['B']) for x in items) / max(1, len(items))
        out[g]['fired_rows'] = [dict(pool=x['pool'], id=x['id'], gold=x['gold'], b2=x['b2'], A=x['A'], B=x['B'])
                                for x in items if x['A'] or x['B']]
    dA, dB = out['decision']['A']['decision'], out['decision']['B']['decision']
    out['final_decision'] = dA if dA == dB else f'UNSTABLE(A={dA},B={dB})->NOT_ADOPTED'
    with open(a.out, 'x', encoding='utf-8') as f:
        json.dump(out, f, ensure_ascii=False, indent=1)
    print(json.dumps(dict(policies=len(policies), stability_mean_jaccard=out['stability_mean_jaccard'],
                          decision={r: out['decision'][r]['tally'] for r in 'AB'},
                          decision_arm={r: out['decision'][r]['arm'] for r in 'AB'}, b2=out['decision']['B2'],
                          valid46={r: out['valid46'][r]['arm'] for r in 'AB'}, valid46_b2=out['valid46']['B2'],
                          final=out['final_decision']), indent=1))


if __name__ == '__main__':
    main()
