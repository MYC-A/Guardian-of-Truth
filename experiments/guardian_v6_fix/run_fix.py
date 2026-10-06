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
    ap.add_argument('--max-calls', type=int, default=120)
    ap.add_argument('--rfix-dir', default=None, help='R_fix live records dir (default outputs/universal_repair/runs)')
    ap.add_argument('--orig-v6', action='store_true', help='compute original v6 layers here (cache copy cache/v6frules)')
    a = ap.parse_args()
    t = Transport('mistral', MODEL, FIX / 'cache' / 'frules', offline=not a.live, max_calls=a.max_calls if a.live else 0,
                  retry_failed=2, sender=paced if a.live else None)
    client = ReadThrough('mistral', MODEL, [], live=t)
    L = {(b, r): Layers(client, MODEL, budget=b, attempts=att) for b in BUDGETS for r, att in REPLICATES.items()}
    (FIX / 'runs').mkdir(parents=True, exist_ok=True)
    V6L = None
    if a.orig_v6:
        from guardian_truth.v6.pipeline import Layers as V6Layers
        from guardian_truth.v6.decide import decide_v6
        t6 = Transport('mistral', MODEL, FIX / 'cache' / 'v6frules', offline=not a.live, max_calls=a.max_calls if a.live else 0,
                       retry_failed=2, sender=paced if a.live else None)
        V6L = V6Layers(ReadThrough('mistral', MODEL, [], live=t6), MODEL)
    for s in a.sets.split(','):
        g, rows = gold_for(s), {r['id']: r for r in inputs(s)}
        recs = {}
        for k in (1, 2, 3):
            p = (Path(a.rfix_dir) if a.rfix_dir else OUT / 'runs') / s / f'rep{k}_R_fix_live.jsonl'
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
                lab = g[i]['label']
                cat = (('format_only' if g[i]['kind'] in ('F1', 'F2') else 'semantic_only') if lab == 1 else 'correct' if lab == 0 else 'unknown') \
                    if 'template' in g[i] else category(s, g[i])
                if V6L is not None:
                    f6 = V6L.findings(row)[0]
                    v6 = {k: {i: decide_v6(recs[k][i], f6)[0]} for k in recs if i in recs[k]}
                out = dict(set=s, id=i, label=lab if lab == 'UNKNOWN' else int(lab), category=cat,
                           rfix={k: decide_v5(recs[k][i])[0] for k in recs if i in recs[k]},
                           rfix_owner={k: (decide_v5(recs[k][i])[1] or {}).get('origin') for k in recs if i in recs[k]},
                           v6={k: v6[k][i] for k in v6 if i in v6[k]}, layers={})
                if V6L is not None:
                    out['v6_findings'] = [dict(layer=x.get('layer') or x.get('origin'), kind=x.get('kind'), target_id=x.get('target_id'))
                                          for x in f6]
                if 'template' in g[i]:
                    out.update(template=g[i]['template'], split=g[i]['split'], family=g[i]['family'], kind=g[i]['kind'])
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
