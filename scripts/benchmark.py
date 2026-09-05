"""Offline paired baseline benchmark; deliberately has no model/API configuration."""

import argparse
import hashlib
import json
from pathlib import Path

from guardian_truth.benchmarking import load_examples, run_benchmark, split_examples
from guardian_truth.pipeline import Detector


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='JSON report including frozen manifest')
    parser.add_argument('--scores', type=Path, required=True, help='Per-example JSONL scores')
    parser.add_argument('--assign-splits', action='store_true', help='Assign unassigned groups deterministically')
    parser.add_argument('--calibrate', action='store_true', help='Select thresholds using calibration rows only')
    parser.add_argument('--seed', type=int, default=0)
    parser.add_argument('--bootstrap-samples', type=int, default=1000)
    parser.add_argument('--baseline', choices=('zero', 'structural'), default='zero')
    parser.add_argument('--checks', default='availability,schema,provenance')
    args = parser.parse_args()
    if len({p.resolve() for p in (args.input, args.output, args.scores)}) != 3:
        parser.error('Input, output and scores must have different paths')
    try:
        examples = load_examples(args.input)
        if args.assign_splits:
            examples = split_examples(examples, seed=args.seed)
        checks = frozenset(item.strip() for item in args.checks.split(',') if item.strip())
        candidate = Detector(enabled=checks)
        baseline = (lambda prompt, response: 0.0) if args.baseline == 'zero' else Detector()
        package = Path(__import__('guardian_truth').__file__).parent
        revision = {path.name: hashlib.sha256(path.read_bytes()).hexdigest()
                    for path in sorted(package.glob('*.py'))}
        result = run_benchmark(examples, baseline, candidate, calibrate=args.calibrate,
                               bootstrap_samples=args.bootstrap_samples, seed=args.seed,
                               configuration={'baseline': args.baseline, 'candidate': 'offline_structural',
                                              'checks': sorted(checks), 'source_hashes': revision,
                                              'split_assignment': 'hash' if args.assign_splits else 'explicit'})
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    per_example = result.pop('per_example')
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.scores.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(result, ensure_ascii=False, indent=2, allow_nan=False) + '\n', encoding='utf-8')
    with args.scores.open('w', encoding='utf-8') as stream:
        for row in per_example:
            stream.write(json.dumps(row, ensure_ascii=False, allow_nan=False) + '\n')
    print(json.dumps({'test_kind': result['test_kind'], 'baseline': result['report']['baseline'],
                      'candidate': result['report']['candidate'], 'delta': result['report']['delta'],
                      'manifest_hash': result['manifest']['manifest_hash']}, ensure_ascii=False))


if __name__ == '__main__':
    main()
