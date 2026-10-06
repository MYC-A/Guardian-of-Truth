"""Score v6 = R_fix (stored live records) + mechanical layers F/P/S. Writes outputs/guardian_v6/runs/<set>/rep<k>.jsonl.
  python -m experiments.guardian_v6.run_v6 [--sets a,b] [--live]"""
import argparse, json
from guardian_truth.integrated import Transport
from guardian_truth.repair import records
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import decide as decide_v5
from guardian_truth.v6.pipeline import Layers
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.score import gold_for

V6 = OUT.parent / 'guardian_v6'
DEV = ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h']


def m(pred, gold):
    tp = sum(p and gold[i]['label'] == 1 for i, p in pred.items()); fp = sum(p and gold[i]['label'] == 0 for i, p in pred.items())
    fn = sum((not p) and gold[i]['label'] == 1 for i, p in pred.items()); tn = sum((not p) and gold[i]['label'] == 0 for i, p in pred.items())
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, f1=round(2 * tp / (2 * tp + fp + fn), 3) if tp else 0.0,
                prec=round(tp / (tp + fp), 3) if tp + fp else None, rec=round(tp / (tp + fn), 3) if tp + fn else None,
                spec=round(tn / (tn + fp), 3) if tn + fp else None)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--sets', default=','.join(DEV)); ap.add_argument('--live', action='store_true')
    ap.add_argument('--gold', default=None, help='override gold json path (e.g. adjudicated)')
    a = ap.parse_args()
    t = Transport('mistral', MODEL, V6 / 'cache' / 'frules', max_calls=200 if a.live else 0, retry_failed=2, sender=paced)
    L = Layers(ReadThrough('mistral', MODEL, [], live=t), MODEL)
    summary = {}
    for s in a.sets.split(','):
        g = json.load(open(a.gold)) if a.gold else gold_for(s)
        rows = {r['id']: r for r in inputs(s)}
        fnd = {i: L.findings(r) for i, r in rows.items()}
        for k in (1, 2, 3):
            p = OUT / 'runs' / s / f'rep{k}_R_fix_live.jsonl'
            if not p.exists():
                continue
            recs, _ = records.load(p, list(rows))
            od = V6 / 'runs' / s; od.mkdir(parents=True, exist_ok=True)
            base, new = {}, {}
            with open(od / f'rep{k}.jsonl', 'w', encoding='utf-8') as f:
                from guardian_truth.v6.decide import decide_v6
                for i in rows:
                    if i not in g or i not in recs:
                        continue
                    d0, acc0 = decide_v5(recs[i]); d, acc = decide_v6(recs[i], fnd[i][0])
                    base[i], new[i] = d0, d
                    f.write(json.dumps(dict(id=i, label=g[i]['label'], rfix=d0, rfix_acc=acc0, v6=d, accusation=acc, findings=fnd[i][0],
                                            policy=fnd[i][1].get('policy')), ensure_ascii=False) + '\n')
            summary[(s, k)] = (m(base, g), m(new, g))
            print(s, k, 'R_fix', summary[(s, k)][0], '\n      v6  ', summary[(s, k)][1], flush=True)
    print(t.counts)


if __name__ == '__main__':
    main()
