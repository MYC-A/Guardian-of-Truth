"""Offline recompute (zero network, no model): every metric of the v6-fix report from the saved per-row files
outputs/guardian_v6_fix/runs/<set>.jsonl (written by run_fix.py). Decisions:
  rfix            saved R_fix decision of rep k
  v6              saved original-v6 decision of rep k
  fix_<B>_<X>     ERROR if any MECHANICAL finding of the fixed layers (budget B, extraction replicate X), else rfix
  fixF_<B>_<X>    same with layer F only
  python -m experiments.guardian_v6_fix.recompute [--json OUT] [--rows]"""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'outputs/guardian_v6_fix/runs'
DEV = ['valid46', 'lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h']
GROUPS = {'dev_pooled': DEV, 'holdout2': ['hold_holdout2'], 'frozen120': ['hold_frozen120']}


def mech(r, key, layers=None):
    return [f for f in r['layers'].get(key, {}).get('findings', []) if f['status'] == 'MECHANICAL' and (layers is None or f['layer'] in layers)]


def arms(r):
    keys = sorted(r['layers'])
    out = {}
    for k, d in r['rfix'].items():
        a = {'rfix': d}
        if k in r['v6']:
            a['v6'] = r['v6'][k]
        for key in keys:
            a[f'fix_{key}'] = 1 if mech(r, key) else d
            a[f'fixF_{key}'] = 1 if mech(r, key, ('F',)) else d
        out[k] = a
    return out


def met(c):
    tp, fp, fn, tn = (c.get(x, 0) for x in ('tp', 'fp', 'fn', 'tn'))
    q = lambda a, b: round(a / b, 3) if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=q(tp, tp + fp), recall=q(tp, tp + fn), specificity=q(tn, tn + fp), f1=q(2 * tp, 2 * tp + fp + fn))


def oc(d, lab):
    return ('tp' if d else 'fn') if lab else ('fp' if d else 'tn')


def load(sets):
    rows = []
    for s in sets:
        p = RUNS / f'{s}.jsonl'
        if p.exists():
            rows += [json.loads(x) for x in p.read_text(encoding='utf-8').splitlines()]
    return rows


def summarize(rows, split_key=None):
    res = defaultdict(Counter)
    per_row = defaultdict(dict)
    for r in rows:
        if r['label'] == 'UNKNOWN':
            continue
        for k, a in arms(r).items():
            for name, d in a.items():
                o = oc(d, r['label'])
                for scope in ('ALL', r['category'], *( [f"split:{r['split']}", f"split:{r['split']}|{r['category']}"] if split_key and 'split' in r else [])):
                    res[(name, k, scope)][o] += 1
                    res[(name, 'pooled', scope)][o] += 1
                per_row[(r['set'], r['id'], k)][name] = d
    return {f'{n}|rep{k}|{s}': met(c) for (n, k, s), c in sorted(res.items())}, per_row


def changes(rows, base, other):
    """rows where `other` differs from `base`: new FP / fixed FN / lost TP / removed FP."""
    out = defaultdict(list)
    for r in rows:
        if r['label'] == 'UNKNOWN':
            continue
        for k, a in arms(r).items():
            if base not in a or other not in a or a[base] == a[other]:
                continue
            tag = ('fixed_FN' if a[other] else 'lost_TP') if r['label'] else ('new_FP' if a[other] else 'removed_FP')
            out[tag].append(f"{r['set']}:{r['id']}:rep{k}:{r['category']}")
    return {k: sorted(v) for k, v in out.items()}


def layer_table(rows, key):
    c = Counter()
    for r in rows:
        for f in r['layers'].get(key, {}).get('findings', []):
            c[(f['layer'], f['kind'], f['status'], str(r['label']))] += 1
    return {'|'.join(k): v for k, v in sorted(c.items())}


