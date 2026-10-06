"""Funnel v2 (docs/universal_repair_v2/FUNNEL_V2.md). Fixes vs v1: A UNKNOWN reported apart from A NO_ERROR; NO_CANDIDATE split
by component admission (e.g. INVALID_JSON_PLAN, NO_VERIFIED_REQUIREMENTS); UNCHECKED_QUEUE_BOUND recognised; CB marked
NOT_RUN (R_fix runs with_cb=False); holdout scored on frozen AND adjudicated-v2 gold; ownership of positives (A/GUARD vs repair).
This is a LOSS LOCATION diagnostic, not an oracle ceiling: no correct relation is injected here (see oracle_probe)."""
import json
from collections import Counter

from guardian_truth.repair.v5 import decide
from .run import OUT
from .score import gold_for, arm_records
from .cause_report import SETS

V2 = OUT.parent / 'universal_repair_v2'


def gold(s, adjudicated):
    if s == 'hold_tau2h' and adjudicated:
        g = json.loads((V2 / 'holdout' / 'GOLD_adjudicated_v2.json').read_text(encoding='utf-8'))
        return {k: v for k, v in g.items() if not v.get('excluded_v2')}
    return gold_for(s)


def stage(rec):
    if rec.get('skipped'):
        return 'NO_PACKET', {}
    A = rec.get('A') or {}
    a_state = 'A_NO_ERROR' if A.get('final') == 'NO_ERROR' else 'A_UNKNOWN' if A.get('final') in (None, 'UNKNOWN') else f"A_{A.get('final')}"
    if rec.get('triggers') is None:
        return f'{a_state}|NO_TARGET_OR_POLICY', {}
    trig = rec['triggers']
    fired = [k for k in ('T_multi', 'T_calc', 'T_quant') if trig.get(k)]
    if not fired:
        return f'{a_state}|NO_TRIGGER', {}
    comps = rec.get('components') or {}
    pool = [p for p in (rec.get('pool') or []) if p['component'] != 'CB']
    adm = {k: v.get('admission') for k, v in comps.items() if k != 'CB'}
    if not pool:
        why = sorted({str(v) for v in adm.values()}) or ['NO_COMPONENT']
        return f'{a_state}|NO_CANDIDATE:' + '+'.join(why), adm
    st = Counter(p.get('verification_status') or 'MISSING_STATUS' for p in pool)
    for s in ('NOT_EXECUTED', 'TECHNICAL_FAILURE', 'UNCHECKED_QUEUE_BOUND', 'MISSING_STATUS', 'UNRESOLVED'):
        if st.get(s):
            return f'{a_state}|{s}', adm
    return f'{a_state}|VERIFIER_REFUTED', adm


def main():
    out, tot = {}, {False: Counter(), True: Counter()}
    own = Counter()
    for sr in SETS:
        s, r = sr.split(':'); r = int(r)
        recs, _ = arm_records(s, r, 'R_fix', 'live')
        for adjudicated in ((False, True) if s == 'hold_tau2h' else (False,)):
            g = gold(s, adjudicated); rows = []
            for i, rec in recs.items():
                if i not in g:
                    continue
                p, acc = decide(rec)
                if p and not adjudicated:
                    own[(acc or {}).get('origin')] += 1
                if g[i]['label'] == 1 and not p:
                    st, adm = stage(rec)
                    rows.append(dict(id=i, stage=st, admissions=adm,
                                     candidates=[dict(component=x['component'], kind=x['candidate'].get('kind'), status=x.get('verification_status'))
                                                 for x in (rec.get('pool') or [])][:8]))
            c = Counter(x['stage'] for x in rows)
            tot[adjudicated].update(c)
            out[f'{sr}{":adjudicated_v2" if adjudicated else ""}'] = dict(fn=len(rows), stages=dict(c), rows=rows)
    out['_total_frozen_gold'] = dict(tot[False].most_common())
    hf = sum((Counter(out[k]['stages']) for k in out if k.startswith('hold_tau2h') and not k.endswith('adjudicated_v2')), Counter())
    ha = sum((Counter(out[k]['stages']) for k in out if k.endswith('adjudicated_v2')), Counter())
    out['_total_with_holdout_adjudicated'] = dict((tot[False] - hf + ha).most_common())
    out['_positives_by_owner'] = dict(own.most_common())
    out['_note'] = 'CB is not run in R_fix (with_cb=False): confirmation/consent misses can only be caught by A/GUARD.'
    p = V2 / 'funnel' / 'funnel_v2_R_fix_live.json'; p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding='utf-8')
    print('frozen gold FN stages:'); [print(' ', k, v) for k, v in tot[False].most_common()]
    print('holdout adjudicated FN stages:', dict(sum((Counter(out[k]['stages']) for k in out if k.endswith('adjudicated_v2')), Counter())))
    print('holdout frozen FN stages:', dict(sum((Counter(out[k]['stages']) for k in out if k.startswith('hold_tau2h') and not k.endswith('adjudicated_v2')), Counter())))
    print('total with holdout adjudicated:', out['_total_with_holdout_adjudicated'])
    print('positives by owner:', dict(own))


if __name__ == '__main__':
    main()
