import argparse
import csv
import json
from dataclasses import asdict
from pathlib import Path

from .pipeline import Detector


def read_rows(path: Path):
    if path.suffix.lower() == '.parquet':
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError('Install the data extra: pip install -e ".[data]"') from exc
        return pd.read_parquet(path).to_dict('records')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        return list(csv.DictReader(stream))


def validate_rows(rows):
    ids = set()
    for row in rows:
        if any(k not in row for k in ('id', 'prompt', 'response')):
            raise ValueError('Required columns: id, prompt, response')
        key = str(row['id'])
        if key in ids: raise ValueError(f'Duplicate id: {key}')
        ids.add(key)
        if not all(isinstance(row[k], str) for k in ('prompt', 'response')):
            raise ValueError(f'Non-text input for {key}')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True, type=Path)
    parser.add_argument('--output', required=True, type=Path)
    parser.add_argument('--audit', type=Path)
    parser.add_argument('--unknown-label', choices=(0, 1), default=0, type=int,
                        help='Technical fallback only; unknown is not a proof of correctness')
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.input, args.output, args.audit) if p]
    if len(set(paths)) != len(paths): parser.error('Input, output and audit paths must differ')
    rows = read_rows(args.input)
    validate_rows(rows)
    detector = Detector()
    predictions, audits = [], []
    for row in rows:
        review = detector.review(row['prompt'], row['response'])
        label = 1 if review.status == 'violation' else args.unknown_label
        predictions.append({'id': str(row['id']), 'label': label})
        audits.append({'id': str(row['id']), 'label': label,
                       'used_fallback': review.status == 'unknown', **asdict(review)})
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'label'])
        writer.writeheader()
        writer.writerows(predictions)
    if args.audit:
        args.audit.parent.mkdir(parents=True, exist_ok=True)
        with args.audit.open('w', encoding='utf-8') as stream:
            for audit in audits: stream.write(json.dumps(audit, ensure_ascii=False) + '\n')
