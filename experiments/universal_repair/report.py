"""Universal-repair report: per set/rep/arm metrics on validated records, deltas vs V4r, receipts, flips.
  python -X utf8 -m experiments.universal_repair.report --mode offline|live --out outputs/universal_repair/<phase>/report.json"""
import argparse, json
from collections import Counter
from pathlib import Path

from guardian_truth.repair.v5 import decide
from .score import SETS, gold_for, metrics, arm_records
from .run import ROOT

ARMS = ['V4r', 'R_fix', 'R_df', 'R_pool', 'R_wit', 'R_comb']
PRESERVE = {('lb2_long', 'lb2L_037'): 'H5e', ('lb3_long', 'lb3L_000'): 'CL3e', ('lb3_long', 'lb3L_055'): 'BK3e',
            ('lb3_long', 'lb3L_003'): 'TL3e', ('lb2_long', 'lb2L_018'): 'G3e'}


def receipts(recs):
    c = Counter()
    for r in recs.values():
        for it in r.get('pool') or []:
            c['queued'] += 1
            c['vs:' + str(it.get('verification_status'))] += 1
        for k, comp in (r.get('components') or {}).items():
            if str(comp.get('admission', '')).startswith('NOT_EXECUTED'):
                c[f'{k}:NOT_EXECUTED'] += 1
            for b in comp.get('batch_admission') or []:
                if b in ('NOT_EXECUTED', 'OVERFLOW_UNCHECKED'):
                    c[f'{k}:batch_{b}'] += 1
    return dict(c)


def build(mode, arms=ARMS, sets=SETS):
    out = dict(mode=mode, sets={})
    golds = {s: gold_for(s) for s in sets}
    golds.setdefault('ext_tau2', gold_for('ext_tau2'))
    golds['ext_tau2v2_strict'] = gold_for('ext_tau2v2_strict')
    for s, reps in sets.items():
        g = golds[s]
        for rep in reps:
            base = None
            for arm in arms:
                try:
                    try:
                        recs, rv = arm_records(s, rep, arm, 'offline' if arm == 'V4r' else mode)
                    except FileNotFoundError:
                        if arm != 'V4r' or mode != 'live':
                            raise
                        recs, rv = arm_records(s, rep, arm, 'live')   # new reps/holdout: V4r itself needed live calls
                except (FileNotFoundError, AssertionError) as e:
                    out['sets'].setdefault(f'{s}#{rep}', {})[arm] = dict(missing=str(e)[:200])
                    continue
                for variant, kw in ((arm, {}), (arm + '_mech', dict(mech=True))):
                    if variant == 'V4r_mech':
                        continue
                    pred = {i: decide(r, **kw) for i, r in recs.items()}
                    m = metrics({i: p[0] for i, p in pred.items()}, g)
                    row = dict(m, receipts=receipts(recs) if not kw else None, records=dict(lines=rv['lines'], retry_chains=rv['retry_chains']))
                    if s == 'ext_tau2':
                        row['strict65'] = metrics({i: p[0] for i, p in pred.items()}, golds['ext_tau2v2_strict'])
                    if arm == 'V4r':
                        base = pred
                    else:
                        row['new_pos'] = sorted((i, g[i]['label'], pred[i][1]['origin']) for i in pred if i in g and pred[i][0] and not base[i][0])
                        row['lost_pos'] = sorted((i, g[i]['label']) for i in pred if i in g and base[i][0] and not pred[i][0])
                    row['preserved'] = {v: dict(pred=pred[i][0], origin=(pred[i][1] or {}).get('origin')) for (ss, i), v in PRESERVE.items() if ss == s and i in pred}
                    row['pred'] = {i: [p[0], (p[1] or {}).get('origin'), (p[1] or {}).get('target_id')] for i, p in pred.items()}
                    out['sets'].setdefault(f'{s}#{rep}', {})[variant] = row
    return out


def table(rep):
    lines = ['| set#rep | arm | TP | FP | FN | F1 | new +/− vs V4 | not executed / unchecked |', '|---|---|---|---|---|---|---|---|']
    for sr, arms in rep['sets'].items():
        for arm, m in arms.items():
            if 'missing' in m:
                lines.append(f'| {sr} | {arm} | — | — | — | — | missing | |')
                continue
            rc = m.get('receipts') or {}
            ne = sum(v for k, v in rc.items() if 'NOT_EXECUTED' in k or 'UNCHECKED' in k)
            np_ = m.get('new_pos', [])
            delta = f"+{sum(1 for x in np_ if x[1] == 1)}TP/+{sum(1 for x in np_ if x[1] == 0)}FP, −{sum(1 for x in m.get('lost_pos', []) if x[1] == 1)}TP/−{sum(1 for x in m.get('lost_pos', []) if x[1] == 0)}FP" if arm != 'V4r' else ''
            lines.append(f"| {sr} | {arm} | {m['tp']} | {m['fp']} | {m['fn']} | {m['f1']} | {delta} | {ne or ''} |")
    return '\n'.join(lines)


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    ap.add_argument('--mode', default='offline')
    ap.add_argument('--out', type=Path, required=True)
    ap.add_argument('--extra', action='store_true', help='add valid46 reps 2-3 and the frozen holdout reps 1-3')
    a = ap.parse_args()
    sets = dict(SETS)
    if a.extra:
        sets['valid46'] = (1, 2, 3); sets['hold_tau2h'] = (1, 2, 3)
    r = build(a.mode, sets=sets)
    a.out.parent.mkdir(parents=True, exist_ok=True)
    a.out.write_text(json.dumps(r, ensure_ascii=False, indent=1), encoding='utf-8')
    a.out.with_suffix('.md').write_text(table(r) + '\n', encoding='utf-8')
    print(table(r))
