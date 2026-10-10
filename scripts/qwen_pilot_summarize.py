"""Independently score a complete pilot export without network/model calls."""
import argparse
from collections import Counter, defaultdict
import hashlib
import json
from pathlib import Path
import zipfile

import pandas as pd


def summarize(bundle, input_path, arm):
    input_sha = hashlib.sha256(input_path.read_bytes()).hexdigest()
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('export_manifest.json'))
        for name, record in manifest.items():
            raw = archive.read(name)
            if len(raw) != record['bytes'] or hashlib.sha256(raw).hexdigest() != record['sha256']:
                raise ValueError('EXPORT_MEMBER_HASH_MISMATCH: ' + name)
        prefix = arm + '/rep1/'
        run = json.loads(archive.read(prefix + 'receipts/run.json'))
        report = json.loads(archive.read(prefix + 'score/report.json'))
        calls = json.loads(archive.read(prefix + 'receipts/calls.json'))
        traces = [json.loads(s) for s in archive.read(prefix + 'receipts/traces.jsonl').decode('utf-8').splitlines() if s.strip()]
        predictions = pd.read_parquet(__import__('io').BytesIO(archive.read(prefix + 'predictions.parquet')))
    if run['input_sha256'] != input_sha or report['input_sha256'] != input_sha:
        raise ValueError('INPUT_SHA_MISMATCH')
    reference = pd.read_parquet(input_path)
    expected = reference['id'].tolist()
    if len(expected) != len(set(expected)):
        raise ValueError('DUPLICATE_INPUT_ID')
    for records in (traces, predictions.to_dict('records')):
        ids = [r['id'] for r in records]
        if len(ids) != len(set(ids)) or set(ids) != set(expected):
            raise ValueError('INVALID_FULL_ID_SET')
    trace_index = {r['id']: r for r in traces}
    pred_index = dict(zip(predictions['id'], predictions['label']))
    matrix = Counter()
    for r in reference.to_dict('records'):
        label = pred_index[r['id']]
        if label not in (0, 1) or isinstance(label, (str, float)):
            raise ValueError('NON_BINARY_LABEL')
        if label != trace_index[r['id']]['binary']:
            raise ValueError('LIVE_PREDICTION_TRACE_MISMATCH')
        matrix[('TN', 'FP', 'FN', 'TP')[2 * int(r['label']) + int(label)]] += 1
    metrics = {k: matrix[k] for k in ('TP', 'FP', 'FN', 'TN')}
    tp, fp, fn = metrics['TP'], metrics['FP'], metrics['FN']
    metrics['F1'] = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0.0
    if report['before']['metrics'] != metrics or report['after']['metrics'] != metrics or report['changes']:
        raise ValueError('SCORE_OR_REPROJECTION_DRIFT')
    if not run.get('output_written') or run['rows'] != len(expected) or len(calls) != run['calls']:
        raise ValueError('INCOMPLETE_RUN')
    groups = defaultdict(list)
    for c in calls:
        groups[c['tag']].append(c)
    per_stage = {}
    for tag, receipts in sorted(groups.items()):
        per_stage[tag] = dict(calls=len(receipts),
            input_tokens=sum((c.get('usage') or {}).get('prompt_tokens', 0) for c in receipts),
            output_tokens=sum((c.get('usage') or {}).get('completion_tokens', 0) for c in receipts),
            finish_reasons=dict(Counter(str(c.get('finish_reason')) for c in receipts)),
            transport_status=dict(Counter(str((c.get('transport') or {}).get('status')) for c in receipts)),
            summed_call_seconds=sum(c['seconds'] for c in receipts))
    return dict(scope='One complete development-set feasibility repetition; not independent holdout or acceptance',
        arm=arm, rows=len(expected), input_sha256=input_sha,
        bundle_sha256=hashlib.sha256(bundle.read_bytes()).hexdigest(),
        metrics=metrics, live_predictions_equal_saved_traces=True, replay_metrics_equal_live=True,
        cli_seconds=run['seconds'],
        time_scope='CLI model startup/health, pipeline, shutdown, output write; excludes bootstrap/probes/scoring',
        calls=run['calls'], input_tokens=run['input_tokens'], output_tokens=run['output_tokens'],
        whole_cli_completion_tokens_per_second=run['output_tokens']/run['seconds'],
        whole_cli_rows_per_minute=len(expected)*60/run['seconds'],
        concurrency_caveat='Summed call seconds overlap across workers; not whole-script latency or isolated GPU compute time',
        raw_model_recoveries=run.get('raw_model_recoveries'), default_zero_fallbacks=run.get('default_zero_fallbacks'),
        owners=dict(Counter(str(t.get('owner')) for t in traces)), per_stage=per_stage)


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--bundle', type=Path, required=True)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--arm', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    result = summarize(args.bundle, args.input, args.arm)
    with args.output.open('x', encoding='utf-8') as stream:
        json.dump(result, stream, indent=2, ensure_ascii=False)
    print(json.dumps({k: result[k] for k in ('arm', 'rows', 'metrics', 'cli_seconds', 'calls', 'input_tokens', 'output_tokens', 'default_zero_fallbacks')}))
