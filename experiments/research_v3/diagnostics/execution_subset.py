"""Separate unavailable requests from executed model failures after scoring."""
import argparse
from collections import Counter
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'experiments/research_v3'))
from pilot import read, write, HERE
from score import metrics


def available(row, out):
    if row['result'].get('scope_excluded'):
        return False
    if row['failure'] in ('FORWARD_DISCOVERY_UNAVAILABLE', 'CACHE_MISS_OR_BREAKER', 'BUDGET_STOP', 'HTTP_ERROR', 'TRANSPORT_ERROR', 'CREDENTIAL_UNAVAILABLE'):
        return False
    for q in row['requests']:
        path = out / 'raw' / (q['request_sha256'] + '.json')
        if not path.exists() or read(path)['status'] != 'OK':
            return False
    for m in row['observations']:
        if m.get('cause') in ('CACHE_MISS_OR_BREAKER', 'BUDGET_STOP', 'HTTP_ERROR', 'TRANSPORT_ERROR', 'CREDENTIAL_UNAVAILABLE', 'PRIOR_UNSAVED_ATTEMPT_NO_RETRY'):
            return False
    return True


def evaluate(out, path):
    rows, gold = read(path), read(HERE / 'fixtures/gold.json')
    statuses, results = {}, {}
    for arm in sorted({r['arm'] for r in rows}):
        selected = [r for r in rows if r['arm'] == arm]
        supported = [r for r in selected if not r['result'].get('scope_excluded')]
        executed = [r for r in supported if available(r, out)]
        observations = [{'gold': gold[r['id']]['verdict'], 'predicted': r['result']['verdict'], **gold[r['id']], 'id': r['id']} for r in executed]
        results[arm] = {'executed_supported': len(executed), 'unavailable_supported': len(supported) - len(executed),
                        'scope_excluded': len(selected) - len(supported),
                        'executed_metrics': metrics(observations),
                        'executed_call_metrics': metrics([r for r in observations if r['scope'] == 'call']),
                        'executed_dev_metrics': metrics([r for r in observations if r['split'] == 'dev']),
                        'executed_heldout_metrics': metrics([r for r in observations if r['split'] == 'heldout']),
                        'executed_case_ids': [r['id'] for r in executed],
                        'inference_failure_counts': dict(Counter((r['failure'] or 'NONE').split('\n')[0] for r in executed))}
    # Same cases with executed receipts in every requested arm. Does not recover
    # a prospective sealed benchmark when transport halted before heldout.
    common = set.intersection(*(set(r['executed_case_ids']) for r in results.values()))
    for arm in results:
        pair = [{'gold': gold[r['id']]['verdict'], 'predicted': r['result']['verdict']} for r in rows if r['arm'] == arm and r['id'] in common]
        results[arm]['common_executed_case_metrics'] = metrics(pair)
    write(out / 'execution_subset_metrics.json', {'by_arm': results, 'common_case_ids': sorted(common),
          'selection': 'TRANSPORT_AVAILABILITY_NOT_OUTCOME; EXPLORATORY_IF_INTERRUPTED', 'new_http': 0})
    return results


if __name__ == '__main__':
    p = argparse.ArgumentParser(); p.add_argument('--out', type=Path, required=True); p.add_argument('--predictions', type=Path, required=True)
    args = p.parse_args()
    r = evaluate(args.out, args.predictions)
    import json
    print(json.dumps({arm: {'executed': s['executed_supported'], 'unavailable': s['unavailable_supported'],
                            'metrics': s['executed_metrics']} for arm, s in r.items()}))
