"""python -m experiments.guardian_fast.score_fast SET[,SET] [model_dir] -> confusion + cost per variant file."""
import glob, json, sys
from pathlib import Path
from experiments.guardian_local_a100.score_local import gold_for, steps, ROOT


def cost(r):
    sec = ctok = ptok = n = ps = pc = 0; seen = set()
    for s in steps(dict(a=r.get('pre_steps'), b=r.get('rec')), []):
        if s['key'] in seen: continue
        seen.add(s['key']); n += 1
        sc = (s.get('transport') or {}).get('seconds') or 0; u = s.get('usage') or {}
        sec += sc; ctok += u.get('completion_tokens') or 0; ptok += u.get('prompt_tokens') or 0
        if s.get('tag') == 'pre_blind': ps += sc; pc += u.get('completion_tokens') or 0
    return sec, ctok, ptok, n, ps, pc


def score(path, set_name, key='binary'):
    g = gold_for(set_name)
    tp = fp = fn = tn = bad = 0; S = C = N = PS = PC = 0; deliv = pre = 0
    for l in open(path):
        r = json.loads(l)
        if r['id'] not in g or g[r['id']].get('label') is None: continue
        y = int(g[r['id']]['label']); p = r.get(key)
        if r.get('error') or p is None: bad += 1; continue
        a, b, c, n, ps, pc = cost(r); S += a; C += b; N += n; PS += ps; PC += pc
        pp = [s for s in r.get('pre_steps') or [] if s.get('tag') == 'pre_blind']
        pre += bool(pp); deliv += any(s.get('injected') for s in pp)
        tp += y and p; fp += (not y) and p; fn += y and not p; tn += (not y) and not p
    n = max(tp + fp + fn + tn, 1)
    P = tp / (tp + fp) if tp + fp else 0; R = tp / (tp + fn) if tp + fn else 0
    return dict(n=tp + fp + fn + tn, TP=tp, FP=fp, FN=fn, TN=tn, F1=round(2 * P * R / (P + R) if P + R else 0, 3), bad=bad,
                sec_row=round(S / n, 1), ctok_row=round(C / n), calls_row=round(N / n, 2), pre_sec=round(PS / n, 1), pre_ctok=round(PC / n),
                pre=pre, deliv=deliv)


if __name__ == '__main__':
    md = sys.argv[2] if len(sys.argv) > 2 else 'ministral-14b-2512'
    for s in sys.argv[1].split(','):
        for p in sorted(glob.glob(str(ROOT / f'outputs/guardian_fast/{md}/runs/{s}/*.jsonl'))):
            print(s, Path(p).stem, score(p, s))
