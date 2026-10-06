"""P3 oracle-ceiling funnel: for every gold-ERROR row a run misses, the first stage at which it was lost.
Stages: BASE_SAID_OK+NO_TRIGGER, NO_CANDIDATE (triggered, empty pool), NOT_EXECUTED/TECHNICAL_FAILURE, UNCHECKED (queue bound),
UNRESOLVED, VERIFIER_REFUTED (every checked candidate refuted). Usage: python -m experiments.universal_repair.funnel --arm R_comb --mode live"""
import argparse
import json
from collections import Counter

from guardian_truth.repair.v5 import decide
from .score import gold_for, arm_records, SETS
from .run import OUT


def stage(rec):
    pool = [p for p in (rec.get('pool') or []) if p['component'] != 'CB']
    trig = rec.get('triggers') or {}
    fired = any(bool(v) for v in trig.values()) if isinstance(trig, dict) else bool(trig)
    if not pool:
        return 'NO_CANDIDATE' if fired else 'NO_TRIGGER'
    st = Counter(p.get('verification_status') or 'UNCHECKED' for p in pool)
    for s in ('NOT_EXECUTED', 'TECHNICAL_FAILURE', 'UNCHECKED', 'UNRESOLVED'):
        if st.get(s):
            return s
    return 'VERIFIER_REFUTED'


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--arm', default='R_comb'); ap.add_argument('--mode', default='live')
    ap.add_argument('--sets', default=','.join(f'{s}:{r}' for s, rs in SETS.items() for r in rs) + ',hold_tau2h:1,hold_tau2h:2,hold_tau2h:3,valid46:2,valid46:3')
    a = ap.parse_args()
    out, tot = {}, Counter()
    for sr in a.sets.split(','):
        s, r = sr.split(':'); r = int(r)
        try:
            recs, _ = arm_records(s, r, a.arm, a.mode)
        except Exception as e:
            out[sr] = dict(error=str(e)[:200]); continue
        g = gold_for(s); rows = []
        for i, rec in recs.items():
            if i in g and g[i]['label'] == 1 and not decide(rec)[0]:
                pool = [p for p in (rec.get('pool') or []) if p['component'] != 'CB']
                rows.append(dict(id=i, stage=stage(rec), n_candidates=len(pool),
                                 candidates=[dict(component=p['component'], kind=p['candidate'].get('kind'), target=p['candidate'].get('target_id'),
                                                  status=p.get('verification_status'), certificate=bool(p['candidate'].get('certificate')))
                                             for p in pool][:8]))
        c = Counter(x['stage'] for x in rows); tot.update(c)
        out[sr] = dict(fn=len(rows), stages=dict(c), rows=rows)
    out['_total'] = dict(tot)
    p = OUT / 'phase3' / f'funnel_{a.arm}_{a.mode}.json'; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    for k, v in out.items():
        print(k, v if k == '_total' else (v.get('fn'), v.get('stages'), v.get('error')))


if __name__ == '__main__':
    main()
