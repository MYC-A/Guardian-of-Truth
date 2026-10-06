"""Holdout metrics on frozen gold vs adjudicated v2 gold (outputs/universal_repair_v2/holdout/GOLD_adjudicated_v2.json):
precision / recall / specificity / F1 per rep + constant-ERROR baseline."""
import json
from guardian_truth.repair.v5 import decide
from .run import OUT
from .score import gold_for, arm_records

V2 = OUT.parent / 'universal_repair_v2'


def m(pred, gold):
    tp = sum(p and gold[i]['label'] == 1 for i, p in pred.items()); fp = sum(p and gold[i]['label'] == 0 for i, p in pred.items())
    fn = sum((not p) and gold[i]['label'] == 1 for i, p in pred.items()); tn = sum((not p) and gold[i]['label'] == 0 for i, p in pred.items())
    r = lambda a, b: round(a / b, 3) if b else None
    return dict(n=len(pred), tp=tp, fp=fp, fn=fn, tn=tn, precision=r(tp, tp + fp), recall=r(tp, tp + fn), specificity=r(tn, tn + fp),
                f1=r(2 * tp, 2 * tp + fp + fn))


def main():
    G = dict(frozen=gold_for('hold_tau2h'))
    a = json.loads((V2 / 'holdout' / 'GOLD_adjudicated_v2.json').read_text(encoding='utf-8'))
    G['adjudicated_v2'] = {k: v for k, v in a.items() if not v.get('excluded_v2')}
    out = {}
    for gname, g in G.items():
        out[f'{gname}:constant_ERROR'] = m({i: 1 for i in g}, g)
        for arm in ('V4r', 'R_fix', 'R_comb'):
            for rep in (1, 2, 3):
                recs, _ = arm_records('hold_tau2h', rep, arm, 'live')
                out[f'{gname}:{arm}:r{rep}'] = m({i: bool(decide(r)[0]) for i, r in recs.items() if i in g}, g)
    (V2 / 'holdout' / 'metrics_v2.json').write_text(json.dumps(out, indent=1), encoding='utf-8')
    for k, v in out.items():
        print(k, v)


if __name__ == '__main__':
    main()
