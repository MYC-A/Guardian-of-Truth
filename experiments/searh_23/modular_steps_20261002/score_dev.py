"""Separate DEV-only scorer. Never imported by inference or service code."""
import argparse
from collections import Counter, defaultdict
import random
import json
from pathlib import Path
from modular_common import HERE, RESULTS, source_sha, sha, write


def scoring_sources(root, split):
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / f'dataset/{split}_input.jsonl').read_bytes()
    if sha(blob) != manifest['splits'][split]['input_sha256']:
        raise ValueError('input_manifest_mismatch')
    inputs = {r['id']: r for r in map(json.loads, blob.decode().splitlines())}
    if split == 'sealed':
        # No gold is opened before the frozen-shortlist and prediction gates.
        frozen_path, receipt_path = root / 'shortlist_frozen.json', root / 'sealed_completion.json'
        if not frozen_path.exists() or not receipt_path.exists():
            raise ValueError('sealed_scoring_requires_frozen_shortlist_and_completion_receipt')
        frozen, receipt = (json.loads(p.read_text(encoding='utf-8')) for p in (frozen_path, receipt_path))
        if frozen.get('status') != 'FROZEN' or not 4 <= len(frozen.get('arms', [])) <= 6:
            raise ValueError('shortlist_not_frozen_or_wrong_size')
        if receipt.get('shortlist_sha256') != sha(frozen_path.read_bytes()) or receipt.get('input_sha256') != sha(blob):
            raise ValueError('completion_manifest_identity_mismatch')
        if receipt.get('state') != 'COMPLETED':
            raise ValueError('sealed_predictions_incomplete')
        for arm in frozen['arms']:
            key = arm['arm']
            prediction_path = (root / arm['predictions_file']).resolve()
            if root.resolve() not in prediction_path.parents:
                raise ValueError('predictions_outside_run_directory')
            if receipt['prediction_sha256'].get(key) != sha(prediction_path.read_bytes()):
                raise ValueError('prediction_hash_mismatch')
            rows = list(map(json.loads, prediction_path.read_text(encoding='utf-8').splitlines()))
            if len(rows) != len(inputs) or {r['id'] for r in rows} != set(inputs):
                raise ValueError('prediction_case_alignment_incomplete_or_duplicate')
            for row in rows:
                if row['source_sha256'] != source_sha(inputs[row['id']]):
                    raise ValueError('prediction_source_mismatch')
                if row.get('config_sha256') != arm['config_sha256']:
                    raise ValueError('prediction_config_mismatch')
    gold_blob = (HERE / f'dataset/{split}_gold.jsonl').read_bytes()
    if sha(gold_blob) != manifest['splits'][split]['gold_sha256']:
        raise ValueError('gold_manifest_mismatch')
    gold = {r['id']: r for r in map(json.loads, gold_blob.decode().splitlines())}
    return inputs, gold


def score(root, split='dev'):
    inputs, gold = scoring_sources(root, split)
    report = {'split': split, 'human_reviewed': False, 'arms': {}, 'natural_FN': [], 'explanation_accuracy': 'Separate atomic audit; labels do not establish explanation truth.'}
    if split == 'sealed':
        frozen = json.loads((root / 'shortlist_frozen.json').read_text(encoding='utf-8'))
        paths = [root / arm['predictions_file'] for arm in frozen['arms']]
    else:
        paths = list(root.glob('*/predictions.jsonl'))
    for path in paths:
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        grouped = defaultdict(list)
        for row in rows:
            grouped[row.get('arm', row.get('model', path.parent.name))].append(row)
        for arm, arm_rows in grouped.items():
            selection_path = path.parent / 'selection.json'
            selection = json.loads(selection_path.read_text(encoding='utf-8')) if selection_path.exists() else {}
            expected_ids = selection.get('ids')
            if path.parent.name == 'control_dev':
                expected_ids = json.loads((HERE / 'dataset/pilot_ids.json').read_text(encoding='utf-8'))
                if isinstance(expected_ids, dict):
                    expected_ids = expected_ids['ids']
            if split == 'sealed':
                expected_ids = list(inputs)
            scored = score_arm(arm_rows, inputs, gold, path, expected_ids)
            if scored['n']:
                key = path.parent.name if len(grouped) == 1 else path.parent.name + '/' + arm
                report['arms'][key] = scored
                report['natural_FN'].extend(scored.pop('natural_FN'))
    controls = report['arms'].get('control_dev', {}).get('per_case', [])
    base = {r['id']: r for r in controls}
    for arm, result in report['arms'].items():
        if arm == 'control_dev':
            continue
        pairs = [(r, base[r['id']]) for r in result['per_case'] if r['id'] in base]
        result['paired_vs_C0'] = {'n': len(pairs),
            'fixed': [r['id'] for r, b in pairs if r['binary_correct'] and not b['binary_correct']],
            'regressed': [r['id'] for r, b in pairs if b['binary_correct'] and not r['binary_correct']]}
    write(root / f'{split}_score.json', report)
    write(root / f'natural_FN_{split}.json', {'cases': report['natural_FN'], 'human_review_completed': False})
    print(json.dumps({k: {'n': v['n'], **v['counts']} for k, v in report['arms'].items()}))
    return report


