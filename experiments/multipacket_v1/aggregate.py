"""Aggregate a multi-run report: mean/min/max F1, mean counts, pooled (row,run) sign test and per-row sign test vs A. Zero inference.
usage: python -m experiments.multipacket_v1.aggregate <report.json> <runs_dir> <gold.json|valid46> <out.json> arms..."""
import json, sys, math, statistics as st
rep, runs_dir, gold_p, out_p, *arms = sys.argv[1:]
R = json.load(open(rep))
if gold_p == 'valid46':
    from experiments.multipacket_v1.common import valid_gold
    gold = {k: v['label'] for k, v in valid_gold().items()}
else:
    gold = {k: v['label'] for k, v in json.load(open(gold_p)).items()}
def sign_p(a, b):
    n = a + b
    if n == 0: return 1.0
    k = min(a, b); return min(1.0, 2 * sum(math.comb(n, i) for i in range(k + 1)) / 2 ** n)
def dec(arm, k, key='decision'):
    out = {}
    for l in open(f'{runs_dir}/run{k}/{arm}.jsonl'):
        r = json.loads(l); out[r['id']] = r.get(key) or r.get('decision')
    return out
runs = sorted({int(k.split('run')[-1]) for k in R if '|run' in k})
res = {}
for a in arms:
    base, var = (a.split('[')[0], a.split('[')[1].rstrip(']')) if '[' in a else (a, None)
    rows = [R.get(f'{a}|all|run{k}') for k in runs]
    if not all(rows): continue
    d = {m: round(st.mean((x.get(m) or 0) for x in rows), 3) for m in ('f1', 'tp', 'fp', 'fn', 'unknown', 'tech', 'reason_correct_tp', 'reason_diff', 'extra_calls_per_row', 'prompt_tokens_per_row')}
    d['f1_min'] = min(x['f1'] for x in rows); d['f1_max'] = max(x['f1'] for x in rows)
    if base != 'A':
        fx = br = 0; rowwin = rowlose = 0
        key = {'sticky': 'sticky', 'any_error': 'any_error'}.get(var, 'decision')
        per = {}
        for k in runs:
            A = dec('A', k); X = dec(base, k, key)
            for i, y in gold.items():
                if i not in A or i not in X: continue
                ca = (A[i] == 'ERROR') == bool(y); cx = (X[i] == 'ERROR') == bool(y)
                fx += cx and not ca; br += ca and not cx
                per[i] = per.get(i, 0) + (cx - ca)
        rowwin = sum(v > 0 for v in per.values()); rowlose = sum(v < 0 for v in per.values())
        d.update(pooled_fixed=fx, pooled_broke=br, pooled_sign_p=round(sign_p(fx, br), 3),
                 row_better=rowwin, row_worse=rowlose, row_sign_p=round(sign_p(rowwin, rowlose), 3))
        a_rc = st.mean((R[f'A|all|run{k}'].get('reason_correct_tp') or 0) for k in runs)
        d['success_rule'] = bool(d['f1'] > res['A']['f1'] and d['reason_correct_tp'] >= a_rc and d['row_sign_p'] < 0.1)
    res[a] = d
json.dump(res, open(out_p, 'w'), indent=1)
for a, d in res.items():
    print(f"{a:16} F1 {d['f1']:.3f} [{d['f1_min']:.3f}-{d['f1_max']:.3f}] TP {d['tp']} FP {d['fp']} rcTP {d['reason_correct_tp']} DIFF {d['reason_diff']} calls {d['extra_calls_per_row']} ptok {d['prompt_tokens_per_row']:.0f}",
          '' if a == 'A' else f"pooled {d['pooled_fixed']}/{d['pooled_broke']} p={d['pooled_sign_p']} rows {d['row_better']}/{d['row_worse']} p={d['row_sign_p']} success={d['success_rule']}")
