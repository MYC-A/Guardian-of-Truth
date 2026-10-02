"""Separate DEV-only scorer. Never imported by inference or service code."""
import argparse
from collections import Counter, defaultdict
import random
import json
from pathlib import Path
from modular_common import HERE, RESULTS, source_sha, write


def score(root):
    gold = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    inputs = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_input.jsonl').read_text(encoding='utf-8').splitlines())}
    report = {'split': 'dev', 'human_reviewed': False, 'arms': {}, 'natural_FN': [], 'explanation_accuracy': 'Separate atomic audit; labels do not establish explanation truth.'}
    for path in root.glob('*/predictions.jsonl'):
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        grouped = defaultdict(list)
        for row in rows:
            grouped[row.get('arm', path.parent.name)].append(row)
        for arm, arm_rows in grouped.items():
            scored = score_arm(arm_rows, inputs, gold, path)
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
    write(root / 'dev_score.json', report)
    write(root / 'natural_FN_dev.json', {'cases': report['natural_FN'], 'human_review_completed': False})
    print(json.dumps({k: {'n': v['n'], **v['counts']} for k, v in report['arms'].items()}))
    return report


def score_arm(rows, inputs, gold, path):
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
        return {'n': len(per_case), 'counts': dict(counts), 'per_case': per_case,
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
    score(p.parse_args().root)
