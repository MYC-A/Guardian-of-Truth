"""Score the completed 24-case deferred comparison (assignment §3.4).

Merges the archived 18 triples (deferred_pilot/predictions.jsonl, rules and
gold v1 era) with the 6 new triples (deferred_completion/predictions.jsonl,
bank v2), rescores ALL 24 on the repaired gold v2 with the SAME frozen dual
rules (raw + UNKNOWN->correct-on-clean/miss-on-error mapping), and proves the
gold repair changed no label of any measured case (v1 vs v2 gold: only the
def_mixed::01 provenance fields differ; its label is unchanged and it was
unmeasured in the archived run).
"""
import json
from pathlib import Path

from modular_common import HERE, RESULTS, sha

BANK = HERE / 'dataset' / 'deferred_bank'
OLD = RESULTS / 'deferred_pilot'
NEW = RESULTS / 'deferred_completion'
FOLDER = RESULTS / 'deferred_completion'


def load_rows():
    old_rows = [json.loads(l) for l in (OLD / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    new_rows = [json.loads(l) for l in (NEW / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    return old_rows, new_rows


def decisions(rows):
    out = {}
    for r in rows:
        label = r.get('label')
        dec = 'UNKNOWN' if not r.get('valid') or label is None else ('ERROR' if label == 1 else 'NO_ERROR')
        out[(r['system'], r['id'])] = (dec, bool(r.get('valid')))
    return out


def metrics(system, decs, gold, ids):
    tp = fp = fn = tn = unk = 0
    for cid in ids:
        dec = decs.get((system, cid), ('MISSING', False))[0]
        g = gold[cid]
        if dec == 'UNKNOWN':
            unk += 1
        elif dec == 'ERROR' and g == 1:
            tp += 1
        elif dec == 'ERROR' and g == 0:
            fp += 1
        elif dec == 'NO_ERROR' and g == 1:
            fn += 1
        elif dec == 'NO_ERROR' and g == 0:
            tn += 1
        else:
            unk += 1  # MISSING rows keep their own status, never drop from the denominator
    p = tp / (tp + fp) if tp + fp else 0.0
    rc = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
    mtp, mfp, mfn, mtn = tp, fp, fn, tn
    for cid in ids:
        dec = decs.get((system, cid), ('MISSING', False))[0]
        g = gold[cid]
        if dec == 'UNKNOWN' or dec == 'MISSING':
            if g == 1:
                mfn += 1
            else:
                mtn += 1
    mp = mtp / (mtp + mfp) if mtp + mfp else 0.0
    mr = mtp / (mtp + mfn) if mtp + mfn else 0.0
    mf1 = 2 * mp * mr / (mp + mr) if mp + mr else 0.0
    return {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'UNKNOWN': unk,
            'P': round(p, 4), 'R': round(rc, 4), 'F1': round(f1, 4),
            'frozen_mapping': {'TP': mtp, 'FP': mfp, 'FN': mfn, 'TN': mtn,
                               'P': round(mp, 4), 'R': round(mr, 4), 'F1': round(mf1, 4),
                               'note': 'UNKNOWN/MISSING->correct-on-clean/miss-on-error (pre-frozen rule)'}}


def main():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    assert manifest.get('version') == 2
    gold = {r['id']: r['label'] for r in map(json.loads, (BANK / 'author_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    gold_v1 = {r['id']: r['label'] for r in map(json.loads, (BANK / 'author_gold_v1.jsonl').read_text(encoding='utf-8').splitlines())}
    assert gold == gold_v1, 'gold repair must not change any label'

    old_rows, new_rows = load_rows()
    all_ids = [json.loads(l)['id'] for l in (BANK / 'input.jsonl').read_text(encoding='utf-8').splitlines()]
    decs = decisions(old_rows + new_rows)
    systems = ['C0_J_control', 'D_V1_gptoss', 'D_V1_gemma']
    report = {
        'schema': 'deferred-completion-score/1',
        'rules': 'same frozen rules as deferred_pilot/selection.json (dual F1: raw | frozen mapping)',
        'bank': {'version': 2, 'gold_v2_sha256': manifest['gold_sha256'],
                 'gold_v1_preserved': 'author_gold_v1.jsonl',
                 'gold_repair': 'def_mixed::01 provenance only; labels identical v1 vs v2 (asserted)'},
        'measured_now': {'archived_triples': sorted({r['id'] for r in old_rows}),
                         'new_triples': sorted({r['id'] for r in new_rows})},
        'systems': {}, 'per_case': {}, 'new_case_details': {},
    }
    for system in systems:
        report['systems'][system] = metrics(system, decs, gold, all_ids)
    # paired transitions vs C0 on all 24
    for system in systems:
        if system == 'C0_J_control':
            continue
        moved = []
        for cid in all_ids:
            c0 = decs.get(('C0_J_control', cid), ('MISSING',))[0]
            d = decs.get((system, cid), ('MISSING',))[0]
            if c0 in ('ERROR', 'NO_ERROR') and d in ('ERROR', 'NO_ERROR') and c0 != d:
                moved.append({'id': cid, 'C0': c0, 'system': d, 'gold': gold[cid]})
        report['systems'][system]['transitions_vs_C0'] = moved
    for cid in all_ids:
        report['per_case'][cid] = {'gold': gold[cid], **{
            s: decs.get((s, cid), ('MISSING',))[0] for s in systems}}
    for r in new_rows:
        report['new_case_details'].setdefault(r['id'], {})[r['system']] = {
            'valid': r.get('valid'), 'reason': r.get('reason'),
            'label': r.get('label'),
            'vote_type': (r.get('vote') or {}).get('type'),
            'n_attempts': len(r.get('calls') or [])}
    out = FOLDER / 'score.json'
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    for system in systems:
        e = report['systems'][system]
        print(system, '->', {k: e[k] for k in ('TP', 'FP', 'FN', 'TN', 'UNKNOWN', 'F1')},
              '| frozen F1', e['frozen_mapping']['F1'], '| n=24')


if __name__ == '__main__':
    main()
