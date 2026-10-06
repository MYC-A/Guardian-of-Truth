"""v2: offline exact-key replay of R_fix with the v2 code boundaries vs the committed A2 live runs.
  python -X utf8 -m experiments.universal_repair.v2_replay --out outputs/universal_repair_v2/replay_vs_a2.json"""
import argparse, json
from guardian_truth.repair import records
from guardian_truth.repair.v5 import decide
from .run import OUT, inputs
from .score import gold_for, metrics

RUNS = [('valid46', 1), ('valid46', 2), ('valid46', 3), ('lb_long', 1), ('lb2_long', 1), ('lb3_long', 1), ('lb3_long', 2),
        ('ext_tau2', 1), ('ext_tau2', 2), ('ext_tau2', 3), ('hold_tau2h', 1), ('hold_tau2h', 2), ('hold_tau2h', 3)]


def load(d, s, r, mode):
    ids = [x['id'] for x in inputs(s)]
    return records.load(d / s / f'rep{r}_R_fix_{mode}.jsonl', ids)[0]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--out', required=True); a = ap.parse_args()
    rep = []
    for s, r in RUNS:
        old, new, g = load(OUT / 'runs', s, r, 'live'), load(OUT.parent / 'universal_repair_v2/runs_offline', s, r, 'offline'), gold_for(s)
        po = {i: decide(x)[0] for i, x in old.items()}; pn = {i: decide(x)[0] for i, x in new.items()}
        flips = []
        for i in po:
            if po[i] != pn.get(i) or (decide(old[i])[1] or {}).get('origin') != (decide(new[i])[1] or {}).get('origin'):
                flips.append(dict(id=i, gold=g.get(i, {}).get('label'), a2=po[i], v2=pn.get(i),
                                  a2_origin=(decide(old[i])[1] or {}).get('origin'), v2_origin=(decide(new[i])[1] or {}).get('origin')))
        rep.append(dict(set=s, rep=r, n_a2=len(old), n_v2=len(new), a2=metrics(po, g), v2=metrics(pn, g), flips=flips))
        print(s, r, rep[-1]['a2'], rep[-1]['v2'], len(flips))
    json.dump(rep, open(a.out, 'w'), indent=1)


if __name__ == '__main__':
    main()
