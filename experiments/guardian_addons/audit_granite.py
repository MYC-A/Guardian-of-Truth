"""Offline (0 HTTP): overlap of the saved Granite Guardian 3.3 groundedness control (outputs/searh_23/baseline_frozen/
control_repro_percase.csv; columns granite_repro = re-run on the server, granite_flash = the historical frozen run) with
the saved R_fix + v6fix decisions on valid46 (outputs/guardian_v6_fix/runs/valid46.jsonl; v6fix decision = fix_20000_A:
ERROR if a MECHANICAL layer finding, else the R_fix decision of the rep), and optionally with new variant runs.
valid46 is REGRESSION data (studied many times). Arms: standalone, fixed OR, diagnostic AND (no oracle switch).
  python -m experiments.guardian_addons.audit_granite [--variant-runs outputs/guardian_addons/runs/valid46/<V>_rep1.jsonl ...]"""
import argparse, csv, json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]


def met(pred, gold):
    tp = sum(1 for i in gold if pred[i] and gold[i]); fp = sum(1 for i in gold if pred[i] and not gold[i])
    fn = sum(1 for i in gold if not pred[i] and gold[i]); tn = len(gold) - tp - fp - fn
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, f1=round(2 * tp / (2 * tp + fp + fn), 3) if tp + fp + fn else None)


def load():
    g = {r['id']: r for r in csv.DictReader(open(ROOT / 'outputs/searh_23/baseline_frozen/control_repro_percase.csv'))}
    v6 = {}
    for r in map(json.loads, open(ROOT / 'outputs/guardian_v6_fix/runs/valid46.jsonl', encoding='utf-8')):
        mech = any(f['status'] == 'MECHANICAL' for f in r['layers']['20000_A']['findings'])
        v6[r['id']] = dict(label=r['label'], v6fix={k: 1 if mech else d for k, d in r['rfix'].items()})
    return g, v6


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--variant-runs', nargs='*', default=[]); ap.add_argument('--json')
    a = ap.parse_args()
    g, v6 = load()
    ids = sorted(set(g) & set(v6))
    gold = {i: int(g[i]['gold']) for i in ids}
    assert all(gold[i] == v6[i]['label'] for i in ids), 'gold mismatch between granite csv and v6fix runs'
    out = dict(n=len(ids), missing_in_v6fix=sorted(set(g) - set(v6)), arms={})
    for col in ('granite_repro', 'granite_flash', 'baseline'):
        out['arms'][col] = met({i: int(g[i][col]) for i in ids}, gold)
    systems = {f'v6fix_rep{k}': {i: v6[i]['v6fix'][k] for i in ids} for k in ('1', '2', '3')}
    for p in a.variant_runs:
        recs = {}
        for x in open(p, encoding='utf-8'):
            r = json.loads(x); recs[r['id']] = r
        systems[Path(p).stem] = {i: int((recs.get(i) or {}).get('binary') or 0) for i in ids}
        out.setdefault('variant_missing', {})[Path(p).stem] = [i for i in ids if i not in recs]
    G = {i: int(g[i]['granite_repro']) for i in ids}
    for name, s in systems.items():
        out['arms'][name] = met(s, gold)
        out['arms'][name + '_OR_granite'] = met({i: s[i] or G[i] for i in ids}, gold)
        out['arms'][name + '_AND_granite'] = met({i: s[i] and G[i] for i in ids}, gold)
        out.setdefault('granite_unique_tp', {})[name] = [i for i in ids if gold[i] and G[i] and not s[i]]
        out.setdefault('granite_unique_fp', {})[name] = [i for i in ids if not gold[i] and G[i] and not s[i]]
        out.setdefault('system_unique_tp', {})[name] = [i for i in ids if gold[i] and s[i] and not G[i]]
    for k, m in out['arms'].items():
        print(f"{k:28s} {m}")
    for k in out['granite_unique_tp']:
        print(k, 'granite-only TP', len(out['granite_unique_tp'][k]), 'granite-only FP', len(out['granite_unique_fp'][k]),
              'system-only TP', len(out['system_unique_tp'][k]))
    if a.json:
        Path(a.json).write_text(json.dumps(out, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
