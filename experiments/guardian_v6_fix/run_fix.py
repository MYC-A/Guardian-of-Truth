"""Stage 6 on the existing sets: fixed layers (v6fix) on top of the SAVED R_fix live records, at two layer budgets
(400k = original v6 layer context, 20k = R_fix context) and two extraction replicates (cache attempts 0/1 and 2/3).
Writes outputs/guardian_v6_fix/runs/<set>.jsonl (one line per row: label, category, saved R_fix per rep, saved original
v6 per rep, fixed-layer findings per budget/replicate). Decisions of every arm are derived offline by recompute.py.
  python -m experiments.guardian_v6_fix.run_fix [--sets a,b] [--live] [--max-calls N]
Without --live the Transport is offline: a missing cached extraction fails loudly (zero HTTP)."""
import argparse, json
from pathlib import Path

from guardian_truth.integrated import Transport
from guardian_truth.repair import records
from guardian_truth.repair.clients import ReadThrough
from guardian_truth.repair.v5 import decide as decide_v5
from guardian_truth.v6fix.pipeline import Layers
from experiments.universal_repair.run import OUT, MODEL, inputs, paced
from experiments.universal_repair.score import gold_for
from experiments.guardian_v6_fix.stage1_baseline import category

ROOT = Path(__file__).resolve().parents[2]
FIX = ROOT / 'outputs/guardian_v6_fix'
V6RUNS = ROOT / 'outputs/guardian_v6/runs'
SETS = ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h', 'hold_holdout2']
BUDGETS = (400000, 20000)
REPLICATES = {'A': (0, 1), 'B': (2, 3)}


def compact(f):
    n = f.get('norm') or {}
    return dict(layer=f['layer'], kind=f['kind'], target_id=f['target_id'], status=f['status'], fact=f['fact'],
                norm_basis=n.get('basis'), norm_source=n.get('source_id') or n.get('source_ids'), norm_quote=n.get('quote') or n.get('text'),
                checks=n.get('checks'))


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--sets', default=','.join(SETS)); ap.add_argument('--live', action='store_true')
    ap.add_argument('--max-calls', type=int, default=120); a = ap.parse_args()
    t = Transport('mistral', MODEL, FIX / 'cache' / 'frules', offline=not a.live, max_calls=a.max_calls if a.live else 0,
                  retry_failed=2, sender=paced if a.live else None)
    client = ReadThrough('mistral', MODEL, [], live=t)
    L = {(b, r): Layers(client, MODEL, budget=b, attempts=att) for b in BUDGETS for r, att in REPLICATES.items()}
    (FIX / 'runs').mkdir(parents=True, exist_ok=True)
    for s in a.sets.split(','):
        g, rows = gold_for(s), {r['id']: r for r in inputs(s)}
        recs = {}
        for k in (1, 2, 3):
            p = OUT / 'runs' / s / f'rep{k}_R_fix_live.jsonl'
            if p.exists():
                recs[k] = records.load(p, list(rows))[0]
        v6 = {}
        for k in (1, 2, 3):
            p = V6RUNS / s / f'rep{k}.jsonl'
            if p.exists():
                v6[k] = {r['id']: r['v6'] for r in map(json.loads, p.read_text(encoding='utf-8').splitlines())}
        with open(FIX / 'runs' / f'{s}.jsonl', 'w', encoding='utf-8') as f:
            for i, row in rows.items():
                if i not in g:
                    continue
                out = dict(set=s, id=i, label=int(g[i]['label']), category=category(s.replace('hold_holdout2', 'hold_holdout2'), g[i]),
                           rfix={k: decide_v5(recs[k][i])[0] for k in recs if i in recs[k]},
                           rfix_owner={k: (decide_v5(recs[k][i])[1] or {}).get('origin') for k in recs if i in recs[k]},
                           v6={k: v6[k][i] for k in v6 if i in v6[k]}, layers={})
                for (b, r), lay in L.items():
                    res = lay.findings(row)
                    out['layers'][f'{b}_{r}'] = dict(findings=[compact(x) for x in res['findings']],
                                                    complete=bool((res['coverage'] or {}).get('complete_input')),
                                                    rules=[dict(type=x['type'], n=x.get('n'), status=x['status'], source_id=x.get('source_id'),
                                                                quote=x['quote'], checks=x['checks']) for x in res['rules']],
                                                    policy_key=(res['extraction'] or {}).get('policy_key'))
                f.write(json.dumps(out, ensure_ascii=False, default=str) + '\n')
        print(s, len(rows), dict(t.counts) if hasattr(t, 'counts') else '', flush=True)
    print('transport', getattr(t, 'counts', None))


if __name__ == '__main__':
    main()
