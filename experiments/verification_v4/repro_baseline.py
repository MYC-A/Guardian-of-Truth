"""V4 commit 1: offline reproduction of the stored guard_adm2 baseline (A_adm2) from the frozen V3 run files.
No model calls (scorer reads stored records + cached judge verdicts)."""
import json
from experiments.verification_v2.score_v3 import report, OUT

RUNS = [('valid46', 1, '_v3dev5'), ('lb_long', 1, '_v3dev5'), ('lb2_long', 1, '_v3dev5'), ('lb3_long', 1, '_v3'), ('lb3_long', 2, '_v3')]

if __name__ == '__main__':
    res = []
    for s, rep, tag in RUNS:
        o = report(s, rep, tag, quiet=True)
        a = o['strata']['all']['A_adm2']
        res.append(dict(set=s, rep=rep, run=f'rep{rep}{tag}', rows=o['rows'], tp=a['tp'], fp=a['fp'], F1=round(a['F1'], 3),
                        cause_correct_tp=a['cause_correct_tp'], V3=dict(tp=o['strata']['all']['V3']['tp'], fp=o['strata']['all']['V3']['fp'])))
        print(res[-1])
    (OUT.parent / 'verification_v4').mkdir(exist_ok=True)
    (OUT.parent / 'verification_v4' / 'baseline_repro.json').write_text(json.dumps(res, indent=1))
