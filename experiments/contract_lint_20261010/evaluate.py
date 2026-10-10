"""Offline evaluation of contract lint per docs/contract_lint_20261010/PROTOCOL.md.

Uses stored B2 Q8 rep1 binaries; no model calls. Gold is read only here.
    GUARDIAN_DATA_ROOT=. PYTHONPATH=src:. python3 -m experiments.contract_lint_20261010.evaluate --out <json>
"""
import argparse
import hashlib
import json

from experiments.contract_lint_20261010.lint import lint
from experiments.guardian_complementarity.combine import QW, runs
from experiments.guardian_local_a100.run_local import rows
from experiments.guardian_local_a100.score_local import gold_for

DECISION = ['ext_tau2', 'hold_tau2h', 'hold_holdout2', 'lb_long', 'lb2_long', 'lb3_long', 'contrast', 'dev', 'devT', 'frozen']
REPORT_ONLY = ['valid46']
CHECKS = ['UNKNOWN_TOOL', 'SCHEMA+INVALID_ARGS_JSON', 'REPEAT_FAILED']
GROUP = {'UNKNOWN_TOOL': {'UNKNOWN_TOOL'}, 'SCHEMA+INVALID_ARGS_JSON': {'SCHEMA', 'INVALID_ARGS_JSON'},
         'REPEAT_FAILED': {'REPEAT_FAILED'}, 'ALL_L0': {'UNKNOWN_TOOL', 'SCHEMA', 'INVALID_ARGS_JSON', 'REPEAT_FAILED'}}


def collect(pools, seen):
    out = []
    for pool in pools:
        gold = {i: g['label'] for i, g in gold_for(pool).items() if g.get('label') in (0, 1)}
        b2 = runs(QW / pool / 'B2_rep1.jsonl', 'B2') or {}
        for r in rows(pool):
            key = hashlib.sha256((r['prompt'] + '\0' + (r['response'] or '')).encode()).hexdigest()
            if r['id'] not in gold or key in seen:
                continue
            seen.add(key)
            out.append(dict(pool=pool, id=r['id'], gold=gold[r['id']], b2=(b2.get(r['id']) or {}).get('b'),
                            findings=lint(r['prompt'], r['response'] or '')))
    return out


def tally(items, group):
    t = dict(rows=len(items), fires_pos=0, fires_neg=0, new_tp=0, new_fp=0, b2_gaps=0)
    for x in items:
        fired = any(f['check'] in GROUP[group] for f in x['findings'])
        if fired:
            t['fires_pos' if x['gold'] else 'fires_neg'] += 1
        if x['b2'] is None:
            t['b2_gaps'] += 1
            continue
        if fired and x['b2'] == 0:
            t['new_tp' if x['gold'] else 'new_fp'] += 1
    fires = t['fires_pos'] + t['fires_neg']
    t['fire_precision'] = round(t['fires_pos'] / fires, 4) if fires else None
    return t


def f1(items, group=None):
    c = dict(TP=0, FP=0, FN=0, TN=0)
    for x in items:
        if x['b2'] is None:
            continue
        p = int(x['b2'] or (group is not None and any(f['check'] in GROUP[group] for f in x['findings'])))
        c[('TN', 'FP', 'FN', 'TP')[2 * x['gold'] + p]] += 1
    c['F1'] = round(2 * c['TP'] / max(1, 2 * c['TP'] + c['FP'] + c['FN']), 4)
    return c


def decide(t):
    fires = t['fires_pos'] + t['fires_neg']
    if t['new_fp'] >= 3 or (t['fire_precision'] is not None and t['fire_precision'] < 0.8):
        return 'REJECT'
    if t['new_fp'] == 0 and fires >= 3:
        return 'HARD'
    if t['new_fp'] <= 2 and fires >= 1:
        return 'EVIDENCE_ONLY'
    return 'INSUFFICIENT_FIRES'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--out', required=True)
    a = ap.parse_args()
    seen = set()
    dec, rep = collect(DECISION, seen), collect(REPORT_ONLY, seen)
    result = dict(protocol='docs/contract_lint_20261010/PROTOCOL.md', decision_rows=len(dec), report_rows=len(rep))
    for name, items in (('decision', dec), ('valid46_report_only', rep)):
        block = dict(B2=f1(items))
        for g in GROUP:
            block[g] = dict(tally=tally(items, g), arm=f1(items, g),
                            per_pool={p: tally([x for x in items if x['pool'] == p], g) for p in sorted({x['pool'] for x in items})})
        result[name] = block
    result['decisions'] = {g: decide(result['decision'][g]['tally']) for g in CHECKS}
    result['fired_rows'] = [dict(pool=x['pool'], id=x['id'], gold=x['gold'], b2=x['b2'], findings=x['findings'])
                            for x in dec + rep if x['findings']]
    with open(a.out, 'x', encoding='utf-8', newline='\n') as s:
        json.dump(result, s, indent=1, ensure_ascii=False)
        s.write('\n')
    print(json.dumps(dict(decisions=result['decisions'],
                          decision={g: result['decision'][g]['tally'] for g in GROUP},
                          decision_B2=result['decision']['B2'], decision_ALL=result['decision']['ALL_L0']['arm'],
                          valid46={g: result['valid46_report_only'][g]['tally'] for g in GROUP},
                          valid46_B2=result['valid46_report_only']['B2'], valid46_ALL=result['valid46_report_only']['ALL_L0']['arm']), indent=1))


if __name__ == '__main__':
    main()
