"""Stage 1: recompute R_fix / original-v6 metrics from the SAVED per-row run files (no network, no Guardian decision code),
split by gold category. Category comes from gold only:
  tau2-family (ext_tau2, hold_tau2h, hold_holdout2): kinds F1/F2 = format, S = semantic
     format_only | mixed (format + semantic) | semantic_only | correct (label 0)
  lockboxes: no turn-shape rules in their policies -> label 1 = semantic_only, label 0 = correct
  valid46: gold has a free-text cause only -> label 1 = unclassified, label 0 = correct
  python -m experiments.guardian_v6_fix.stage1_baseline [--json OUT]"""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
RUNS = ROOT / 'outputs/guardian_v6/runs'
GOLD = {'valid46': None, 'lb_long': 'outputs/verification_v2/lockbox/long/GOLD_eval_only.json',
        'lb2_long': 'outputs/verification_v2/lockbox2/long/GOLD_eval_only.json',
        'lb3_long': 'outputs/verification_v2/lockbox3/long/GOLD_eval_only.json',
        'ext_tau2': 'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json',
        'hold_tau2h': 'outputs/universal_repair/holdout/tau2h/GOLD_frozen.json',
        'hold_holdout2': 'outputs/guardian_v6/holdout2/GOLD_frozen.json'}


def gold(s):
    if GOLD[s] is None:
        import pandas as pd
        return {r.id: dict(label=int(r.label)) for r in pd.read_parquet(ROOT / 'valid.parquet').itertuples()}
    return json.loads((ROOT / GOLD[s]).read_text(encoding='utf-8'))


def category(s, g):
    if int(g['label']) == 0:
        return 'correct'
    if s == 'valid46':
        return 'unclassified'
    kinds = g.get('kinds')
    if kinds is None:
        return 'semantic_only'
    kinds = eval(kinds) if isinstance(kinds, str) else kinds
    f = any(k in ('F1', 'F2') for k in kinds); sem = any(k not in ('F1', 'F2') for k in kinds)
    return 'mixed' if f and sem else 'format_only' if f else 'semantic_only'


def metrics(c):
    tp, fp, fn, tn = (c[k] for k in ('tp', 'fp', 'fn', 'tn'))
    r = lambda a, b: round(a / b, 3) if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=r(tp, tp + fp), recall=r(tp, tp + fn), specificity=r(tn, tn + fp),
                f1=r(2 * tp, 2 * tp + fp + fn))


def outcome(d, lab):
    return ('tp' if d else 'fn') if lab else ('fp' if d else 'tn')


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--json'); a = ap.parse_args()
    res = defaultdict(Counter); cats = {}
    for s in GOLD:
        G = gold(s)
        cats[s] = Counter(category(s, g) for g in G.values())
        for p in sorted((RUNS / s).glob('rep*.jsonl')):
            for r in map(json.loads, p.read_text(encoding='utf-8').splitlines()):
                g = G[r['id']]; lab = int(g['label']); cat = category(s, g)
                for arm in ('rfix', 'v6'):
                    o = outcome(r[arm], lab)
                    for key in ((s, p.stem, arm, cat), (s, p.stem, arm, 'ALL'), (s, p.stem, arm, 'NO_FORMAT' if cat in ('semantic_only', 'correct') else 'HAS_FORMAT_OR_UNCL')):
                        res[key][o] += 1
    out = {' | '.join(k): metrics(v) for k, v in sorted(res.items())}
    print('row categories per set:', {s: dict(c) for s, c in cats.items()})
    for k, v in out.items():
        print(k, v)
    if a.json:
        Path(a.json).write_text(json.dumps(dict(categories={s: dict(c) for s, c in cats.items()}, metrics=out), indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
