"""LLM-free runtime gate: row -> verdict/label/audit trace, plus valid-set scoring.

Usage::

    python -m guardian_truth.policy_table_v11.service --input valid.parquet \
        --output preds.csv --audit audit.jsonl --metrics metrics.json \
        [--bundle policy_bundle.json] [--mode BALANCED] [--unknown-label 0]

Labels: VIOLATION -> 1, ADMISSIBLE -> 0, UNKNOWN -> ``--unknown-label``
(technical fallback, reported separately; it is not a proof of correctness).
"""
import argparse
import csv
import json
import statistics
import sys
from pathlib import Path

from guardian_truth.policy_table.segment import policy_hash
from guardian_truth.source_search.store import SourceStore
from .admissibility import assess, audit_jsonl, EnforcementPolicy, VIOLATION, UNKNOWN, STRICT, BALANCED, PERMISSIVE
from .bundle import BundleError, load_bundle, table_for


class Gate:
    def __init__(self, bundle=None, *, mode=BALANCED, unknown_label=0, tool_risk=None):
        if unknown_label not in (0, 1): raise ValueError('unknown_label must be 0 or 1')
        self.bundle, self.unknown_label = bundle, unknown_label
        self.enforcement = EnforcementPolicy(mode, tool_risk)

    def check(self, row):
        try:
            store = SourceStore(row)
        except Exception as exc:  # malformed input never crashes the batch
            return {'id': row.get('id'), 'label': self.unknown_label, 'verdict': UNKNOWN, 'decision': 'REVIEW',
                    'error': f'{type(exc).__name__}: {exc}'}
        table = table_for(self.bundle, policy_hash(store))
        trace = assess(store, table=table, enforcement=self.enforcement)
        if table is None: trace['notes'].append({'code': 'NO_POLICY_TABLE'})
        label = 1 if trace['verdict'] == VIOLATION else self.unknown_label if trace['verdict'] == UNKNOWN else 0
        return {'id': row.get('id'), 'label': label, **trace}


def read_rows(path):
    path = Path(path)
    if path.suffix.lower() == '.parquet':
        import pandas as pd
        return pd.read_parquet(path).to_dict('records')
    if path.suffix.lower() == '.jsonl':
        return [json.loads(l) for l in path.read_text(encoding='utf-8').splitlines() if l.strip()]
    csv.field_size_limit(16 * 1024 * 1024)
    with path.open(encoding='utf-8-sig', newline='') as s: return list(csv.DictReader(s))


def score(results, gold):
    tp = fp = fn = tn = 0
    for r in results:
        g = gold.get(str(r['id']))
        if g is None: continue
        p = r['label']
        tp += p == 1 and g == 1; fp += p == 1 and g == 0; fn += p == 0 and g == 1; tn += p == 0 and g == 0
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {'tp': tp, 'fp': fp, 'fn': fn, 'tn': tn, 'precision': round(precision, 4), 'recall': round(recall, 4),
            'f1': round(f1, 4), 'scored_rows': tp + fp + fn + tn}


def summarize(results, gold=None):
    lat = [r.get('latency_ms', 0.0) for r in results]
    verdicts, routes = {}, {}
    for r in results:
        verdicts[r['verdict']] = verdicts.get(r['verdict'], 0) + 1
        routes[r.get('route', 'ERROR')] = routes.get(r.get('route', 'ERROR'), 0) + 1
    out = {'rows': len(results), 'verdicts': verdicts, 'routes': routes, 'errors': sum('error' in r for r in results),
           'latency_ms': {'median': round(statistics.median(lat), 3) if lat else 0.0, 'max': round(max(lat), 3) if lat else 0.0},
           'llm_calls': 0}
    if gold: out['metrics'] = score(results, gold)
    return out


def _gold(rows):
    gold = {}
    for row in rows:
        v = row.get('label')
        if v is None or str(v).strip() in ('', 'nan'): continue
        gold[str(row['id'])] = int(float(v))
    return gold


def main(argv=None):
    ap = argparse.ArgumentParser(description='LLM-free Guardian admissibility gate')
    ap.add_argument('--input', required=True, type=Path)
    ap.add_argument('--output', required=True, type=Path)
    ap.add_argument('--audit', type=Path)
    ap.add_argument('--metrics', type=Path)
    ap.add_argument('--bundle', type=Path, help='Signed policy bundle (built offline by scripts/build_policy_bundle.py)')
    ap.add_argument('--require-hmac', action='store_true', help='Reject bundles without an HMAC signature')
    ap.add_argument('--mode', choices=(STRICT, BALANCED, PERMISSIVE), default=BALANCED)
    ap.add_argument('--unknown-label', type=int, choices=(0, 1), default=0)
    ap.add_argument('--min-f1', type=float, help='Exit 2 when labelled F1 is below this floor (CI regression gate)')
    args = ap.parse_args(argv)
    bundle = None
    if args.bundle:
        try: bundle = load_bundle(args.bundle, require_hmac=args.require_hmac)
        except (BundleError, OSError, json.JSONDecodeError) as exc: ap.error(f'policy bundle rejected: {exc}')
    rows = read_rows(args.input)
    ids = [str(r.get('id', '')) for r in rows]
    if any(not i.strip() for i in ids) or len(set(ids)) != len(ids): ap.error('input needs unique nonempty id column')
    gate = Gate(bundle, mode=args.mode, unknown_label=args.unknown_label)
    results = [gate.check(r) for r in rows]
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8') as s:
        w = csv.DictWriter(s, fieldnames=['id', 'label']); w.writeheader()
        for r in results: w.writerow({'id': r['id'], 'label': r['label']})
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        args.audit.write_text(''.join(audit_jsonl(r) + '\n' for r in results), encoding='utf-8')
    summary = summarize(results, _gold(rows))
    summary.update({'mode': args.mode, 'unknown_label': args.unknown_label,
                    'bundle': None if bundle is None else {'signature': bundle['signature']['algorithm'],
                                                           'tables': len(bundle['tables'])}})
    text = json.dumps(summary, ensure_ascii=False, indent=1, sort_keys=True)
    if args.metrics:
        args.metrics.parent.mkdir(parents=True, exist_ok=True); args.metrics.write_text(text + '\n', encoding='utf-8')
    print(text)
    if args.min_f1 is not None and summary.get('metrics', {}).get('f1', 0.0) < args.min_f1:
        print(f'F1 below floor {args.min_f1}', file=sys.stderr); return 2
    return 0


if __name__ == '__main__':
    sys.exit(main())
