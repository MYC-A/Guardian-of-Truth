"""Separate historical scorer; never imported by the detector or controller."""
import argparse
import csv
import json
from collections import Counter

from acceptance import ROOT
from run_compare import OUT


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--allow-partial', action='store_true')
    args = parser.parse_args()
    frozen = json.loads((OUT / 'frozen.json').read_text(encoding='utf-8'))
    records = [json.loads(line) for line in (OUT / 'predictions.jsonl').read_text(encoding='utf-8').splitlines()]
    expected = {(i, a) for i in frozen['case_ids'] for a in frozen['arms']}
    by_key = {(r['case_id'], r['mode']): r for r in records}
    if len(by_key) != len(records) or not set(by_key) <= expected:
        raise RuntimeError('duplicate or foreign predictions')
    if set(by_key) != expected and not args.allow_partial:
        raise RuntimeError('predictions incomplete; gold remains closed unless explicit historical partial report requested')
    csv.field_size_limit(10**9)
    # Gold is only opened here, after all paired predictions or an explicitly
    # disclosed partial dev report. No output changes after this point.
    with (ROOT / 'experiments/searh_23/three_architectures/data/public46_gold.csv').open(newline='', encoding='utf-8') as stream:
        reader = csv.DictReader(stream)
        if 'label' not in reader.fieldnames:
            raise RuntimeError('public46 has no gold label column; provide independent historical gold file')
        gold = {r['id']: int(r['label']) for r in reader}
    summary = {}
    for arm in frozen['arms']:
        counts, stops, operations = Counter(), Counter(), Counter()
        cases, calls, tokens, bounds = [], 0, 0, 0
        for row in records:
            if row['mode'] != arm:
                continue
            label, decision = gold[row['case_id']], row['decision']
            key = ('UNKNOWN_POSITIVE' if label else 'UNKNOWN_NEGATIVE') if decision == 'UNKNOWN' else (
                'TP' if label and decision == 'ERROR' else 'FP' if not label and decision == 'ERROR' else
                'FN' if label else 'TN')
            counts[key] += 1; stops[row['stop_reason']] += 1
            calls += row['cost_after']['actual_api_attempts'] - row['cost_before']['actual_api_attempts']
            tokens += row['cost_after']['known_provider_tokens'] - row['cost_before']['known_provider_tokens']
            bounds += row['cost_after']['unknown_usage_upper_bounds'] - row['cost_before']['unknown_usage_upper_bounds']
            for trace in row['module_trace']:
                action = trace.get('action', {}).get('action', {})
                if action:
                    operations[action['op']] += 1
                    if action['op'] == 'traverse':
                        operations['traverse/' + action.get('args', {}).get('strategy', 'BFS')] += 1
            cases.append({'id': row['case_id'], 'gold': label, 'decision': decision,
                'bucket': key, 'stop_reason': row['stop_reason'], 'basis': row['decision_basis']})
        summary[arm] = {'counts': dict(counts), 'stops': dict(stops), 'operations': dict(operations),
            'actual_api_attempts': calls, 'known_tokens': tokens, 'unknown_usage_bounds': bounds,
            'cases': cases}
    changed = []
    for case_id in frozen['case_ids']:
        a, b = by_key.get((case_id, 'direct')), by_key.get((case_id, 'search'))
        if a and b and a['decision'] != b['decision']:
            changed.append({'id': case_id, 'gold': gold[case_id], 'direct': a['decision'], 'search': b['decision'],
                'direct_stop': a['stop_reason'], 'search_stop': b['stop_reason']})
    output = {'scope': 'BURNED_PUBLIC46_DEVELOPMENT_NOT_INDEPENDENT_TRANSFER',
        'complete': set(by_key) == expected, 'records': len(records), 'expected': len(expected),
        'arms': summary, 'per_case_changes': changed,
        'UNKNOWN_csv_fallback_is_not_a_NO_ERROR_prediction': True}
    (OUT / 'score.json').write_text(json.dumps(output, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps({k: {kk: vv for kk, vv in v.items() if kk != 'cases'} for k, v in summary.items()}))


if __name__ == '__main__':
    main()
