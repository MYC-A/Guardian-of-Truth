"""Post-run scorer for the long-bank pilot (§7.F). Gold opened here only."""
import json
from collections import Counter, defaultdict
from modular_common import HERE, RESULTS, write

FOLDER = RESULTS / 'long_bank_pilot'


def gold_map():
    gold = {}
    for line in (HERE / 'dataset/long_context_v2/author_gold.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        gold[r['id']] = r
    return gold


def main():
    rows = [json.loads(l) for l in (FOLDER / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold = gold_map()
    per_case, by_slice = {}, defaultdict(Counter)
    overall = Counter()
    for r in rows:
        g = gold[r['id']]
        label = int(g['author_label'])
        decision = r['decision']
        if decision == 'ERROR':
            cell = 'TP' if label == 1 else 'FP'
        elif decision == 'NO_ERROR':
            cell = 'FN' if label == 1 else 'TN'
        else:
            cell = 'TN' if label == 0 else 'FN'
            overall['UNKNOWN'] += 1
        overall[cell] += 1
        family, size, position, tail = r['id'].split('_')[2], int(r['id'].split('_')[3]), r['id'].split('_')[4], r['id'].split('_')[5]
        by_slice[f'size/{size}'][cell] += 1
        by_slice[f'position/{position}'][cell] += 1
        by_slice[f'family/{family}'][cell] += 1
        per_case[r['id']] = {'label': label, 'decision': decision, 'cell': cell,
                             'degraded': r.get('degraded'), 'unknown_reasons': r.get('unknown_reasons'),
                             'policy_relative_position': g['policy_relative_position'],
                             'observation_relative_position': g['observation_relative_position'],
                             'competing_observations': g['competing_observations'],
                             'usage': r.get('usage')}
    tp, fp, fn, tn = (overall[k] for k in ('TP', 'FP', 'FN', 'TN'))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    analysis = {'schema': 'long-bank-scoring/1',
        'gold_opened_after': 'run rows journaled',
        'binary_mapping': 'UNKNOWN counts correct on clean, miss on error',
        'layout_caveat': 'ARTIFICIAL two-SYSTEM-message stress layout, explicitly not the contest single-system format',
        'n': len(rows), 'per_case': per_case,
        'overall': {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'UNKNOWN': overall.get('UNKNOWN', 0),
                    'precision': prec, 'recall': rec,
                    'F1': (2 * prec * rec / (prec + rec)) if prec and rec else None},
        'slices': {k: dict(v) for k, v in by_slice.items()},
        'operational_smoke_12001': 'existing service_long_v2 receipts; not re-run here',
        'limits': ['Author gold, constructed stress layout; no leaderboard claim.',
                   '12 cases with correlated construction; CIs required.',
                   'Position/family slices have 2-6 cases each: directional only.']}
    write(FOLDER / 'analysis.json', analysis)
    print(json.dumps({'overall': analysis['overall'], 'slices': analysis['slices']}, indent=1)[:1800])


if __name__ == '__main__':
    main()
