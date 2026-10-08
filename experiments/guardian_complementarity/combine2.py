"""Phase g42+binding scorer (offline). Adds G42 (Granite 4.2 B2) and BIND (verified binding mismatch) to QB2.
Pools: dev (valid46, ext_tau2, hold_tau2h, hold_holdout2) and test (lb2_long, lb3_long, lb_long).
Each comparison is scored on rows where all systems involved are present (paired)."""
import argparse, json
from pathlib import Path
from experiments.guardian_complementarity.combine import runs, score, boot, QW, LOC, ROOT
from experiments.guardian_local_a100.score_local import gold_for

G42 = LOC / 'llamacpp/granite-4.2-30b@27b350a791e8:Q4_K_M:llamacpp-b11459/runs'
BD = ROOT / 'outputs/guardian_binding/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459'
POOLS = dict(dev=['valid46', 'ext_tau2', 'hold_tau2h', 'hold_holdout2'], test=['lb2_long', 'lb3_long', 'lb_long'])


def bind(s):
    p = BD / f'{s}.jsonl'
    if not p.exists():
        return {}
    out = {}
    for x in p.read_text(encoding='utf-8').splitlines():
        r = json.loads(x); out[r['id']] = dict(b=int(bool(r.get('verified'))), rec=r)
    return out


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--json'); a = ap.parse_args()
    res = {}
    for pool, sets in POOLS.items():
        gold, S = {}, {k: {} for k in ('QB2', 'G42', 'BIND')}
        for s in sets:
            g = {i: x['label'] for i, x in gold_for(s).items() if x.get('label') in (0, 1)}
            gold.update({f'{s}/{i}': y for i, y in g.items()})
            for k, v in (('QB2', runs(QW / s / 'B2_rep1.jsonl', 'B2')), ('G42', runs(G42 / s / 'B2_rep1.jsonl', 'B2')), ('BIND', bind(s))):
                for i, x in (v or {}).items():
                    if i in g and x['b'] is not None:
                        S[k][f'{s}/{i}'] = int(x['b'])
        arms = {'QB2|BIND': ('BIND', lambda q, o: q or o), 'G42': ('G42', lambda q, o: o),
                'QB2|G42': ('G42', lambda q, o: q or o), 'QB2&G42': ('G42', lambda q, o: q and o)}
        R = dict(n_gold=len(gold), n_qb2=len(S['QB2']), n_g42=len(S['G42']), n_bind=len(S['BIND']), arms={})
        for name, (other, f) in arms.items():
            ids = [i for i in gold if i in S['QB2'] and i in S[other]]
            if not ids:
                continue
            g = {i: gold[i] for i in ids}; q = {i: S['QB2'][i] for i in ids}; c = {i: int(f(q[i], S[other][i])) for i in ids}
            R['arms'][name] = dict(n=len(ids), QB2=score(g, q), arm=score(g, c), ci=boot(g, q, c),
                                   fn_to_tp=sorted(i for i in ids if g[i] and not q[i] and c[i]),
                                   tn_to_fp=sorted(i for i in ids if not g[i] and not q[i] and c[i]),
                                   tp_to_fn=sorted(i for i in ids if g[i] and q[i] and not c[i]))
        res[pool] = R
        print('==', pool, {k: v for k, v in R.items() if k != 'arms'})
        for k, v in R['arms'].items():
            f = lambda x: (x['tp'], x['fp'], x['fn'], x['f1'])
            print(f'  {k:9s} n={v["n"]} QB2={f(v["QB2"])} arm={f(v["arm"])} CI={v["ci"]} +TP={v["fn_to_tp"]} +FP={v["tn_to_fp"]} -TP={v["tp_to_fn"]}')
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
