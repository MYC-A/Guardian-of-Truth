"""Replay complete B2 processing using exact frozen request/attempt receipts.

This verifies processing reproducibility, not new model quality or independent
provider authentication. Missing requests are fatal; no network fallback exists.
"""
import argparse
import copy
import hashlib
import json
from pathlib import Path
import socket
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--expected-input-sha256', required=True)
    ap.add_argument('--calls', type=Path, required=True)
    ap.add_argument('--traces', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--primary-contract', choices=['reason-last', 'decision-first'], default='reason-last')
    ap.add_argument('--retry-primary', action='store_true')
    a = ap.parse_args()
    if a.output.exists():
        raise ValueError('REPLAY_OUTPUT_ALREADY_EXISTS')
    if hashlib.sha256(a.input.read_bytes()).hexdigest() != a.expected_input_sha256:
        raise ValueError('FROZEN_INPUT_FINGERPRINT_MISMATCH')
    def deny(*args, **kwargs):
        raise RuntimeError('RAW_REPLAY_NETWORK_FORBIDDEN')
    socket.create_connection = socket.socket.connect = socket.socket.connect_ex = deny
    from guardian_truth.integrated.transport import sha
    from guardian_truth.submission.cli import MODEL, finalize_trace, predict_one, read_rows
    from guardian_truth.v6fix.pipeline import Layers
    rows = read_rows(a.input)
    previous_rows = [json.loads(s) for s in a.traces.read_text(encoding='utf-8').splitlines() if s.strip()]
    expected = {r['id']: r for r in previous_rows}
    if len(expected) != len(previous_rows) or set(expected) != {r['id'] for r in rows}:
        raise ValueError('TRACE_IDS_MISMATCH')
    frozen = json.loads(a.calls.read_text(encoding='utf-8'))
    records = {}
    for r in frozen:
        if r['key'] in records:
            raise ValueError('DUPLICATE_FROZEN_REQUEST_KEY')
        records[r['key']] = r
    class Client:
        model = MODEL
        primary_contract = a.primary_contract
        primary_recovery_enabled = a.retry_primary
        used = set()
        lookups = 0
        def call(self, request, attempt=0, tag=''):
            self.lookups += 1
            key = sha(dict(model=MODEL, request=request, attempt=attempt))
            if key not in records:
                raise ValueError('EXACT_REQUEST_NOT_IN_FROZEN_RECEIPTS: ' + tag)
            rec = records[key]
            if rec['request_sha256'] != sha(request) or rec['attempt'] != attempt or rec['model'] != MODEL or rec['tag'] != tag:
                raise ValueError('FROZEN_REQUEST_METADATA_MISMATCH')
            self.used.add(key)
            return copy.deepcopy(rec)
    client = Client()
    layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700)
    mismatches = []
    predictions = []
    for row in rows:
        fresh = predict_one(row, client, layers)
        prior = finalize_trace(expected[row['id']])
        fields = ('binary', 'owner', 'accusation')
        if any(fresh.get(k) != prior.get(k) for k in fields):
            mismatches.append(dict(id=row['id'], replay={k: fresh.get(k) for k in fields},
                                   frozen={k: prior.get(k) for k in fields}))
        predictions.append(dict(id=row['id'], binary=fresh['binary']))
    report = dict(scope='same raw processing; not new inference', rows=len(rows), actual_http_calls=0,
                  primary_contract=a.primary_contract, primary_recovery_enabled=a.retry_primary,
                  exact_request_lookups=client.lookups, unique_exact_requests=len(client.used),
                  frozen_records=len(records), unused_records=len(set(records) - client.used),
                  input_sha256=a.expected_input_sha256,
                  calls_sha256=hashlib.sha256(a.calls.read_bytes()).hexdigest(),
                  traces_sha256=hashlib.sha256(a.traces.read_bytes()).hexdigest(),
                  cli_sha256=hashlib.sha256((ROOT / 'src/guardian_truth/submission/cli.py').read_bytes()).hexdigest(),
                  mismatches=mismatches, predictions=predictions)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8') as handle:
        json.dump(report, handle, indent=2, ensure_ascii=False)
    print(json.dumps({k: v for k, v in report.items() if k != 'predictions'}, ensure_ascii=False))
    if mismatches:
        raise RuntimeError('RAW_REPLAY_DIFFERENCE')


if __name__ == '__main__':
    main()
