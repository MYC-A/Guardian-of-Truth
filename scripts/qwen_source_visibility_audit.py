"""Reconstruct saved B2 requests without HTTP and audit native source completion.

Checks both the caller's original request hash and the exact dispatched cache key.
This is evidence availability, never an inferred new prediction or oracle gain.
"""
import argparse
from collections import Counter
import io
import json
from pathlib import Path
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'src'), str(ROOT)]
from experiments.guardian_addons.variants2 import Hook2
from experiments.guardian_binding.source_completion import complete
from guardian_truth.integrated.transport import sha
from guardian_truth.repair.v5 import ARMS, run_v5

REF = '51160fcd0b7b9354f8a63615430aeae0c95b591a'
BASE = 'outputs/guardian_local_a100/llamacpp/qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459/runs/'


class Captured(Exception):
    pass


class Client:
    def __init__(self, record):
        self.record = record
        self.request = None

    def call(self, request, attempt=0, tag=''):
        if tag == 'pre_blind':
            saved = next(s for s in self.record['pre_steps'] if s['tag'] == tag)
            return dict(content=saved['raw_content'], usage=saved.get('usage'),
                        transport=saved.get('transport'), finish_reason=saved.get('finish_reason'), cached=True)
        if tag != 'review':
            raise ValueError('UNEXPECTED_CALL:' + tag)
        self.request = request
        raise Captured()


class Hook(Hook2):
    def call(self, request, attempt=0, tag=''):
        if tag == 'review':
            self.original_request = request
        return super().call(request, attempt=attempt, tag=tag)


def inspect(row, record):
    client = Client(record)
    hook = Hook(client, 'blind2', record['model'], original_row=row,
                max_tokens=3400, max_request_bytes=60000)
    try:
        run_v5(row, hook, flags=ARMS['R_fix'], provider='local-llamacpp', model=record['model'], attempt=0)
    except Captured:
        pass
    if client.request is None:
        return dict(id=row['id'], status='NO_DISPATCHED_REVIEW')
    saved = next(s for s in record['rec']['A']['steps'] if s.get('tag') == 'review')
    if sha(hook.original_request) != saved['request_sha256']:
        raise ValueError('CALLER_REQUEST_HASH_MISMATCH:' + row['id'])
    endpoint = 'http://127.0.0.1:8081/v1/chat/completions'
    key = sha(dict(provider='local-llamacpp', endpoint=endpoint,
                   model=record['model'], request=client.request, attempt=0))
    if key != saved['key']:
        raise ValueError('DISPATCH_CACHE_KEY_MISMATCH:' + row['id'])
    packet = json.loads(client.request['messages'][1]['content'])
    augmented, receipt = complete(row, packet)
    return dict(id=row['id'], status='EXACT_REQUEST_RECONSTRUCTED', binary=record.get('binary'),
                original_request_sha256=saved['request_sha256'], dispatched_request_sha256=sha(client.request),
                dispatched_cache_key=key, history_before=[s['source_id'] for s in packet['history']],
                completion=receipt, added_sources=[s for s in augmented['history']
                    if s['source_id'] in receipt['sources_added'] + receipt['sources_expanded']])


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    def blob(path):
        return subprocess.check_output(['git', 'show', REF + ':' + path], cwd=ROOT)
    import pandas as pd
    rows = [r._asdict() for r in pd.read_parquet(io.BytesIO(blob('valid.parquet'))).itertuples(index=False)]
    records = {r['id']: r for r in map(json.loads, blob(BASE + 'valid46/B2_rep1.jsonl').splitlines())}
    if set(records) != {r['id'] for r in rows}:
        raise ValueError('BASELINE_INPUT_COVERAGE_MISMATCH')
    out = [dict(inspect(row, records[row['id']]), label=int(row['label'])) for row in rows]
    result = dict(ref=REF, network_calls=0, rows=len(out), status_counts=dict(Counter(r['status'] for r in out)),
                  interpretation='Source visibility diagnostic; no automatic predictions or semantic closure', records=out)
    a.output.parent.mkdir(parents=True, exist_ok=True)
    with a.output.open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(result, stream, ensure_ascii=False, indent=2)
    print(result['status_counts'])
    print('rows with added native sources', sum(bool(r.get('added_sources')) for r in out))


if __name__ == '__main__':
    main()
