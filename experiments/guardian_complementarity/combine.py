"""Offline binary combinations for the complementarity study (no inference).
Usage (server, PYTHONPATH=src:.): python -m experiments.guardian_complementarity.combine --json out.json"""
import argparse, json, random
from pathlib import Path
from experiments.guardian_local_a100.score_local import gold_for, classify_row

ROOT = Path(__file__).resolve().parents[2]
LOC = ROOT / 'outputs/guardian_local_a100'
QW = LOC / 'llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs'
MI = LOC / 'vllm/ministral-3-14b-instruct-2512@29439f81c2be:bf16:vllm-0.31.0/runs'
GR = ROOT / 'outputs/research_granite_guardian'
HELD = ['lb_long', 'lb2_long', 'lb3_long', 'ext_tau2', 'hold_tau2h', 'hold_holdout2']


def runs(p, variant, pick='binary'):
    if not p.exists():
        return None
    out = {}
    for x in p.read_text(encoding='utf-8').splitlines():
        if x.strip():
            r = json.loads(x); out[r['id']] = dict(b=r.get(pick), cls=classify_row(r, variant, pick))
    return out


def granite(s):
    p = GR / f'compl_{s}/records.jsonl'
    if not p.exists():
        return None
    return {r['id']: dict(b=(1 if r.get('risk_token') == 'yes' else 0 if r.get('risk_token') == 'no' else None), cls=r.get('status'))
            for r in map(json.loads, p.read_text(encoding='utf-8').splitlines())}


def score(gold, pred):
    tp = fp = fn = tn = und = 0
    for i, y in gold.items():
        b = pred.get(i)
        if b is None:
            und += 1; continue
        if y and b: tp += 1
        elif y: fn += 1
        elif b: fp += 1
        else: tn += 1
    f1 = 2 * tp / (2 * tp + fp + fn) if tp else 0.0
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, undecided=und, f1=round(f1, 4))


def combos(sysd):
    out = {}
    for k, v in sysd.items():
        out[k] = {i: x['b'] for i, x in v.items()}
    def op(a, b, f):
        return {i: (None if out[a].get(i) is None or out[b].get(i) is None else int(f(out[a][i], out[b][i]))) for i in out[a]}
    if 'QB2' in out and 'GR' in out:
        out['QB2|GR'] = op('QB2', 'GR', lambda x, y: x or y); out['QB2&GR'] = op('QB2', 'GR', lambda x, y: x and y)
    if 'QB2' in out and 'QAM' in out:
        out['QB2|QAM'] = op('QB2', 'QAM', lambda x, y: x or y)
    if 'MB2' in out and 'GR' in out:
        out['MB2|GR'] = op('MB2', 'GR', lambda x, y: x or y)
    if 'QB2' in out and 'MB2' in out:
        out['QB2|MB2'] = op('QB2', 'MB2', lambda x, y: x or y)
    return out


def boot(gold, a, b, n=2000, seed=0):
    ids = [i for i in gold if a.get(i) is not None and b.get(i) is not None]
    rnd = random.Random(seed); d = []
    for _ in range(n):
        smp = [rnd.choice(ids) for _ in ids]
        g = {}; pa = {}; pb = {}
        for k, i in enumerate(smp):
            g[k] = gold[i]; pa[k] = a[i]; pb[k] = b[i]
        d.append(score(g, pb)['f1'] - score(g, pa)['f1'])
    d.sort()
    return [round(d[int(.025 * n)], 4), round(d[int(.975 * n)], 4)]


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--json'); ap.add_argument('--sets', default=','.join(HELD)); a = ap.parse_args()
    res = dict(sets={}, pooled={})
    pooled_gold, pooled = {}, {}
    for s in a.sets.split(','):
        gold = {i: g['label'] for i, g in gold_for(s).items() if g.get('label') in (0, 1)}
        sysd = {k: v for k, v in dict(QB2=runs(QW / s / 'B2_rep1.jsonl', 'B2'), QAM=runs(QW / s / 'AM_rep1.jsonl', 'A', 'binary_rfix'),
                                      MB2=runs(MI / s / 'B2_rep1.jsonl', 'B2'), GR=granite(s)).items() if v is not None}
        cls = {k: {c: sum(1 for i in gold if (v.get(i) or {}).get('cls', 'missing') == c) for c in ('verdict', 'fallback', 'no_solution', 'missing', 'ok')}
               for k, v in sysd.items()}
        c = combos(sysd)
        res['sets'][s] = dict(n=len(gold), pos=sum(gold.values()), scores={k: score(gold, v) for k, v in c.items()}, row_classes=cls)
        for k, v in c.items():
            pooled.setdefault(k, {}).update({f'{s}/{i}': v.get(i) for i in gold})
        pooled_gold.update({f'{s}/{i}': y for i, y in gold.items()})
    full = {k: v for k, v in pooled.items() if len(v) == len(pooled_gold)}
    res['pooled'] = {k: score(pooled_gold, v) for k, v in full.items()}
    if 'QB2' in full:
        res['delta_ci'] = {k: boot(pooled_gold, full['QB2'], full[k]) for k in full if k.startswith('QB2') and k != 'QB2'}
        res['flips'] = {k: dict(fn_to_tp=sorted(i for i in pooled_gold if pooled_gold[i] and not full['QB2'][i] and full[k][i]),
                                tn_to_fp=sorted(i for i in pooled_gold if not pooled_gold[i] and not full['QB2'][i] and full[k][i]),
                                tp_to_fn=sorted(i for i in pooled_gold if pooled_gold[i] and full['QB2'][i] and not full[k][i]))
                        for k in full if k.startswith('QB2') and k != 'QB2'}
    for s, v in res['sets'].items():
        print(s, v['n'], v['pos'], {k: (x['tp'], x['fp'], x['fn'], x['f1'], x['undecided']) for k, x in v['scores'].items()})
    print('POOLED', {k: (x['tp'], x['fp'], x['fn'], x['f1'], x['undecided']) for k, x in res['pooled'].items()})
    print('CI', res.get('delta_ci'))
    if a.json:
        Path(a.json).write_text(json.dumps(res, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
