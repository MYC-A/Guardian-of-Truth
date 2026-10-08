"""Reproject a complete frozen runtime trace without HTTP or old-output edits.

Gold is used only in this research scorer after inference projection. The
submission package does not include this script or any reference labels.
"""
import argparse
import hashlib
import json
from pathlib import Path
import subprocess
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def metrics(gold, predictions):
    tp = sum(y == p == 1 for y, p in zip(gold, predictions))
    fp = sum(y == 0 and p == 1 for y, p in zip(gold, predictions))
    fn = sum(y == 1 and p == 0 for y, p in zip(gold, predictions))
    tn = sum(y == p == 0 for y, p in zip(gold, predictions))
    return dict(TP=tp, FP=fp, FN=fn, TN=tn,
                F1=2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else 0)


def score(labels, rows):
    invalid = [i for i, r in enumerate(rows) if type(r.get('binary')) is not int or r['binary'] not in (0, 1)]
    if not invalid:
        return dict(complete=True, metrics=metrics(labels, [r['binary'] for r in rows]))
    # Bounds apply to the full denominator. They are hypothetical scores,
    # never generated predictions and never saved as submission labels.
    valid = {i for i in range(len(rows)) if i not in invalid}
    best = [r['binary'] if i in valid else labels[i] for i, r in enumerate(rows)]
    worst = [r['binary'] if i in valid else 1 - labels[i] for i, r in enumerate(rows)]
    return dict(complete=False, metrics=None, invalid_ids=[rows[i]['id'] for i in invalid],
                hypothetical_lower=metrics(labels, worst), hypothetical_upper=metrics(labels, best))


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--traces', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--expected-input-sha256', required=True, help='Frozen phase input fingerprint, not an inferred ID match')
    a = ap.parse_args()
    def deny_network(*args, **kwargs):
        raise RuntimeError('OFFLINE_REPROJECTION_NETWORK_FORBIDDEN')
    socket.create_connection = deny_network
    socket.socket.connect = deny_network
    socket.socket.connect_ex = deny_network
    from guardian_truth.submission.cli import finalize_trace, read_rows, row_fingerprint, write_predictions
    import pandas as pd
    input_sha256 = hashlib.sha256(a.input.read_bytes()).hexdigest()
    if input_sha256 != a.expected_input_sha256:
        raise ValueError('FROZEN_INPUT_FINGERPRINT_MISMATCH')
    input_rows = read_rows(a.input)
    identifiers = [r['id'] for r in input_rows]
    original = [json.loads(s) for s in a.traces.read_text(encoding='utf-8').splitlines() if s.strip()]
    index = {}
    for row in original:
        if row['id'] in index:
            raise ValueError('DUPLICATE_TRACE_ID')
        index[row['id']] = row
    if set(index) != set(identifiers):
        raise ValueError('INCOMPLETE_OR_UNEXPECTED_TRACE_IDS')
    original = [index[i] for i in identifiers]
    legacy_rows = 0
    for source, trace in zip(input_rows, original):
        if 'input_row_sha256' not in trace:
            legacy_rows += 1
        elif trace['input_row_sha256'] != row_fingerprint(source):
            raise ValueError('TRACE_SOURCE_FINGERPRINT_MISMATCH: ' + source['id'])
    revised = [finalize_trace(r) for r in original]
    # Only now access gold, entirely outside the runtime projection.
    gold = pd.read_parquet(a.input) if a.input.read_bytes()[:4] == b'PAR1' else pd.read_csv(a.input, dtype={'id': str})
    if 'label' not in gold or any(type(x) not in (int, bool) or x not in (0, 1) for x in gold['label'].tolist()):
        raise ValueError('BINARY_REFERENCE_LABELS_REQUIRED')
    by_id = dict(zip(gold['id'], gold['label'].tolist()))
    labels = [by_id[i] for i in identifiers]
    before, after = score(labels, original), score(labels, revised)
    report = dict(version='submission-terminal-projection-2', rows=len(identifiers),
                  input_sha256=input_sha256,
                  row_fingerprints_verified=len(original) - legacy_rows,
                  legacy_without_row_fingerprint=legacy_rows,
                  input_binding='PHASE_HASH_ONLY_LEGACY_ROWS_PRESENT' if legacy_rows else 'ROW_HASH_VERIFIED',
                  traces_sha256=hashlib.sha256(a.traces.read_bytes()).hexdigest(),
                  commit=subprocess.check_output(['git', '-C', str(ROOT), 'rev-parse', 'HEAD'], text=True).strip(),
                  model_calls=0, before=before, after=after,
                  changes=[dict(id=x['id'], before=x.get('binary'), after=y.get('binary'),
                                before_error=x.get('error'), after_error=y.get('error'))
                           for x, y in zip(original, revised) if x.get('binary') != y.get('binary') or x.get('error') != y.get('error')])
    a.output_dir.mkdir(parents=True, exist_ok=False)
    (a.output_dir / 'report.json').write_text(json.dumps(report, indent=2, ensure_ascii=False), encoding='utf-8')
    with (a.output_dir / 'traces.jsonl').open('x', encoding='utf-8', newline='\n') as f:
        for row in revised:
            f.write(json.dumps(row, ensure_ascii=False) + '\n')
    if after['complete']:
        write_predictions(a.output_dir / 'predictions.parquet', [dict(id=r['id'], label=r['binary']) for r in revised])
    print(json.dumps(report, ensure_ascii=False))


if __name__ == '__main__':
    main()
