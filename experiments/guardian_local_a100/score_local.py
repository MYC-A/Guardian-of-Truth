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

Decision accounting (offline re-classification of saved records; no inference):
  verdict      valid final decision through the variant's intended path:
               for B/B2/T/E the blind analysis was actually DELIVERED to the
               review request (created-but-not-delivered is NOT a delivered
               pre-pass); for M/L no layer/verification on the decision path
               was technically unavailable.
  fallback     valid decision via a degraded path: the review itself is valid
               but (a) the blind analysis was NOT delivered (a B variant row
               then behaves as plain AM on that row), or (b) the strict
               layers/verifications were technically unavailable so the model
               rule alone decided. Counted in TP/FP/FN/TN, reported separately.
  extra_pass   valid verdict while an optional additional pass (a layer
               finding or an in-review verification) did not execute.
  no_solution  no valid decision at all (review transport/parse failure,
               row exception, decision field absent). NEVER scored as
               NO_ERROR: excluded from the confusion matrix entirely.
  missing      row absent from the saved records.

TP/FP/FN/TN are computed over verdict+fallback rows (valid decisions);
'clean' repeats the confusion matrix over verdict-only rows.
RU/EN split by Cyrillic share in the row prompt. cause_auto: accusation
target == gold target AND a gold cause marker in the accusation text (where
gold provides markers). Family breakdown where the gold provides one.
Calls/tokens per row from saved receipts (ledger = actual).
"""
import argparse
import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

from experiments.research_records import load_records, expected_for_score, technical_gaps

ROOT = Path(__file__).resolve().parents[2]
OUTROOT = ROOT / 'outputs/guardian_local_a100'
DATA_ROOT = Path(os.environ.get('GUARDIAN_DATA_ROOT', '/workspace/guardian/data_root_403d811e'))

SEM = ROOT / 'outputs/guardian_semantic/data'
ADD = ROOT / 'outputs/guardian_addons/data'
F120 = ROOT / 'outputs/guardian_v6_fix/frozen120'
HOLDOUT2 = DATA_ROOT / 'outputs/guardian_v6/holdout2'
LB = {'lb_long': 'lockbox', 'lb2_long': 'lockbox2', 'lb3_long': 'lockbox3'}

CYR = re.compile(r'[А-Яа-яЁё]')
REVIEW_BAD = ('INVALID_JSON', 'INVALID_SCHEMA', 'TRANSPORT_FAILURE', 'NOT_EXECUTED')
MECH_LAYERS = ('F', 'S', 'P')


def gold_for(set_name):
    if set_name == 'valid46':
        import pandas as pd
        df = pd.read_parquet(DATA_ROOT / 'valid.parquet')
        return {r.id: dict(label=int(r.label), family=None,
                           cause_markers=([r.explanation] if isinstance(r.explanation, str) and r.explanation.strip() else []),
                           target_id=None) for r in df.itertuples()}
    if set_name in LB:
        g = json.loads((DATA_ROOT / 'outputs/verification_v2' / LB[set_name] / 'long/GOLD_eval_only.json').read_text(encoding='utf-8'))
        return {k: dict(v, family=v.get('family'), target_id=v.get('target') or 't0',
                        cause_markers=v.get('causes') or v.get('cause') or []) for k, v in g.items()}
    if set_name == 'ext_tau2':
        # tau2v2 gold (per PROMPT/universal_repair.score gold_for): 68 of 70 inputs have labels;
        # the 2 unlabelled rows are executed and counted in coverage, excluded from binary metrics only.
        g = json.loads((DATA_ROOT / 'outputs/verification_v4/external/tau2v2/GOLD_eval_only.json').read_text(encoding='utf-8'))
        return {k: dict(v, family=v.get('family'), target_id=v.get('target') or 't0',
                        cause_markers=v.get('causes') or v.get('cause') or []) for k, v in g.items()}
    if set_name == 'hold_tau2h':
        g = json.loads((DATA_ROOT / 'outputs/universal_repair/holdout/tau2h/GOLD_frozen.json').read_text(encoding='utf-8'))
        return {k: dict(v, family=v.get('family') or v.get('domain'),
                        cause_markers=[c for c in (v.get('causes') or [])][:1],
                        target_id=(v.get('cause_meta') or [{}])[0].get('target') or 't0') for k, v in g.items()}
    if set_name == 'hold_holdout2':
        g = json.loads((HOLDOUT2 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        return {k: dict(v, family=v.get('family') or v.get('domain'),
                        cause_markers=[c for c in (v.get('causes') or [])][:1],
                        target_id=(v.get('cause_meta') or [{}])[0].get('target') or 't0') for k, v in g.items()}
    if set_name.startswith('f120'):
        g = json.loads((F120 / 'GOLD_frozen.json').read_text(encoding='utf-8'))
        split = set_name.split(':', 1)[1] if ':' in set_name else 'dev'
        return {k: v for k, v in g.items() if v.get('split') == split}
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


# ---------------------------------------------------------------- decision accounting

def review_valid(r):
    """Primary review path executed and parseable -> its decision is usable."""
    if r is None or r.get('error'):
        return False
    rec_steps = ((r.get('rec') or {}).get('A') or {}).get('steps') or []
    if not rec_steps:
        return False
    for step in rec_steps:
        if step.get('admission') in REVIEW_BAD:
            return False
        validation = step.get('schema_validation') or {}
        if validation.get('status') in REVIEW_BAD:
            return False
        if step.get('parsed_ok') is False or ('parsed' in step and step['parsed'] is None):
            return False
        if step.get('raw_content') is None and str((step.get('transport') or {}).get('status')) != '200':
            return False
    return True


def prepass_info(r):
    """(has_pre, delivered): delivered only when the analysis was actually
    injected into the review request — a created-but-not-transmitted analysis
    does not count as a delivered blind pass."""
    pre_steps = [s for s in (r.get('pre_steps') or []) if str(s.get('tag', '')).startswith('pre_')]
    if not pre_steps:
        return False, False
    return True, any(s.get('injected') is True for s in pre_steps)


def _gaps(r, prefix):
    return [g for g in technical_gaps(r) if str(g.get('path', '')).startswith(prefix)]


def layer_gaps(r):
    return _gaps(r, '/layer_trace')


def review_gaps(r):
    return _gaps(r, '/rec')


def mechanical_owner(r):
    """The final binary came from a strict mechanical layer (F/S/P), not the model rule."""
    if r.get('owner') in MECH_LAYERS:
        return True
    return (r.get('accusation') or {}).get('certificate') == 'MECHANICAL'


def classify_row(r, variant, pick):
    """Mutually exclusive row class for the scored variant:
    missing / no_solution / fallback / verdict (see module docstring)."""
    if r is None:
        return 'missing'
    if not review_valid(r) or r.get(pick) is None:
        return 'no_solution'
    has_pre, delivered = prepass_info(r)
    if has_pre and not delivered:
        return 'fallback'
    lg, rg = bool(layer_gaps(r)), bool(review_gaps(r))
    if variant == 'A':
        return 'fallback' if rg else 'verdict'
    if (lg or rg) and not mechanical_owner(r):
        return 'fallback'
    return 'verdict'


def failed_row(r):
    """Back-compat boolean (old 'tech' definition) — kept for reference only."""
    from experiments.research_records import failed_record
    return r is None or failed_record(r) or technical_gaps(r) or any(
        x.get('parsed_ok') is False or ('parsed' in x and x['parsed'] is None) for x in (r.get('pre_steps') or []))


# ---------------------------------------------------------------- set language map

def inputs_lang(set_name):
    """id -> 'ru'/'en' from the set's inputs.jsonl (language is a property of the row, not the model output)."""
    if set_name == 'valid46':
        src, fname = DATA_ROOT, 'valid.parquet'
        try:
            import pandas as pd
            df = pd.read_parquet(DATA_ROOT / 'valid.parquet')
            return {r.id: lang_of(dict(prompt=r.prompt, response=r.response)) for r in df.itertuples()}
        except Exception:
            return {}
    if set_name in LB:
        src, fname = DATA_ROOT / 'outputs/verification_v2' / LB[set_name] / 'long', 'inputs.jsonl'
    elif set_name == 'ext_tau2':
        src, fname = DATA_ROOT / 'outputs/verification_v4/external/tau2', 'inputs.jsonl'
    elif set_name == 'hold_tau2h':
        src, fname = DATA_ROOT / 'outputs/universal_repair/holdout/tau2h', 'inputs.jsonl'
    elif set_name == 'hold_holdout2':
        src, fname = DATA_ROOT / 'outputs/guardian_v6/holdout2', 'inputs.jsonl'
    elif set_name.startswith('f120'):
        src, fname = F120, 'inputs.jsonl'
    else:
        src, fname = (ADD if set_name == 'contrast' else SEM), f'{set_name}_inputs.jsonl'
    try:
        out = {}
        for line in (src / fname).read_text(encoding='utf-8').splitlines():
            if line.strip():
                r = json.loads(line)
                out[r['id']] = lang_of(r)
        return out
    except FileNotFoundError:
        return {}


