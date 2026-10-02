"""Score the §9.6 deferred comparison (gold opened post-run, rules frozen)."""
import json
from pathlib import Path

from modular_common import HERE, RESULTS

FOLDER = RESULTS / 'deferred_pilot'
BANK = HERE / 'dataset' / 'deferred_bank'


def main():
    manifest = json.loads((BANK / 'manifest.json').read_text(encoding='utf-8'))
    from modular_common import sha
    assert sha((BANK / 'author_gold.jsonl').read_bytes()) == manifest['gold_sha256']
    gold = {r['id']: r['label'] for r in map(json.loads, (BANK / 'author_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    rows = [json.loads(l) for l in (FOLDER / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    systems = {}
    for r in rows:
        label = r.get('label')
        dec = 'UNKNOWN' if not r.get('valid') or label is None else ('ERROR' if label == 1 else 'NO_ERROR')
        d = systems.setdefault(r['system'], {'dec': {}, 'valid': {}, 'tokens': 0, 'calls': 0, 'lat': []})
        d['dec'][r['id']] = dec
        d['valid'][r['id']] = bool(r.get('valid'))
        for c in r.get('calls') or []:
            d['calls'] += 1
            d['tokens'] += int((c.get('usage') or {}).get('total_tokens') or 0)
            d['lat'].append(float(c.get('elapsed_s') or 0))
    report = {'schema': 'deferred-score/1', 'rules': 'frozen in selection.json before results viewed',
              'systems': {}, 'per_case': {}}
    for system, d in sorted(systems.items()):
        tp = fp = fn = tn = unk = 0
        for cid, dec in d['dec'].items():
            g = gold[cid]
            if dec == 'UNKNOWN':
                unk += 1
            elif dec == 'ERROR' and g == 1:
                tp += 1
            elif dec == 'ERROR' and g == 0:
                fp += 1
            elif dec == 'NO_ERROR' and g == 1:
                fn += 1
            else:
                tn += 1
        p = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * p * rc / (p + rc) if p + rc else 0.0
        # frozen binary mapping (auditor R-201 dual report): UNKNOWN counts
        # correct-on-clean / miss-on-error — the rule frozen pre-comparison
        mtp = mfp = mfn = mtn = 0
        for cid, dec in d['dec'].items():
            g = gold[cid]
            if dec == 'ERROR' and g == 1:
                mtp += 1
            elif dec == 'ERROR' and g == 0:
                mfp += 1
            elif dec == 'NO_ERROR' and g == 1:
                mfn += 1
            elif dec == 'NO_ERROR' and g == 0:
                mtn += 1
            elif g == 1:
                mfn += 1
            else:
                mtn += 1
        mp = mtp / (mtp + mfp) if mtp + mfp else 0.0
        mr = mtp / (mtp + mfn) if mtp + mfn else 0.0
        mf1 = 2 * mp * mr / (mp + mr) if mp + mr else 0.0
        report['systems'][system] = {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'UNKNOWN': unk,
                                     'P': round(p, 4), 'R': round(rc, 4), 'F1': round(f1, 4),
                                     'frozen_mapping': {'TP': mtp, 'FP': mfp, 'FN': mfn, 'TN': mtn,
                                                        'P': round(mp, 4), 'R': round(mr, 4),
                                                        'F1': round(mf1, 4),
                                                        'note': 'UNKNOWN->correct-on-clean/miss-on-error (pre-frozen rule)'},
                                     'n': len(d['dec']), 'api_calls': d['calls'],
                                     'tokens': d['tokens'],
                                     'median_latency_s': round(sorted(d['lat'])[len(d['lat']) // 2], 2) if d['lat'] else None}
    # paired transitions vs C0_J_control
    c0 = systems.get('C0_J_control', {}).get('dec', {})
    for system, d in systems.items():
        if system == 'C0_J_control':
            continue
        moved = []
        for cid, dec in d['dec'].items():
            if cid in c0 and c0[cid] in ('ERROR', 'NO_ERROR') and c0[cid] != dec:
                moved.append({'id': cid, 'C0': c0[cid], 'system': dec, 'gold': gold[cid]})
        report['systems'][system]['transitions_vs_C0'] = moved
    for cid in gold:
        report['per_case'][cid] = {'gold': gold[cid], **{
            s: d['dec'].get(cid) for s, d in systems.items()}}
    out = FOLDER / 'score.json'
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    for system, e in report['systems'].items():
        print(system, '->', {k: e[k] for k in ('TP', 'FP', 'FN', 'TN', 'UNKNOWN', 'F1', 'n')})


if __name__ == '__main__':
    main()