CAUSE = {'MAX_TOOL_CALLS_PER_TURN': {'F1'}, 'NO_TEXT_WITH_TOOL_CALL': {'F2'}, 'UNDECLARED_TOOL': {'UNDECLARED_TOOL'},
         'UNSOURCED_REFERENCE': {'INVENTED_ID', 'WRONG_ID'}, 'NOT_FROM_USER': {'NOT_FROM_USER'}}


def gold_kinds(s, i, _cache={}):
    if s not in _cache:
        from experiments.universal_repair.score import gold_for
        _cache[s] = gold_for(s)
    g = _cache[s].get(i, {})
    k = g.get('kinds', g.get('kind'))
    if k is None:
        return None
    k = eval(k) if isinstance(k, str) and k.startswith('[') else k
    return set(k) if isinstance(k, (list, tuple, set)) else {k}


def cause_check(rows, key):
    """Decisive (first MECHANICAL, priority F>S>P) finding on label-1 rows vs the gold kinds (code mapping CAUSE).
    Only rows whose gold carries kinds; others are 'no_gold_kind'."""
    order = {'F': 0, 'S': 1, 'P': 2}
    c, bad = Counter(), []
    for r in rows:
        if r['label'] != 1:
            continue
        m = sorted(mech(r, key), key=lambda f: order[f['layer']])
        if not m:
            continue
        gk = gold_kinds(r['set'], r['id'])
        if gk is None:
            c['no_gold_kind'] += 1
        elif CAUSE.get(m[0]['kind'], set()) & gk:
            c['match'] += 1
        else:
            c['mismatch'] += 1
            bad.append(f"{r['set']}:{r['id']}:{m[0]['kind']} vs {sorted(gk)}")
    return dict(c, mismatches=bad)


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--json'); ap.add_argument('--rows', action='store_true'); a = ap.parse_args()
    out = {}
    for g, sets in GROUPS.items():
        rows = load(sets)
        if not rows:
            continue
        m, _ = summarize(rows, split_key=(g == 'frozen120'))
        keys = sorted({k for r in rows for k in r['layers']})
        out[g] = dict(n_rows=len(rows), unique_tasks=len({(r['set'], r['id']) for r in rows}), metrics=m,
                      layers={k: layer_table(rows, k) for k in keys},
                      incomplete={k: sum(not r['layers'][k]['complete'] for r in rows) for k in keys},
                      changes={f'{b}->{o}': changes(rows, b, o) for b, o in
                               [('rfix', 'v6'), ('rfix', 'fix_20000_A'), ('rfix', 'fix_400000_A'), ('v6', 'fix_400000_A'), ('v6', 'fix_20000_A'),
                                ('fix_20000_A', 'fix_20000_B'), ('fix_400000_A', 'fix_400000_B')]},
                      cause={k: cause_check(rows, k) for k in keys},
                      false_mechanical={k: sorted(f"{r['set']}:{r['id']}:{f['layer']}:{f['kind']}" for r in rows if r['label'] == 0
                                                  for f in mech(r, k)) for k in keys})
    txt = json.dumps(out, ensure_ascii=False, indent=1)
    if a.json:
        Path(a.json).write_text(txt, encoding='utf-8')
    for g, d in out.items():
        print(f'== {g}: rows {d["n_rows"]}')
        for name in ('rfix', 'v6', 'fix_20000_A', 'fix_400000_A', 'fixF_20000_A', 'fixF_400000_A', 'fix_20000_B', 'fix_400000_B'):
            for scope in ('ALL', 'format_only', 'mixed', 'semantic_only', 'unclassified'):
                m = d['metrics'].get(f'{name}|reppooled|{scope}')
                if m:
                    print(f'  {name:14s} {scope:13s} TP {m["tp"]:3d} FP {m["fp"]:3d} FN {m["fn"]:3d} TN {m["tn"]:3d} F1 {m["f1"]}')
        print('  false mechanical:', {k: len(v) for k, v in d['false_mechanical'].items()})
        print('  cause:', {k: {x: y for x, y in v.items() if x != 'mismatches'} for k, v in d['cause'].items()})


if __name__ == '__main__':
    main()
