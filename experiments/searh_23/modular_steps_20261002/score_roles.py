"""Unified scorer for the §8 role pilot (offline; gold opened post-run).

Binary mapping (frozen before any deferred comparison): label 1 -> ERROR,
label 0 -> NO_ERROR; INVALID/missing -> UNKNOWN which counts correct on
clean (no false alarm) and miss on error — reported separately everywhere.
References: archived C0 primary decisions and archived strict_always B
(mistral, official V0 contract) for paired transitions on the same cases.
"""
import hashlib
import json
from pathlib import Path

from modular_common import HERE, RESULTS

FOLDER = RESULTS / 'role_pilot'
R_NEG = RESULTS / 'negative_review_pilot_v4'
R_C0 = RESULTS / 'control_dev'


def _gold():
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / 'dataset/dev_gold.jsonl').read_bytes()
    assert hashlib.sha256(blob).hexdigest() == manifest['splits']['dev']['gold_sha256']
    return {r['id']: r['label'] for r in map(json.loads, blob.decode().splitlines())}


def _archived_references():
    """C0 primary decision + archived B (mistral V0) verdict per bank case."""
    c0 = {}
    p = R_C0 / 'predictions.jsonl'
    if p.exists():
        for line in p.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            out = r.get('output') or {}
            c0[r['id']] = out.get('decision')
    b_v0 = {}
    q = R_NEG / 'predictions.jsonl'
    if q.exists():
        for line in q.read_text(encoding='utf-8').splitlines():
            r = json.loads(line)
            if r.get('arm') == 'strict_always':
                b_v0[r['id']] = r.get('decision')
    return c0, b_v0


def binary(label, valid):
    if not valid or label is None:
        return 'UNKNOWN'
    return 'ERROR' if label == 1 else 'NO_ERROR'


def prf(tp, fp, fn, tn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'P': round(p, 4),
            'R': round(r, 4), 'F1': round(f1, 4)}


def main():
    gold = _gold()
    c0, b_v0 = _archived_references()
    rows = [json.loads(l) for l in (FOLDER / 'role_predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    systems = {}
    for r in rows:
        arm = r['arm']
        if arm.endswith('/E'):
            continue  # extraction stage: measured via proposal validity + downstream J
        vote = r.get('parsed')
        label = vote.get('label') if isinstance(vote, dict) else None
        dec = binary(label, r.get('valid'))
        d = systems.setdefault(arm, {'decisions': {}, 'valid': {}, 'calls': 0,
                                     'cached_calls': 0, 'tokens': 0, 'seconds': 0.0})
        d['decisions'][r['id']] = dec
        d['valid'][r['id']] = bool(r.get('valid'))
        for c in r.get('calls') or []:
            d['calls'] += 1
            d['cached_calls'] += 1 if c.get('cached') else 0
            d['tokens'] += int((c.get('usage') or {}).get('total_tokens') or 0)
            d['seconds'] += float(c.get('elapsed_s') or 0)
    report = {'schema': 'role-score/1', 'systems': {}, 'references': {
        'C0_primary_on_bank': {cid: c0.get(cid) for cid in gold if cid in systems.get(
            'D_V1_mistral', {}).get('decisions', {})},
        'B_mistral_V0_on_bank': {cid: b_v0.get(cid) for cid in gold if cid in systems.get(
            'D_V1_mistral', {}).get('decisions', {})}}}
    for arm, d in sorted(systems.items()):
        tp = fp = fn = tn = unk = 0
        for cid, dec in d['decisions'].items():
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
        entry = prf(tp, fp, fn, tn)
        entry.update({'UNKNOWN': unk, 'valid': sum(d['valid'].values()),
                      'n': len(d['decisions']),
                      'api_calls': d['calls'], 'cached': d['cached_calls'],
                      'tokens': d['tokens'], 'model_seconds': round(d['seconds'], 1)})
        # paired transitions vs archived references on the same cases
        trans = {'vs_C0_primary': [], 'vs_B_mistral_V0': []}
        for cid, dec in d['decisions'].items():
            if c0.get(cid):
                base = 'ERROR' if c0[cid] == 'ERROR' else 'NO_ERROR'
                if base != dec:
                    trans['vs_C0_primary'].append({'id': cid, 'C0': base, 'arm': dec,
                                                   'gold': gold[cid]})
            if b_v0.get(cid):
                base = b_v0[cid]
                if base != dec and base in ('ERROR', 'NO_ERROR'):
                    trans['vs_B_mistral_V0'].append({'id': cid, 'B_V0': base, 'arm': dec,
                                                     'gold': gold[cid]})
        entry['transitions'] = trans
        report['systems'][arm] = entry
    out = FOLDER / 'score.json'
    out.write_text(json.dumps(report, ensure_ascii=False, sort_keys=True, indent=2) + '\n', encoding='utf-8')
    for arm, e in report['systems'].items():
        print(arm, '->', {k: e[k] for k in ('TP', 'FP', 'FN', 'TN', 'UNKNOWN', 'F1', 'valid', 'n')})


if __name__ == '__main__':
    main()
