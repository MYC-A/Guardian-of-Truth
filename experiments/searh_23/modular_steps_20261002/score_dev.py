"""Separate DEV-only scorer. Never imported by inference or service code."""
import argparse
from collections import Counter
import json
from pathlib import Path
from modular_common import HERE, RESULTS, source_sha, write


def score(root):
    gold = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines())}
    inputs = {r['id']: r for r in map(json.loads, (HERE / 'dataset/dev_input.jsonl').read_text(encoding='utf-8').splitlines())}
    report = {'split': 'dev', 'human_reviewed': False, 'arms': {}, 'natural_FN': [], 'explanation_accuracy': 'Separate atomic audit; labels do not establish explanation truth.'}
    for path in root.glob('*/predictions.jsonl'):
        rows = [json.loads(s) for s in path.read_text(encoding='utf-8').splitlines()]
        counts = Counter()
        per_case = []
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
                report['natural_FN'].append({'id': row['id'], 'arm': path.parent.name,
                    'prediction_source': str(path), 'input': inputs[row['id']],
                    'author_gold': g, 'rechecked_gold': 'AUTHOR_SPEC_AND_SOURCE_AUDIT_NOT_HUMAN',
                    'prediction': row, 'status': 'NATURAL_MODEL_MISS_NOT_FAULT_INJECTION'})
        if per_case:
            report['arms'][path.parent.name] = {'n': len(per_case), 'counts': dict(counts), 'per_case': per_case}
    write(root / 'dev_score.json', report)
    write(root / 'natural_FN_dev.json', {'cases': report['natural_FN'], 'human_review_completed': False})
    print(json.dumps({k: {'n': v['n'], **v['counts']} for k, v in report['arms'].items()}))
    return report


if __name__ == '__main__':
    p = argparse.ArgumentParser()
    p.add_argument('--root', type=Path, default=RESULTS)
    score(p.parse_args().root)
