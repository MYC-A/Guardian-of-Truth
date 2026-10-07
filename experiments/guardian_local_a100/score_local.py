"""Offline scorer for local runs (zero network).

python -m experiments.guardian_local_a100.score_local --backend vllm \
    --model-id '...' [--sets dev,devT,frozen,contrast,f120:dev,holdout2] [--json OUT] [--rows]

Decision rule actually scored per variant:
  A     -> binary_rfix (R_fix alone)          [read from AM runs]
  M     -> binary (R_fix + v6fix@403d811e)    [read from AM runs]
  B/T/E -> binary (same rule, different pre-pass)
  L     -> binary (R_fix + OLD v6fix@5330dcc4)
AM runs are scored twice (A and M) from the same saved primary replies —
mechanical postprocessing only, no extra model calls.

Tech rows (transport failure / unparseable pre-pass reply / failed record) are
counted separately, never as NO_ERROR. RU/EN split by Cyrillic share in the row
prompt. cause_auto: accusation target == gold target AND a gold cause marker in
the accusation text (where gold provides markers). Family breakdown where the
gold provides one. Calls/tokens per row from saved receipts (ledger = actual).
"""
import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

from experiments.research_records import load_records, expected_for_score, technical_gaps

ROOT = Path(__file__).resolve().parents[2]
OUTROOT = ROOT / 'outputs/guardian_local_a100'

SEM = ROOT / 'outputs/guardian_semantic/data'
ADD = ROOT / 'outputs/guardian_addons/data'
F120 = ROOT / 'outputs/guardian_v6_fix/frozen120'
HOLDOUT2 = ROOT / 'outputs/guardian_v6/holdout2'

CYR = re.compile(r'[А-Яа-яЁё]')


