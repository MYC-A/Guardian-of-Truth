import argparse
import csv
import json
import time
from dataclasses import asdict
from pathlib import Path

from .pipeline import Detector
from .decision import decide
from .runtime import add_runtime_arguments, detector_from_args
from .settings import load_env_file
from .llm_client import ChatClientError


def read_rows(path: Path):
    if path.suffix.lower() == '.parquet':
        try:
            import pandas as pd
        except ImportError as exc:
            raise RuntimeError('Install the data extra: pip install -e ".[data]"') from exc
        return pd.read_parquet(path).to_dict('records')
    with path.open(encoding='utf-8-sig', newline='') as stream:
        if path.suffix.lower() == '.jsonl':
            return [json.loads(line) for line in stream if line.strip()]
        if path.suffix.lower() != '.csv':
            raise ValueError('Input must be CSV, JSONL, or Parquet')
        return list(csv.DictReader(stream))


def validate_rows(rows):
    ids = set()
    for row in rows:
        if not isinstance(row, dict) or any(k not in row for k in ('id', 'prompt', 'response')):
            raise ValueError('Required columns: id, prompt, response')
        if row['id'] is None or not str(row['id']).strip():
            raise ValueError('A nonempty id is required')
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
    parser.add_argument('--run-report', type=Path)
    parser.add_argument('--env-file', type=Path, default=Path('.env'))
    parser.add_argument('--unknown-label', choices=(0, 1), default=0, type=int,
                        help='Technical fallback only; unknown is not a proof of correctness')
    add_runtime_arguments(parser)
    args = parser.parse_args()
    paths = [p.resolve() for p in (args.input, args.output, args.audit, args.run_report) if p]
    if len(set(paths)) != len(paths): parser.error('Input, output and audit paths must differ')
    if any(p == args.env_file.resolve() for p in paths): parser.error('Data/output paths must differ from env file')
    rows = read_rows(args.input)
    validate_rows(rows)
    load_env_file(args.env_file)
    try:
        detector = detector_from_args(args)
        # Validate classification parameters before creating output files.
        decide(Detector().review('',''),threshold=args.threshold,unknown_label=args.unknown_label)
    except (ValueError, ChatClientError) as error:
        parser.error(str(error))
    started = time.monotonic()
    counts = {'rows':0,'fallbacks':0,'mechanical_violations':0,'semantic_decisions':0}
    args.output.parent.mkdir(parents=True, exist_ok=True)
    with args.output.open('w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, fieldnames=['id', 'label'])
        writer.writeheader()
        audit_stream = None
        try:
            if args.audit:
                args.audit.parent.mkdir(parents=True, exist_ok=True)
                audit_stream = args.audit.open('w',encoding='utf-8')
            for row in rows:
                review = detector.review(row['prompt'], row['response'])
                decision = decide(review, threshold=args.threshold, use_semantic=args.backend != 'none',
                                  unknown_label=args.unknown_label)
                writer.writerow({'id':str(row['id']),'label':decision.label})
                stream.flush()
                counts['rows'] += 1
                counts['fallbacks'] += int(decision.used_fallback)
                counts['mechanical_violations'] += int(decision.reason == 'mechanical_violation')
                counts['semantic_decisions'] += int(decision.score is not None)
                if audit_stream:
                    audit = {'id':str(row['id']), **asdict(review), **asdict(decision)}
                    audit_stream.write(json.dumps(audit,ensure_ascii=False,allow_nan=False)+'\n')
                    audit_stream.flush()
        finally:
            if audit_stream:
                audit_stream.close()
    if args.run_report:
        counts.update(seconds=time.monotonic()-started,backend=args.backend,mode=args.mode,recovery=args.recovery,
                      threshold=args.threshold,score_kind='uncalibrated',
                      budget=detector.semantic.budget.summary() if hasattr(detector.semantic,'budget') else None)
        args.run_report.parent.mkdir(parents=True,exist_ok=True)
        args.run_report.write_text(json.dumps(counts,indent=2,allow_nan=False),encoding='utf-8')
