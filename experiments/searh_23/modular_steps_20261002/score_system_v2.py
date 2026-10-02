"""Post-run scorer for the automatic SystemV2 E2E pilot (§7.D M1).

Gold is opened here only, after the run SUCCEEDED and all rows were
journaled. Compares the ordinary-upstream automatic profile against gold
and the archived C0 baseline on the same 4 cases; UNKNOWN counts correct
on clean and a miss on error (score_negative_arms convention).
"""
import json
from modular_common import HERE, RESULTS, write

FOLDER = RESULTS / 'system_v2_pilot'


def main():
    rows = [json.loads(l) for l in (FOLDER / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    gold = {}
    for line in (HERE / 'dataset/dev_gold.jsonl').read_text(encoding='utf-8').splitlines():
        r = json.loads(line)
        gold[r['id']] = r['label']
    control = {json.loads(l)['id']: json.loads(l)['output'].get('decision')
               for l in (RESULTS / 'control_dev/predictions.jsonl').read_text(encoding='utf-8').splitlines()}
    per_case = {}
    tallies = {'system_v2': {'TP': 0, 'FP': 0, 'FN': 0, 'TN': 0, 'UNKNOWN': 0}, 'C0': {'TP': 0, 'FP': 0, 'FN': 0, 'TN': 0}}
    for r in rows:
        label = gold[r['id']]
        entry = {'gold': label, 'system_v2': r['decision'], 'C0': control.get(r['id']),
                 'basis': r.get('basis'), 'degraded': r.get('degraded'),
                 'unknown_reasons': r.get('unknown_reasons'),
                 'cost': r.get('cost'), 'advisory': r.get('v2_advisory_summary'),
                 'modules': r.get('modules')}
        for name, decision in (('system_v2', r['decision']), ('C0', control.get(r['id']))):
            if decision == 'ERROR':
                tallies[name]['TP' if label == 1 else 'FP'] += 1
            elif decision == 'NO_ERROR':
                tallies[name]['FN' if label == 1 else 'TN'] += 1
            else:
                tallies[name]['UNKNOWN'] += 1
                tallies[name]['TN' if label == 0 else 'FN'] += 1
        entry['transition_C0_to_v2'] = {'kind': (
            'unchanged' if r['decision'] == control.get(r['id']) else
            'fixed' if control.get(r['id']) == 'NO_ERROR' and r['decision'] == 'ERROR' else
            'lost' if control.get(r['id']) == 'ERROR' and r['decision'] == 'NO_ERROR' else 'other')}
        per_case[r['id']] = entry
    def f1(t):
        tp, fp, fn = t['TP'], t['FP'], t['FN']
        p = tp / (tp + fp) if tp + fp else None
        rc = tp / (tp + fn) if tp + fn else None
        return p, rc, (2 * p * rc / (p + rc) if p and rc else None)
    analysis = {'schema': 'system-v2-scoring/1',
        'gold_opened_after': 'run SUCCEEDED 4/4 and all rows journaled',
        'binary_mapping': 'UNKNOWN counts correct on clean, miss on error',
        'per_case': per_case, 'tallies': tallies,
        'F1': {name: {'precision': f1(t)[0], 'recall': f1(t)[1], 'F1': f1(t)[2]} for name, t in tallies.items()},
        'limits': ['Four cases, correlated constructions; no quality certificate.',
                   'Ordinary upstream only: automatic IR extraction, no gold substitutions.',
                   'Advisory layers are measured end-to-end through J and strict B; layer attribution requires the archived per-stage traces.'],
        'cost_total': {k: sum(r.get('cost', {}).get(k, 0) for r in rows if isinstance(r.get('cost'), dict))
                       for k in ('actual_api_attempts', 'logical_tokens', 'model_seconds')}}
    write(FOLDER / 'analysis.json', analysis)
    print(json.dumps({'tallies': tallies, 'F1': analysis['F1'],
                      'per_case': {i: {k: e[k] for k in ('gold', 'system_v2', 'C0', 'transition_C0_to_v2', 'degraded')}
                                   for i, e in per_case.items()}}, indent=1)[:1600])


if __name__ == '__main__':
    main()
