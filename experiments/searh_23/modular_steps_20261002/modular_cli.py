"""JSONL preserving UNKNOWN; optional CSV uses explicitly fixed mapping."""
import argparse
import csv
import json
from pathlib import Path
from modular_runtime import check, CONFIGS, config_identity


def main():
    p = argparse.ArgumentParser()
    p.add_argument('--input', required=True, type=Path)
    p.add_argument('--output', required=True, type=Path)
    p.add_argument('--config', choices=CONFIGS, default='modular-structural-v1')
    p.add_argument('--csv', type=Path)
    args = p.parse_args()
    previous = {r['source_sha256']: r for r in map(json.loads, args.output.read_text(encoding='utf-8').splitlines())} if args.output.exists() else {}
    results = []
    from modular_common import append, source_sha
    for row in map(json.loads, args.input.read_text(encoding='utf-8').splitlines()):
        identity = source_sha(row)
        old = previous.get(identity)
        if old and (old['config_id'] != args.config or old.get('config_sha256') != config_identity(args.config)):
            raise ValueError('resume_configuration_mismatch')
        result = old or check({'case_id': row.get('id', row.get('case_id', 'unnamed')), 'prompt': row['prompt'], 'response': row['response']}, args.config)
        if old is None:
            append(args.output, result)
        results.append(result)
    if args.csv:
        with args.csv.open('w', encoding='utf-8', newline='') as f:
            writer = csv.writer(f)
            writer.writerow(['case_id', 'label', 'decision'])
            writer.writerows((r['case_id'], int(r['decision'] == 'ERROR'), r['decision']) for r in results)


if __name__ == '__main__':
    main()
