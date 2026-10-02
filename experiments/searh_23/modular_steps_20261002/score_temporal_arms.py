"""Post-run scorer for the temporal-calculation assistant pilot.

Gold is opened here only, after the run COMPLETED and every prediction row
was journaled (selection.json records that discipline). UNKNOWN counts
correct on clean (no false alarm) and a miss on error, mirroring
score_negative_arms.py; determined accuracy is reported separately.
"""
import json
from collections import Counter
from modular_common import HERE, RESULTS, sha, write

FOLDER = RESULTS / 'temporal_assistant_pilot'
ARMS = ('B_without_calc', 'B_with_calc')


def gold_map():
    gold = {}
    for line in (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        if row['id'].startswith('dev_inclusive_timezone::'):
            gold[row['id']] = row['label']
    for line in (HERE / 'dataset/temporal_boundary/author_gold.jsonl').read_text(encoding='utf-8').splitlines():
        row = json.loads(line)
        gold[row['id']] = row['label']
    return gold


def confusion(pairs):
    # binary mapping: UNKNOWN correct on clean, miss on error
    counts = Counter()
    for label, decision in pairs:
        if decision == 'ERROR':
            counts['TP' if label == 1 else 'FP'] += 1
        elif decision == 'NO_ERROR':
            counts['FN' if label == 1 else 'TN'] += 1
        else:
            counts['TN' if label == 0 else 'FN'] += 1
            counts['UNKNOWN'] += 1
    tp, fp, fn, tn = (counts[k] for k in ('TP', 'FP', 'FN', 'TN'))
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    f1 = 2 * prec * rec / (prec + rec) if prec and rec else None
    determined_pairs = [(l, d) for l, d in pairs if d != 'UNKNOWN']
    n_determined = len(determined_pairs)
    acc = (sum(1 for l, d in determined_pairs if (1 if d == 'ERROR' else 0) == l) / n_determined) if n_determined else None
    return {'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'UNKNOWN': counts.get('UNKNOWN', 0),
            'precision': prec, 'recall': rec, 'F1': f1,
            'determined_accuracy': acc, 'determined_n': n_determined}


def main():
    status = json.loads((FOLDER / 'status.json').read_text(encoding='utf-8'))
    rows = [json.loads(l) for l in (FOLDER / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold = gold_map()
    by_arm = {arm: {} for arm in ARMS}
    for r in rows:
        by_arm[r['arm']][r['id']] = r
    bank = sorted(gold)
    analysis = {'schema': 'temporal-assistant-scoring/1',
        'gold_opened_after': 'run COMPLETED and all prediction rows journaled',
        'status_state': status.get('state'), 'bank_n': len(bank),
        'binary_mapping': 'UNKNOWN counts correct on clean (no false alarm), miss on error; determined accuracy separate',
        'missing_rows': {arm: [i for i in bank if i not in by_arm[arm]] for arm in ARMS},
        'invalid_B': {arm: [i for i in bank if i in by_arm[arm] and not by_arm[arm][i]['B_valid']] for arm in ARMS},
        'primary_vote': {i: by_arm[ARMS[0]][i]['primary_decision'] for i in bank if i in by_arm[ARMS[0]]}}
    analysis['arms'] = {}
    for arm in ARMS:
        pairs = [(gold[i], by_arm[arm][i]['decision']) for i in bank if i in by_arm[arm]]
        analysis['arms'][arm] = confusion(pairs)
        analysis['arms'][arm]['cost'] = {
            k: sum(r['cost'].get(k, 0) for r in by_arm[arm].values() if isinstance(r.get('cost'), dict))
            for k in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}
        analysis['arms'][arm]['reused_B_rows'] = sum(1 for r in by_arm[arm].values() if r['cost'].get('reused_from'))
    # paired transitions without -> with
    transitions = {}
    for i in bank:
        if i in by_arm[ARMS[0]] and i in by_arm[ARMS[1]]:
            a, b = by_arm[ARMS[0]][i]['decision'], by_arm[ARMS[1]][i]['decision']
            if a == b:
                kind = 'unchanged'
            elif b == 'ERROR':
                kind = 'fixed_FN' if gold[i] == 1 else 'new_FP'
            elif a == 'ERROR':
                kind = 'lost_TP' if gold[i] == 1 else 'fp_removed'
            else:
                kind = 'other_drift'
            transitions[i] = {'without': a, 'with': b, 'gold': gold[i], 'transition': kind,
                              'B_valid_drift': by_arm[ARMS[0]][i]['B_valid'] != by_arm[ARMS[1]][i]['B_valid'],
                              'B_additional_error_with': by_arm[ARMS[1]][i].get('B_additional_error'),
                              'B_additional_error_without': by_arm[ARMS[0]][i].get('B_additional_error')}
    analysis['paired_transitions'] = transitions
    analysis['transition_counts'] = Counter(t['transition'] for t in transitions.values())
    analysis['known_FN_repair_check'] = {
        'dev_inclusive_timezone::02': transitions.get('dev_inclusive_timezone::02'),
        'note': 'a B-review inclusion is not a repair: only a valid B ERROR verdict counts'}
    analysis['module_verification'] = json.loads((FOLDER / 'module_verification.json').read_text(encoding='utf-8'))['status']
    analysis['limits'] = ['18-case constructed bank, author gold not human-reviewed; group CIs required.',
                          'B flags additional errors on clean NO_ERROR rows by design; precision on clean governs.',
                          'The module is advisory arithmetic only; no claim about policy semantics.']
    write(FOLDER / 'analysis.json', analysis)
    print(json.dumps({'arms': {a: analysis['arms'][a] for a in ARMS},
                      'transition_counts': dict(analysis['transition_counts']),
                      'invalid_B': analysis['invalid_B'], 'missing': analysis['missing_rows']}, indent=1)[:2400])


if __name__ == '__main__':
    main()
