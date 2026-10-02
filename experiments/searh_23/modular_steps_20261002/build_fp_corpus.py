"""Assemble the false-positive analysis corpus (assignment §5).

Extracts, for close reading, every temporal-pilot FP and every routing-pilot
FP (strict_always arm) with the full original prompt/response, the gold basis
(requirement, policy span, reason, evidence spans) and the COMPLETE saved B
answer. Output: results/.../fp_corpus/{routing_fp,temporal_fp}.jsonl.
Read-only over frozen datasets and journals; gold is opened post-run exactly
like the frozen scorers do.
"""
import json
from pathlib import Path

from modular_common import HERE, RESULTS, sha

R = RESULTS / 'negative_review_pilot_v4'
T = RESULTS / 'temporal_assistant_pilot'
OUT = RESULTS / 'fp_corpus'
OUT.mkdir(parents=True, exist_ok=True)


def gold_map(split='dev'):
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / f'dataset/{split}_gold.jsonl').read_bytes() if split == 'dev' else \
        (HERE / f'dataset/{split}/author_gold.jsonl').read_bytes()
    if split == 'dev' and sha(blob) != manifest['splits']['dev']['gold_sha256']:
        raise ValueError('dev_gold_identity_mismatch')
    return {r['id']: r for r in map(json.loads, blob.decode().splitlines())}


def input_map(split='dev'):
    if split == 'dev':
        rows = [json.loads(s) for s in (HERE / 'dataset/dev_input.jsonl').read_text(encoding='utf-8').splitlines()]
    else:
        rows = [json.loads(s) for s in (HERE / f'dataset/{split}/input.jsonl').read_text(encoding='utf-8').splitlines()]
    return {r['id']: r for r in rows}


def gold_basis(g):
    keep = ('label', 'expected_decision', 'requirement', 'reason', 'required_evidence',
            'policy_span', 'target_span', 'history_evidence_spans', 'logical_group',
            'human_review_status', 'boundary_note', 'provenance')
    return {k: g[k] for k in keep if k in g}


def routing_fp():
    gold = gold_map('dev')
    inputs = input_map('dev')
    preds = [json.loads(l) for l in (R / 'predictions.jsonl').read_text().splitlines()]
    raw_b = {r['id']: r for r in map(json.loads, (R / 'raw_B_calls.jsonl').read_text().splitlines())}
    rows = []
    for p in preds:
        if p['arm'] != 'strict_always':
            continue
        g = gold[p['id']]
        if g['label'] != 0 or p['decision'] != 'ERROR':
            continue
        row = inputs[p['id']]
        b = raw_b.get(p['id'], {})
        rows.append({
            'corpus': 'routing', 'id': p['id'], 'source_sha256': p['source_sha256'],
            'primary_decision': p['primary_decision'], 'B_used': p['B_used'],
            'B_reason': p.get('reason'), 'findings': p.get('findings'),
            'B_model': b.get('model'),
            'B_raw_content': (b.get('raw') or {}).get('content'),
            'gold_basis': gold_basis(g),
            'prompt': row['prompt'], 'response': row['response'],
        })
    return rows


def temporal_fp():
    gold = gold_map('temporal_boundary')
    inputs = input_map('temporal_boundary')
    # temporal bank also includes 8 dev_inclusive_timezone cases: gold from dev
    dev_gold = gold_map('dev')
    dev_inputs = input_map('dev')
    for i in range(8):
        cid = f'dev_inclusive_timezone::{i:02d}'
        if cid not in gold and cid in dev_gold:
            gold[cid] = dev_gold[cid]
            inputs[cid] = dev_inputs[cid]
    preds = [json.loads(l) for l in (T / 'predictions.jsonl').read_text().splitlines()]
    raw_b = {}
    for r in map(json.loads, (T / 'raw_B_calls.jsonl').read_text().splitlines()):
        raw_b[(r['id'], r.get('stage'))] = r
    # without-arm rows reused by 4 dev_inclusive_timezone cases come from the
    # routing pilot's archived shared_B: their raw content lives there.
    routing_raw = {r['id']: r for r in map(json.loads, (R / 'raw_B_calls.jsonl').read_text().splitlines())}
    shared_review = {r['id']: r for r in map(json.loads, (R / 'shared_B.jsonl').read_text().splitlines())}
    rows = []
    seen_without = set()
    for p in preds:
        if p['arm'] != 'B_without_calc':
            continue
        g = gold.get(p['id'])
        if g is None or g['label'] != 0 or p['decision'] != 'ERROR':
            continue
        seen_without.add(p['id'])
        row = inputs[p['id']]
        with_p = next((q for q in preds if q['arm'] == 'B_with_calc' and q['id'] == p['id']), None)
        # raw rows are keyed by runner stage names: B_without_calc / B_with_calc;
        # reused without-rows fall back to the routing pilot's archived call
        cand_wo = [v for (i2, st), v in raw_b.items() if i2 == p['id'] and st == 'B_without_calc']
        cand_with = [v for (i2, st), v in raw_b.items() if i2 == p['id'] and st == 'B_with_calc']
        raw_wo = ((cand_wo[0].get('raw') or {}).get('content') if cand_wo else None) or \
                 ((routing_raw.get(p['id'], {}).get('raw') or {}).get('content')) or \
                 ((shared_review.get(p['id'], {}).get('review') or {}).get('raw_content'))
        rows.append({
            'corpus': 'temporal', 'id': p['id'], 'source_sha256': p['source_sha256'],
            'primary_decision': p['primary_decision'],
            'B_reason_without': p.get('B_reason'), 'B_reason_with': (with_p or {}).get('B_reason'),
            'B_raw_without': raw_wo,
            'B_raw_with': ((cand_with[0].get('raw') or {}).get('content') if cand_with else None),
            'module_advisory_sha256': p.get('module_advisory_sha256'),
            'gold_basis': gold_basis(g),
            'prompt': row['prompt'], 'response': row['response'],
        })
    return rows


if __name__ == '__main__':
    routing = routing_fp()
    temporal = temporal_fp()
    overlap = sorted({r['id'] for r in routing} & {r['id'] for r in temporal})
    (OUT / 'routing_fp.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in routing) + '\n', encoding='utf-8')
    (OUT / 'temporal_fp.jsonl').write_text(
        '\n'.join(json.dumps(r, ensure_ascii=False) for r in temporal) + '\n', encoding='utf-8')
    print(json.dumps({'routing_fp': len(routing), 'temporal_fp': len(temporal),
                      'overlap_ids': overlap,
                      'routing_ids': [r['id'] for r in routing],
                      'temporal_ids': [r['id'] for r in temporal]}, ensure_ascii=False))
