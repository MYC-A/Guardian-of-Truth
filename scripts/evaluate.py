"""Development measurement only: reference labels never enter Detector.review."""

import argparse
import json
import time
from collections import Counter
from pathlib import Path

from guardian_truth.cli import read_rows, validate_rows
from guardian_truth.pipeline import Detector


def metrics(pairs):
    tp = sum(y == 1 and p == 1 for y, p in pairs)
    fp = sum(y == 0 and p == 1 for y, p in pairs)
    fn = sum(y == 1 and p == 0 for y, p in pairs)
    tn = sum(y == 0 and p == 0 for y, p in pairs)
    return dict(n=len(pairs), tp=tp, fp=fp, fn=fn, tn=tn,
                precision=tp/(tp+fp) if tp+fp else 0,
                recall=tp/(tp+fn) if tp+fn else 0,
                f1=2*tp/(2*tp+fp+fn) if 2*tp+fp+fn else 0)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    if args.input.resolve() == args.output.resolve(): parser.error('Output must differ from input')
    rows = read_rows(args.input)
    validate_rows(rows)
    labels = [int(row['label']) for row in rows]
    if any(label not in (0, 1) for label in labels): raise ValueError('Labels must be binary')
    report = {'warning': 'Development sample, not held-out quality. Unknown -> 0 is a fixed fallback.',
              'trajectory_groups': len({str(r['id']).split('::')[0] for r in rows}), 'runs': {}}
    for name, enabled in [('availability', {'availability'}), ('schema', {'schema'}),
                          ('combined', {'availability', 'schema'}),
                          ('with_provenance', {'availability', 'schema', 'provenance'})]:
        begin = time.perf_counter()
        detector = Detector(enabled)
        reviews = [detector.review(r['prompt'], r['response']) for r in rows]
        predicted = [int(r.status == 'violation') for r in reviews]
        by_domain, by_finding = {}, {}
        for row, y, p, review in zip(rows, labels, predicted, reviews):
            domain = str(row['id']).split('__')[0]
            by_domain.setdefault(domain, []).append((y, p))
            for code in {f.code for f in review.findings if f.status == 'violation'}:
                counts = by_finding.setdefault(code, {'tp': 0, 'fp': 0})
                counts['tp' if y else 'fp'] += 1
        report['runs'][name] = {**metrics(list(zip(labels, predicted))),
            'seconds': time.perf_counter()-begin,
            'unknown': sum(r.status == 'unknown' for r in reviews),
            'by_domain': {k: metrics(v) for k,v in by_domain.items()}, 'by_finding': by_finding,
            'provenance': {
                'note': 'Structural coverage, not correctness or calibrated confidence.',
                'facts': sum(len(r.graph.facts) for r in reviews),
                'version_edges': sum(len(f.previous) for r in reviews for f in r.graph.facts),
                'arguments': sum(len(r.graph.arguments) for r in reviews),
                'argument_statuses': dict(Counter(t.status for r in reviews for t in r.graph.arguments)),
                'examples_with_arguments': sum(bool(r.graph.arguments) for r in reviews),
                'issues': dict(Counter(issue for r in reviews for issue in r.graph.issues)),
            }}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(report, ensure_ascii=False, indent=2), encoding='utf-8')
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == '__main__': main()