def score_arm(rows, inputs, gold, path, expected_ids=None):
        counts, per_case, misses = Counter(), [], []
        for row in rows:
            if row['id'] not in gold:
                continue
            assert row['source_sha256'] == source_sha(inputs[row['id']])
            decision = row.get('decision') or row.get('output', {}).get('decision')
            if decision not in {'ERROR', 'NO_ERROR', 'UNKNOWN'}:
                continue
            g = gold[row['id']]
            if decision == 'UNKNOWN':
                counts['UNKNOWN'] += 1
                counts['UNKNOWN_error' if g['label'] else 'UNKNOWN_clean'] += 1
            key = ('TP' if g['label'] else 'FP') if decision == 'ERROR' else ('FN' if g['label'] else 'TN')
            counts[key] += 1
            correct = (decision == 'ERROR') == bool(g['label'])
            per_case.append({'id': row['id'], 'logical_group': g['logical_group'],
                             'label': g['label'], 'decision': decision, 'binary_correct': correct,
                             'determined_correct': correct and decision != 'UNKNOWN'})
            if g['label'] and decision == 'NO_ERROR':
                misses.append({'id': row['id'], 'arm': row.get('arm', path.parent.name),
                    'prediction_source': str(path), 'input': inputs[row['id']],
                    'author_gold': g, 'rechecked_gold': 'AUTHOR_SPEC_AND_SOURCE_AUDIT_NOT_HUMAN',
                    'prediction': row, 'status': 'NATURAL_MODEL_MISS_NOT_FAULT_INJECTION'})
        tp, fp, fn = (counts[k] for k in ('TP', 'FP', 'FN'))
        groups = defaultdict(list)
        for row in per_case:
            groups[row['logical_group']].append(row['binary_correct'])
        ci = None
        if len(groups) >= 2:
            rng = random.Random(1729)
            names = sorted(groups)
            boot = []
            for _ in range(1000):
                values = [v for name in rng.choices(names, k=len(names)) for v in groups[name]]
                boot.append(sum(values) / len(values))
            boot.sort()
            ci = [boot[25], boot[974]]
        selected = set(expected_ids or [r['id'] for r in rows if r['id'] in gold])
        seen = [r['id'] for r in rows if r['id'] in gold]
        if len(set(seen)) != len(seen):
            raise ValueError('duplicate_case_within_one_arm')
        if set(seen) - selected:
            raise ValueError('prediction_outside_frozen_selection')
        determined = [r for r in per_case if r['decision'] != 'UNKNOWN']
        return {'n': len(per_case), 'counts': dict(counts), 'per_case': per_case,
                'selected_n': len(selected), 'missing_predictions': sorted(selected - set(seen)),
                'journal_fraction': len(seen) / len(selected) if selected else None,
                'completion_fraction': len(per_case) / len(selected) if selected else None,
                'missing_final_decisions': sorted(selected - {r['id'] for r in per_case}),
                'determined_fraction_of_selected': len(determined) / len(selected) if selected else None,
                'determined_accuracy': sum(r['binary_correct'] for r in determined) / len(determined) if determined else None,
                'attempted_rows': len(rows), 'not_scored_no_decision': len(rows) - len(per_case),
                'precision': tp / (tp + fp) if tp + fp else None,
                'recall': tp / (tp + fn) if tp + fn else None,
                'binary_F1': 2 * tp / (2 * tp + fp + fn) if tp + fp + fn else None,
                'determined_coverage': (len(per_case) - counts['UNKNOWN']) / len(rows) if rows else None,
                'logical_group_count': len(groups), 'group_bootstrap_accuracy_CI95': ci,
                'natural_FN': misses}


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=RESULTS)
    p.add_argument('--split', choices=['dev', 'sealed'], default='dev')
    args = p.parse_args()
    score(args.root, args.split)
