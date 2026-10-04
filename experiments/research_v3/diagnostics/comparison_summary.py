"""Offline same-case comparison, including A3's shared forward dependency cost."""
import csv
import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
BASE = ROOT / 'outputs/searh_23'
OUT = BASE / 'semantic_hybrid_v4_diagnostics_20261004'


def read(path):
    return json.loads(path.read_text(encoding='utf-8'))


def main():
    folder = BASE / 'semantic_hybrid_v4_20261004'
    execution = read(folder / 'execution_subset_metrics.json')
    rows = read(folder / 'predictions_A0_A1_A2_A3.json')
    ledger = read(folder / 'ledger.json')
    common = set(execution['common_case_ids'])
    forward = {(r['id'], q['request_sha256']) for r in rows for q in r['requests'] if q['task'] == 'DISCOVER'}
    report = []
    for arm, arm_metrics in execution['by_arm'].items():
        selected = [r for r in rows if r['arm'] == arm and r['id'] in common]
        requests = {q['request_sha256'] for r in selected for q in r['requests']}
        if arm == 'A3':
            requests.update(h for cid, h in forward if cid in common)
        requests &= set(ledger)
        m = arm_metrics['common_executed_case_metrics']
        report.append({'arm': arm, 'cases': m['n'], 'correct': m['correct'],
                       'accuracy_3way': m['accuracy_3way'], 'decided': m['decided'],
                       'TP': m['TP'], 'FP': m['FP'], 'FN': m['FN'],
                       'unique_requests': len(requests),
                       'known_tokens': sum(ledger[h]['known_tokens'] for h in requests),
                       'http_seconds': sum(ledger[h]['seconds'] for h in requests)})
    output = {'subset': '13_COMMON_EXECUTED_DEV_CASES_SELECTED_BY_RECEIPT_AVAILABILITY',
              'rows': report, 'case_ids': sorted(common), 'new_http': 0,
              'cost_caveats': ['A3 includes reused forward discovery; per-arm costs are not additive.',
                               'This replayed cache attribution is not an equal-budget randomized trial.',
                               'Time is summed recorded HTTP service time, not end-to-end wall latency.']}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / 'common_case_comparison.json').write_text(json.dumps(output, indent=2) + '\n', encoding='utf-8', newline='\n')
    with (OUT / 'common_case_comparison.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=list(report[0])); writer.writeheader(); writer.writerows(report)
    print(json.dumps(report))


if __name__ == '__main__':
    main()
