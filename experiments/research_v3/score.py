"""Open gold only after saving predictions; never imported by inference runner."""
import argparse
from collections import Counter, defaultdict
import csv
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).parent))
from pilot import HERE, DEFAULT_OUT, read, sha, write


def metrics(rows):
    n = len(rows)
    if not n:
        return {'n': 0}
    counts = Counter((r['gold'], r['predicted']) for r in rows)
    tp = counts['ERROR', 'ERROR']
    fp = sum(v for (g, p), v in counts.items() if g != 'ERROR' and p == 'ERROR')
    fn = sum(v for (g, p), v in counts.items() if g == 'ERROR' and p != 'ERROR')
    tn = n - tp - fp - fn
    decided = [r for r in rows if r['predicted'] != 'UNKNOWN']
    return {'n': n, 'correct': sum(r['gold'] == r['predicted'] for r in rows),
            'accuracy_3way': sum(r['gold'] == r['predicted'] for r in rows) / n,
            'decided': len(decided), 'decided_coverage': len(decided) / n,
            'accuracy_decided': sum(r['gold'] == r['predicted'] for r in decided) / len(decided) if decided else None,
            'unknown_rate': 1 - len(decided) / n,
            'TP': tp, 'FP': fp, 'FN': fn, 'TN': tn, 'precision': tp / (tp + fp) if tp + fp else None,
            'recall': tp / (tp + fn) if tp + fn else None,
            'F1_binary_abstain_to_0': 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0,
            'false_ERROR_rate': fp / sum(r['gold'] != 'ERROR' for r in rows) if any(r['gold'] != 'ERROR' for r in rows) else None}


def score(out, prediction_path):
    p = read(out / 'protocol.json')
    if sha(HERE / 'fixtures/gold.json') != p['gold_sha256']:
        raise ValueError('GOLD_CHANGED_AFTER_FREEZE')
    predictions = read(prediction_path)
    gold = read(HERE / 'fixtures/gold.json')
    if len({(r['id'], r['arm']) for r in predictions}) != len(predictions):
        raise ValueError('DUPLICATE_PREDICTION')
    scores, rows, failures, additions = {}, [], [], []
    ledger = read(out / 'ledger.json') if (out / 'ledger.json').exists() else {}
    for r in predictions:
        g = gold[r['id']]
        result = r['result']
        row = {'id': r['id'], 'arm': r['arm'], **g, 'gold': g['verdict'], 'predicted': result['verdict'],
               'scope_excluded': bool(result.get('scope_excluded')), 'failure': r['failure']}
        row['correct'] = row['gold'] == row['predicted']
        rows.append(row)
        if not row['correct'] or row['failure']:
            failures.append({**row, 'model_result': result})
        forward = set(s for c in (result.get('forward') or {}).get('candidates', []) for s in c['policy_ids'] + c['exception_ids'])
        reverse = set(s for c in (result.get('reverse') or {}).get('candidates', []) for s in c['policy_ids'] + c['exception_ids'])
        if r['arm'] == 'A3':
            required = set(g['required_policy_ids'])
            additions.append({'id': r['id'], 'extra_source_ids': sorted(reverse - forward),
                              'extra_required_ids': sorted((reverse - forward) & required),
                              'extra_other_ids': sorted((reverse - forward) - required),
                              'note': 'Other IDs are not automatically false norms; manual semantic audit required.'})
    for arm in sorted({r['arm'] for r in rows}):
        full = [r for r in rows if r['arm'] == arm]
        supported = [r for r in full if not r['scope_excluded']]
        request_ids = set(q['request_sha256'] for r in predictions if r['arm'] == arm for q in r['requests'])
        known = sum(ledger.get(k, {}).get('known_tokens', 0) for k in request_ids)
        unsupported = [r['id'] for r in full if r['scope_excluded']]
        scores[arm] = {'all_with_unsupported_unknown': metrics(full), 'supported_scope': metrics(supported),
                       'call_only': metrics([r for r in supported if r['scope'] == 'call']),
                       'speech_only': metrics([r for r in supported if r['scope'] == 'speech']),
                       'dev': metrics([r for r in supported if r['split'] == 'dev']),
                       'heldout': metrics([r for r in supported if r['split'] == 'heldout']),
                       'by_family': {f: metrics([r for r in supported if r['family'] == f]) for f in sorted({r['family'] for r in full})},
                       'by_variant': {v: metrics([r for r in supported if r['variant'] == v]) for v in sorted({r['variant'] for r in full})},
                       'excluded_case_ids': unsupported,
                       'request_references': sum(len(r['requests']) for r in predictions if r['arm'] == arm),
                       'unique_requests': len(request_ids), 'known_tokens_on_referenced_requests': known,
                       'note': 'Shared request tokens attributed to every using arm; totals are not additive.'}
        model_rows = [r for r in predictions if r['arm'] == arm]
        valid = [r for r in model_rows if not r['failure'] and not r['result'].get('scope_excluded')]
        scores[arm]['pipeline_no_failure_rate'] = len(valid) / len(supported) if supported else None
        effects = [(gold[r['id']]['effect'], r['result'].get('effect')) for r in valid if r['result'].get('effect')]
        scores[arm]['effect_accuracy'] = {'n': len(effects), 'correct': sum(g == p for g, p in effects)}
        groups = [(set(gold[r['id']]['required_policy_ids']), set(r['result'].get('policy_ids', []))) for r in valid
                  if gold[r['id']]['required_policy_ids']]
        scores[arm]['gold_source_group_complete'] = {'n': len(groups), 'complete': sum(g <= p for g, p in groups),
                                                    'note': 'Source selection only, not semantic NormRecall.'}
    write(out / 'metrics.json', scores)
    write(out / 'failures.json', failures)
    write(out / 'source_additions.json', additions)
    fields = ['arm', 'n', 'accuracy_3way', 'decided_coverage', 'unknown_rate', 'TP', 'FP', 'FN', 'TN', 'F1_binary_abstain_to_0']
    with (out / 'comparison.csv').open('w', encoding='utf-8', newline='') as f:
        writer = csv.DictWriter(f, fieldnames=fields); writer.writeheader()
        for arm, s in scores.items():
            writer.writerow({'arm': arm, **{k: s['call_only'][k] for k in fields[1:]}})
    write(out / 'cost_summary.json', {'http_attempts': len(ledger),
          'known_tokens': sum(v.get('known_tokens', 0) for v in ledger.values()),
          'charged_tokens_including_unknown': sum(v['charged_tokens'] for v in ledger.values()),
          'transport_seconds_sum': sum(v.get('seconds', 0) for v in ledger.values()),
          'statuses': dict(Counter(v['status'] for v in ledger.values())),
          'provider_reported_dollars': None, 'retries': 0, 'gpu_inference': False})
    return scores


if __name__ == '__main__':
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--out', type=Path, default=DEFAULT_OUT)
    p.add_argument('--predictions', type=Path)
    args = p.parse_args()
    print(json.dumps(score(args.out, args.predictions or args.out / 'predictions_A0_A1_A2_A3.json'), ensure_ascii=False))