def met(c):
    tp, fp, fn, tn = (c.get(x, 0) for x in ('tp', 'fp', 'fn', 'tn'))
    q = lambda a, b: round(a / b, 3) if b else None
    return dict(tp=tp, fp=fp, fn=fn, tn=tn, precision=q(tp, tp + fp), recall=q(tp, tp + fn),
                f1=q(2 * tp, 2 * tp + fp + fn), specificity=q(tn, tn + fp),
                cause_auto=c.get('cause', 0),
                technical=c.get('fallback', 0) + c.get('extra_pass', 0) + c.get('no_solution', 0),
                n_verdict=c.get('verdict', 0), n_fallback=c.get('fallback', 0),
                n_extra_pass=c.get('extra_pass', 0), n_no_solution=c.get('no_solution', 0))


def _ratio(a, b):
    return round(a / b, 3) if b else None


def score_set(set_name, runs_dir):
    gold = gold_for(set_name)
    res, rows_out = {}, []
    for p in sorted((runs_dir / set_name).glob('*_rep*.jsonl')):
        stem, rep = p.stem.rsplit('_rep', 1)
        # Expected ids: the runner's .expected.json; the L (old-v6fix) script records
        # them in .phase.json['expected_ids']. ALL rows incl. unlabelled ext_tau2;
        # binary metrics use only ids present in gold, coverage counts everything.
        expected = None
        for mf, key in ((p.with_suffix('.expected.json'), None), (p.with_suffix('.phase.json'), 'expected_ids')):
            try:
                data = json.loads(mf.read_text(encoding='utf-8'))
                expected = data if key is None else data[key]
                break
            except Exception:
                continue
        if not expected:
            expected = sorted(gold)
        recs, record_coverage = load_records(p, expected)
        variants = ['A', 'M'] if stem == 'AM' else [stem]
        langs = inputs_lang(set_name)
        for var in variants:
            c, cc, fam, lang, n, tok = Counter(), Counter(), defaultdict(Counter), defaultdict(Counter), 0, 0
            pick = binary_pick(var)
            unlabelled = executed_unlabelled = 0
            cov = Counter()
            for i in expected:
                r = recs.get(i)
                cls = classify_row(r, var, pick)
                if cls == 'missing':
                    c['missing'] += 1
                    continue
                has_pre, delivered = prepass_info(r)
                if has_pre:
                    c['prepass'] += 1
                    c['prepass_delivered' if delivered else 'prepass_not_delivered'] += 1
                if i not in gold:
                    # executed but no binary gold (ext_tau2v2): coverage only
                    unlabelled += 1
                    cov[cls] += 1
                    if cls in ('verdict', 'fallback'):
                        executed_unlabelled += 1
                    continue
                g = gold[i]
                if cls == 'no_solution':
                    c['no_solution'] += 1
                    rows_out.append(dict(set=set_name, variant=var, rep=int(rep), id=i, label=g['label'],
                                         family=g.get('family'), outcome='no_solution', cls=cls,
                                         delivered=delivered if has_pre else None, calls=None, tokens=None))
                    continue
                d = int(r.get(pick) or 0)
                o = ('tp' if d else 'fn') if g['label'] == 1 else ('fp' if d else 'tn')
                c[o] += 1
                c[cls] += 1
                if cls == 'verdict':
                    cc[o] += 1
                if cls == 'verdict' and (layer_gaps(r) or review_gaps(r)):
                    c['extra_pass'] += 1
                fam[g.get('family') or '?'][o] += 1
                lang[langs.get(i, 'en')][o] += 1
                if o == 'tp' and cause_auto(r, g):
                    c['cause'] += 1
                    fam[g.get('family') or '?']['cause'] += 1
                k, t = cost(r)
                n += k
                tok += t
                rows_out.append(dict(set=set_name, variant=var, rep=int(rep), id=i, label=g['label'],
                                     family=g.get('family'), outcome=o, cls=cls, delivered=delivered if has_pre else None,
                                     owner=r.get('owner' if var != 'A' else 'owner_rfix'),
                                     target=(r.get('accusation' if var != 'A' else 'accusation_rfix') or {}).get('target_id'),
                                     cause_auto=o == 'tp' and cause_auto(r, g),
                                     reason=(((r.get('accusation' if var != 'A' else 'accusation_rfix') or {}).get('text')) or '')[:400],
                                     calls=k, tokens=t))
            m = met(c)
            m.update(record_coverage=record_coverage, rows=len(recs), calls_per_row=round(n / max(1, len(recs)), 2),
                     tokens_per_row=round(tok / max(1, len(recs))), missing=c.get('missing', 0),
                     executed_unlabelled=executed_unlabelled,
                     unlabelled_classes=dict(cov),
                     prepass_rows=c.get('prepass', 0), prepass_delivered=c.get('prepass_delivered', 0),
                     prepass_not_delivered=c.get('prepass_not_delivered', 0),
                     clean=dict(tp=cc['tp'], fp=cc['fp'], fn=cc['fn'], tn=cc['tn'],
                                precision=_ratio(cc['tp'], cc['tp'] + cc['fp']),
                                recall=_ratio(cc['tp'], cc['tp'] + cc['fn']),
                                f1=_ratio(2 * cc['tp'], 2 * cc['tp'] + cc['fp'] + cc['fn'])),
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
                      f"R={m['recall']} F1={m['f1']} cause={m['cause_auto']} "
                      f"verdict={m['n_verdict']} fallback={m['n_fallback']} extra={m['n_extra_pass']} "
                      f"nosol={m['n_no_solution']} miss={m['missing']} "
                      f"pre={m['prepass_rows']}(delivered {m['prepass_delivered']}/not {m['prepass_not_delivered']}) "
                      f"cleanF1={m['clean']['f1']} calls/row={m['calls_per_row']} tok/row={m['tokens_per_row']}")
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