def gold_for(set_name):
    if set_name.startswith('f120'):
        g = json.loads((F120 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        split = set_name.split(':', 1)[1] if ':' in set_name else 'dev'
        return {k: v for k, v in g.items() if v.get('split') == split}
    if set_name == 'holdout2':
        g = json.loads((HOLDOUT2 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        return {k: dict(v, family=v.get('family') or v.get('domain'), cause_markers=[c for c in (v.get('causes') or [])][:1],
                        target_id=(v.get('cause_meta') or [{}])[0].get('target') or 't0') for k, v in g.items()}
    d = ADD if set_name == 'contrast' else SEM
    return json.loads((d / f'{set_name}_GOLD.json').read_text(encoding='utf-8'))


def lang_of(row):
    n = len(CYR.findall(row.get('prompt') or ''))
    return 'ru' if n > 40 else 'en'


def binary_pick(variant):
    return 'binary_rfix' if variant == 'A' else 'binary'


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
    ss, seen = steps(dict(a=r.get('pre_steps'), b=r.get('rec'), layers=r.get('layer_trace')), []), set()
    n = tok = 0
    for s in ss:
        if s['key'] in seen:
            continue
        seen.add(s['key'])
        n += 1
        u = s.get('usage') or {}
        tok += (u.get('prompt_tokens') or 0) + (u.get('completion_tokens') or 0)
    return n, tok


def cause_auto(r, g):
    acc = r.get('accusation') or {}
    txt = (acc.get('text') or '') + ' ' + (acc.get('fact') or '' if isinstance(acc.get('fact'), str) else json.dumps(acc.get('fact')))
    markers = g.get('cause_markers') or []
    return acc.get('target_id') == g.get('target_id') and bool(markers) and any(m in txt for m in markers)


def met(c):
    tp, fp, fn, tn = (c.get(x, 0) for x in ('tp', 'fp', 'fn', 'tn'))
    q = lambda a, b: round(a / b, 3) if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=q(tp, tp + fp), recall=q(tp, tp + fn),
                f1=q(2 * tp, 2 * tp + fp + fn), specificity=q(tn, tn + fp),
                cause_auto=c.get('cause', 0), technical=c.get('tech', 0))


def failed_row(r):
    from experiments.research_records import failed_record
    return r is None or failed_record(r) or technical_gaps(r) or any(
        x.get('parsed_ok') is False or ('parsed' in x and x['parsed'] is None) for x in (r.get('pre_steps') or []))


def inputs_lang(set_name):
    """id -> 'ru'/'en' from the set's inputs.jsonl (language is a property of the row, not the model output)."""
    src = {"contrast": ADD, "holdout2": HOLDOUT2}.get(set_name, F120 if set_name.startswith('f120') else SEM)
    fname = 'inputs.jsonl' if set_name.startswith('f120') or set_name == 'holdout2' else f'{set_name}_inputs.jsonl'
    try:
        out = {}
        for line in (src / fname).read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                out[r['id']] = lang_of(r)
        return out
    except FileNotFoundError:
        return {}


def score_set(set_name, runs_dir):
    gold = gold_for(set_name)
    res, rows_out = {}, []
    for p in sorted((runs_dir / set_name).glob('*_rep*.jsonl')):
        stem, rep = p.stem.rsplit('_rep', 1)
        expected = expected_for_score(p, gold)
        recs, record_coverage = load_records(p, expected)
        variants = ['A', 'M'] if stem == 'AM' else [stem]
        langs = inputs_lang(set_name)
        for var in variants:
            c, fam, lang, n, tok = Counter(), defaultdict(Counter), defaultdict(Counter), 0, 0
            pick = binary_pick(var)
            for i in expected:
                g, r = gold[i], recs.get(i)
                if r is None:
                    c['missing'] += 1
                    continue
                if failed_row(r):
                    c['tech'] += 1
                d = int(r.get(pick) or 0)
                o = ('tp' if d else 'fn') if g['label'] == 1 else ('fp' if d else 'tn')
                c[o] += 1
                fam[g.get('family') or '?'][o] += 1
                lang[langs.get(i, 'en')][o] += 1
                if o == 'tp' and cause_auto(r, g):
                    c['cause'] += 1
                    fam[g.get('family') or '?']['cause'] += 1
                k, t = cost(r)
                n += k
                tok += t
                rows_out.append(dict(set=set_name, variant=var, rep=int(rep), id=i, label=g['label'],
                                     family=g.get('family'), outcome=o, owner=r.get('owner' if var != 'A' else 'owner_rfix'),
                                     target=(r.get('accusation' if var != 'A' else 'accusation_rfix') or {}).get('target_id'),
                                     cause_auto=o == 'tp' and cause_auto(r, g),
                                     reason=(((r.get('accusation' if var != 'A' else 'accusation_rfix') or {}).get('text')) or '')[:400],
                                     calls=k, tokens=t))
            m = met(c)
            m.update(record_coverage=record_coverage, rows=len(recs), calls_per_row=round(n / max(1, len(recs)), 2),
                     tokens_per_row=round(tok / max(1, len(recs))), missing=c.get('missing', 0),
                     by_family={f: met(v) for f, v in sorted(fam.items())},
                     by_lang={l: met(v) for l, v in sorted(lang.items())})
            res[f'{var}_rep{rep}'] = m
    return res, rows_out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--backend', required=True, choices=('vllm', 'llamacpp'))
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--sets', default='dev,devT,frozen,contrast')
    ap.add_argument('--json')
    ap.add_argument('--rows', action='store_true')
    a = ap.parse_args()
    runs_dir = OUTROOT / a.backend / a.model_id.replace('/', '_') / 'runs'
    all_res, all_rows = {}, []
    for s in [x for x in a.sets.split(',') if x]:
        res, rows_out = score_set(s, runs_dir)
        if res:
            all_res[s] = res
            all_rows.extend(rows_out)
            for k, m in res.items():
                print(f"{s:12s} {k:10s} TP{m['tp']} FP{m['fp']} FN{m['fn']} TN{m['tn']} P={m['precision']} "
                      f"R={m['recall']} F1={m['f1']} cause={m['cause_auto']} tech={m['technical']} "
                      f"calls/row={m['calls_per_row']} tok/row={m['tokens_per_row']}")
    if a.json:
        p = Path(a.json)
        p.parent.mkdir(parents=True, exist_ok=True)
        with p.open('x', encoding='utf-8', newline='\n') as h:
            json.dump(dict(model=a.model_id, backend=a.backend, summary=all_res, rows=all_rows), h, ensure_ascii=False, indent=1)
    if a.rows:
        for r in all_rows:
            print(json.dumps(r, ensure_ascii=False))


if __name__ == '__main__':
    main()
