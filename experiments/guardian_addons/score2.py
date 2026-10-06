"""Offline scoring (zero network): python -m experiments.guardian_addons.score2 [--set dev] [--json OUT] [--rows]
Per variant x rep: TP/FP/FN/TN, precision/recall/F1 (binary = final v6fix decision), per family; cause_auto = TP whose
accusation target equals the gold target AND whose text contains one gold cause marker (manual self-review is separate,
REPORT.md); method calls/tokens per row from the saved steps (cached replays included, ledger = actual spend)."""
import argparse, json
from collections import Counter, defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / 'outputs/guardian_addons'
from .run2 import data_dir, failed_rec


def steps(o, acc):
    if isinstance(o, dict):
        if isinstance(o.get('key'), str) and 'usage' in o and ('raw_content' in o or 'content' in o or 'tag' in o):
            acc.append(o)
        for v in o.values():
            steps(v, acc)
    elif isinstance(o, list):
        for v in o:
            steps(v, acc)
    return acc


def cost(r):
    ss, seen = steps(dict(a=r.get('pre_steps'), b=r.get('rec')), []), set()
    n = tok = 0
    for s in ss:
        if s['key'] in seen:
            continue
        seen.add(s['key']); n += 1
        u = s.get('usage') or {}
        tok += (u.get('prompt_tokens') or 0) + (u.get('completion_tokens') or 0)
    return n, tok


def cause_auto(r, g):
    acc = r.get('accusation') or {}
    txt = (acc.get('text') or '') + ' ' + (acc.get('fact') or '' if isinstance(acc.get('fact'), str) else json.dumps(acc.get('fact')))
    return acc.get('target_id') == g['target_id'] and any(m in txt for m in g['cause_markers'])


def met(c):
    tp, fp, fn, tn = (c.get(x, 0) for x in ('tp', 'fp', 'fn', 'tn'))
    q = lambda a, b: round(a / b, 3) if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=q(tp, tp + fp), recall=q(tp, tp + fn), f1=q(2 * tp, 2 * tp + fp + fn),
                cause_auto=c.get('cause', 0), technical=c.get('tech', 0))


def score(s):
    gold = json.loads((data_dir(s) / f'{s}_GOLD.json').read_text(encoding='utf-8'))
    res, rows = {}, []
    for p in sorted((OUT / 'runs' / s).glob('*_rep*.jsonl')):
        var, rep = p.stem.rsplit('_rep', 1)
        recs = {}
        for x in p.read_text(encoding='utf-8').splitlines():
            r = json.loads(x); recs[r['id']] = r              # last record of a row wins (resume)
        c, fam, n, tok = Counter(), defaultdict(Counter), 0, 0
        for i, g in gold.items():
            r = recs.get(i)
            if r is None:
                c['missing'] += 1; continue
            if failed_rec(r) or any(x.get('parsed_ok') is False or ('parsed' in x and x['parsed'] is None) for x in r.get('pre_steps') or []):
                c['tech'] += 1          # transport failure, or a pre-pass reply that could not be parsed (e.g. finish_reason=length)
            d = int(r.get('binary') or 0)
            o = ('tp' if d else 'fn') if g['label'] == 1 else ('fp' if d else 'tn')
            c[o] += 1; fam[g['family']][o] += 1
            if o == 'tp' and cause_auto(r, g):
                c['cause'] += 1; fam[g['family']]['cause'] += 1
            k, t = cost(r); n += k; tok += t
            rows.append(dict(set=s, variant=var, rep=int(rep), id=i, label=g['label'], family=g['family'], outcome=o, owner=r.get('owner'),
                             target=(r.get('accusation') or {}).get('target_id'), cause_auto=o == 'tp' and cause_auto(r, g),
                             reason=((r.get('accusation') or {}).get('text') or '')[:400], calls=k, tokens=t,
                             executions=r.get('executions'), pre=[dict(tag=x['tag'], injected=x.get('injected'),
                             status=(x.get('receipt') or {}).get('status'), eval_changed=x.get('eval_changed'),
                             checks=[(c['consistency'], c['computation']) for c in x.get('code_checks') or []]) for x in r.get('pre_steps') or []]))
        m = met(c); m.update(rows=len(recs), calls_per_row=round(n / max(1, len(recs)), 2), tokens_per_row=round(tok / max(1, len(recs))),
                             missing=c.get('missing', 0), by_family={f: met(v) for f, v in sorted(fam.items())})
        res[f'{var}_rep{rep}'] = m
    return res, rows


def main():
    ap = argparse.ArgumentParser(); ap.add_argument('--set', default='dev'); ap.add_argument('--json'); ap.add_argument('--rows', action='store_true')
    a = ap.parse_args()
    res, rows = score(a.set)
    for k, m in res.items():
        print(f"{k:12s} TP{m['tp']} FP{m['fp']} FN{m['fn']} TN{m['tn']} P={m['precision']} R={m['recall']} F1={m['f1']} cause={m['cause_auto']} "
              f"tech={m['technical']} calls/row={m['calls_per_row']} tok/row={m['tokens_per_row']} | " +
              ' '.join(f"{f}:{v['tp']}/{v['fp']}/{v['fn']}/{v['tn']}" for f, v in m['by_family'].items()))
    if a.rows:
        for r in rows:
            print(json.dumps(r, ensure_ascii=False))
    if a.json:
        Path(a.json).write_text(json.dumps(dict(summary=res, rows=rows), ensure_ascii=False, indent=1), encoding='utf-8')


if __name__ == '__main__':
    main()
