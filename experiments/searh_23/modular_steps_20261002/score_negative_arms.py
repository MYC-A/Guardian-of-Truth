"""Verdict-level DEV scoring of the four frozen negative-routing arms.

Separate from the frozen runners: reads the completed journal only, never
touches gold before all prediction hashes are recorded (they are — the run
is COMPLETED). Follows the established binary mapping convention:
UNKNOWN counts as correct on a clean case (no false alarm) and as a miss on
an error case; determined accuracy is reported separately.
"""
import json
from pathlib import Path
from modular_common import HERE, RESULTS, sha, write

ARMS = ('strict_positive', 'strict_always', 'strict_source_adaptive', 'strict_matched_random')


def _binary_correct(decision, label):
    if decision == 'UNKNOWN':
        return label == 0
    return (decision == 'ERROR') == bool(label)


def run(root=RESULTS):
    manifest = json.loads((HERE / 'dataset/manifest.json').read_text(encoding='utf-8'))
    blob = (HERE / 'dataset/dev_gold.jsonl').read_bytes()
    if sha(blob) != manifest['splits']['dev']['gold_sha256']:
        raise ValueError('dev_gold_identity_mismatch')
    gold = {r['id']: r for r in map(json.loads, blob.decode().splitlines())}
    folder = root / 'negative_review_pilot_v4'
    prepared = json.loads((folder / 'selection.json').read_text(encoding='utf-8'))
    rows = [json.loads(l) for l in (folder / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    shared = {r['id']: r for r in map(json.loads, (folder / 'shared_B.jsonl').read_text(encoding='utf-8').splitlines())}
    by_arm = {arm: [r for r in rows if r['arm'] == arm] for arm in ARMS}
    if any(len(v) != len(rows) // len(ARMS) for v in by_arm.values()):
        raise ValueError('incomplete_journal')

    def counts(arm):
        out = {'TP': 0, 'FP': 0, 'FN': 0, 'TN': 0, 'UNKNOWN': 0, 'UNKNOWN_on_error': 0,
               'UNKNOWN_on_clean': 0, 'degraded': 0, 'invalid_B': 0}
        for r in by_arm[arm]:
            label = gold[r['id']]['label']
            if r['decision'] == 'UNKNOWN':
                out['UNKNOWN'] += 1
                out['UNKNOWN_on_error' if label else 'UNKNOWN_on_clean'] += 1
            elif r['decision'] == 'ERROR':
                out['TP' if label else 'FP'] += 1
            else:
                out['FN' if label else 'TN'] += 1
            out['degraded'] += bool(r.get('degraded'))
            out['invalid_B'] += bool(r.get('B_used') and not shared[r['id']]['review']['valid'])
        determined = [r for r in by_arm[arm] if r['decision'] != 'UNKNOWN']
        hits = sum(1 for r in by_arm[arm] if _binary_correct(r['decision'], gold[r['id']]['label']))
        out['n'] = len(by_arm[arm])
        out['binary_correct'] = hits
        out['binary_accuracy'] = round(hits / len(by_arm[arm]), 4)
        if determined:
            tp, fp, fn, tn = out['TP'], out['FP'], out['FN'], out['TN']
            out['determined_accuracy'] = round((tp + tn) / len(determined), 4)
            out['precision'] = round(tp / (tp + fp), 4) if tp + fp else None
            out['recall'] = round(tp / (tp + fn), 4) if tp + fn else None
            out['f1'] = round(2 * tp / (2 * tp + fp + fn), 4) if 2 * tp + fp + fn else None
        return out

    def transitions(base_arm, arm):
        base = {r['id']: r for r in by_arm[base_arm]}
        moved = []
        for r in by_arm[arm]:
            b = base[r['id']]
            if r['decision'] != b['decision']:
                moved.append({'id': r['id'], 'gold_label': gold[r['id']]['label'],
                              'base': b['decision'], 'arm': r['decision'],
                              'B_used': r.get('B_used'),
                              'binary_correct_base': _binary_correct(b['decision'], gold[r['id']]['label']),
                              'binary_correct_arm': _binary_correct(r['decision'], gold[r['id']]['label'])})
        return moved

    # The known primary FN(s): primary NO_ERROR where gold says ERROR.
    known_fn = sorted({r['id'] for r in by_arm['strict_positive']
                       if r['decision'] == 'NO_ERROR' and gold[r['id']]['label'] == 1})
    fn_outcomes = {}
    for arm in ARMS:
        fn_outcomes[arm] = [{'id': r['id'], 'decision': r['decision'], 'degraded': r.get('degraded'),
                             'B_used': r.get('B_used'), 'reason': r.get('reason'),
                             'binary_correct': _binary_correct(r['decision'], gold[r['id']]['label'])}
                            for r in by_arm[arm] if r['id'] in known_fn]
    cost = {arm: {'queries_if_executed_alone': sum(r['cost_if_executed_alone']['actual_api_attempts'] for r in by_arm[arm]),
                  'tokens_if_executed_alone': sum(r['cost_if_executed_alone']['logical_tokens'] for r in by_arm[arm])}
            for arm in ARMS}
    report = {'scope': 'DEV verdict-level scoring of the frozen negative-routing arms (48 primary decisions reused, one shared B query per case, four arms).',
              'gold_opened_after': 'run COMPLETED 192/192 and all prediction rows journaled',
              'code_sha256': prepared['code_sha256'], 'human_gold_reviewed': False,
              'binary_mapping': 'UNKNOWN counts correct on clean (no false alarm), miss on error; determined accuracy separate',
              'per_arm': {arm: counts(arm) for arm in ARMS},
              'transitions_vs_strict_positive': {arm: transitions('strict_positive', arm)
                                                  for arm in ('strict_always', 'strict_source_adaptive', 'strict_matched_random')},
              'known_primary_FN_ids': known_fn, 'known_FN_outcomes': fn_outcomes,
              'shared_B_spend': {'unique_B_queries': len(shared),
                                 'api_attempts': sum(r['cost']['actual_api_attempts'] for r in shared.values()),
                                 'tokens': sum(r['cost']['logical_tokens'] for r in shared.values())},
              'arm_costs': cost,
              'limits': ['DEV-calibrated triggers; both selections include the known FN by construction, not independent confirmation.',
                         'A B-review inclusion is not a repair: only a valid B ERROR verdict repairs; UNKNOWN/degraded is not CONFIRMED.',
                         'Same B answer shared across arms is one measurement, not four independent votes.']}
    write(folder / 'arm_scoring.json', report)
    print(json.dumps({arm: {k: report['per_arm'][arm][k] for k in
                            ('TP', 'FP', 'FN', 'TN', 'UNKNOWN', 'binary_accuracy', 'precision', 'recall', 'f1')}
                            for arm in ARMS}))
    print(json.dumps({'known_FN_outcomes': {a: fn_outcomes[a] for a in
                                            ('strict_source_adaptive', 'strict_matched_random')}}))


if __name__ == '__main__':
    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('--root', type=Path, default=RESULTS)
    args = parser.parse_args()
    run(args.root)
