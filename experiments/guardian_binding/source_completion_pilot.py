"""Matched all46 source-completion review; consumes frozen gold-free requests."""
import argparse
from concurrent.futures import ThreadPoolExecutor
import hashlib
import json
import os
from pathlib import Path
import subprocess
import threading
import urllib.request
from urllib.parse import urlsplit

from guardian_truth.file_lock import process_lock
from guardian_truth.integrated.transport import sha
from guardian_truth.verification.admission import interpret_receipt_v2
from guardian_truth.verification.common import schema_errors, transport_failure
from experiments.guardian_local_a100.providers import backend_endpoint
from experiments.guardian_local_a100.run_local import client_for
from .audit import ReservedClient, _unique_object
from .pilot import context_count

ROOT = Path(__file__).resolve().parents[2]
MODES = ('control', 'completion')


def served_models(base):
    with urllib.request.urlopen(base + '/v1/models', timeout=10) as response:
        return json.loads(response.read()).get('data', [])


def admit(reply, request):
    if transport_failure(reply) or reply.get('finish_reason') != 'stop':
        return dict(status='TECHNICAL_FAILURE', decision=None, binary=None)
    try:
        value = json.loads(reply.get('content') or '', object_pairs_hook=_unique_object)
    except (ValueError, TypeError):
        return dict(status='INVALID_JSON', decision=None, binary=None)
    errors = schema_errors(value, request['response_format']['json_schema']['schema'])
    if errors:
        return dict(status='INVALID_SCHEMA', errors=errors, decision=None, binary=None)
    packet = json.loads(request['messages'][1]['content'])
    result = interpret_receipt_v2(reply, packet)
    decision = result.get('decision')
    return dict(status=result['admission'], decision=decision,
                binary=1 if decision == 'ERROR' else 0 if decision == 'NO_ERROR' else None,
                interpretation=result, authority='MODEL_JUDGMENT', code_certificate=False)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output', type=Path, required=True)
    ap.add_argument('--model-id', required=True)
    ap.add_argument('--workers', type=int, default=8)
    ap.add_argument('--max-calls', type=int, default=100)
    ap.add_argument('--timeout', type=int, default=240)
    a = ap.parse_args()
    if min(a.workers, a.max_calls, a.timeout) < 1:
        raise ValueError('INVALID_BUDGET')
    rows = [json.loads(l) for l in a.input.read_text(encoding='utf-8').splitlines() if l.strip()]
    ids = [r['id'] for r in rows]
    if len(ids) != len(set(ids)):
        raise ValueError('DUPLICATE_INPUT_IDS')
    for row in rows:
        if set(row) != {'id', *MODES, 'source_completion', 'archived_dispatched_key',
                        'control_sha256', 'completion_sha256', 'wire_identical'}:
            raise ValueError('UNEXPECTED_RUNTIME_FIELDS')
        for mode in MODES:
            if sha(row[mode]) != row[mode + '_sha256'] or row[mode]['model'] != a.model_id:
                raise ValueError('FROZEN_REQUEST_MISMATCH')
    endpoint = backend_endpoint('local-llamacpp')
    if urlsplit(endpoint).hostname not in ('127.0.0.1', 'localhost', '::1'):
        raise ValueError('LOCAL_ENDPOINT_REQUIRED')
    base = endpoint.removesuffix('/v1/chat/completions')
    served = next((m for m in served_models(base) if m.get('id') == a.model_id), None)
    if not served or (served.get('meta') or {}).get('n_ctx', 0) < 32768:
        raise ValueError('MODEL_CONTEXT_MISMATCH')
    files = [Path(__file__), Path(__file__).with_name('source_completion.py'), Path(__file__).with_name('pilot.py'),
             Path(__file__).with_name('audit.py'), ROOT / 'src/guardian_truth/verification/admission.py',
             ROOT / 'src/guardian_truth/integrated/reviewer.py']
    config = dict(version='native-source-completion-pilot-v1', expected_ids=ids, modes=list(MODES),
        input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(), endpoint=endpoint, model=a.model_id,
        context_tokens=32768, served_model_meta=served.get('meta'), max_calls=a.max_calls, workers=a.workers,
        timeout=a.timeout, attempt=1, code={str(p.relative_to(ROOT)): hashlib.sha256(p.read_bytes()).hexdigest() for p in files},
        head=subprocess.check_output(['git', 'rev-parse', 'HEAD'], cwd=ROOT).decode().strip())
    a.output.mkdir(parents=True, exist_ok=True)
    manifest, path = a.output / 'manifest.json', a.output / 'records.jsonl'
    with process_lock(a.output / '.phase.lock'):
        if manifest.exists():
            if json.loads(manifest.read_text(encoding='utf-8')) != config:
                raise ValueError('PHASE_FINGERPRINT_CHANGED')
        else:
            if path.exists():
                raise ValueError('UNVERSIONED_RECORDS')
            with manifest.open('x', encoding='utf-8', newline='\n') as stream:
                json.dump(config, stream, indent=2)
        done = set()
        for line in path.read_text(encoding='utf-8').splitlines() if path.exists() else []:
            r = json.loads(line); key = (r['id'], r['mode'])
            if key in done or r['id'] not in ids or r['mode'] not in MODES:
                raise ValueError('INVALID_RESUME_IDS')
            done.add(key)
        client = ReservedClient(client_for('local-llamacpp', a.model_id, a.output / 'cache',
                    max_calls=a.max_calls, timeout=a.timeout), a.output / 'reservations.jsonl', a.max_calls)
        lock = threading.Lock()
        def one(task):
            row, mode = task; request = row[mode]
            record = dict(id=row['id'], mode=mode, request_sha256=sha(request),
                          wire_identical=row['wire_identical'], source_completion=row['source_completion'])
            try:
                count = context_count(request, base)
                if count + request['max_tokens'] + 32 > 32768:
                    reply = dict(content=None, finish_reason=None, transport=dict(status='CONTEXT_NOT_EXECUTED'))
                else:
                    reply = client.call(request, attempt=1, tag='source_completion_' + mode)
                record.update(reply=reply, input_tokens_counted=count, result=admit(reply, request))
            except Exception as exc:
                record.update(exception_type=type(exc).__name__,
                              result=dict(status='TECHNICAL_EXCEPTION', decision=None, binary=None))
            with lock:
                with path.open('a', encoding='utf-8', newline='\n') as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + '\n'); stream.flush(); os.fsync(stream.fileno())
                print(row['id'], mode, record['result']['status'], record['result']['decision'], flush=True)
        tasks = []
        for row in rows:
            modes = MODES if int(hashlib.sha256(row['id'].encode()).hexdigest(), 16) % 2 else tuple(reversed(MODES))
            tasks.extend((row, mode) for mode in modes if (row['id'], mode) not in done)
        with ThreadPoolExecutor(a.workers) as executor:
            list(executor.map(one, tasks))
        actual = [(r['id'], r['mode']) for r in map(json.loads, path.read_text(encoding='utf-8').splitlines())]
        if len(actual) != len(set(actual)) or set(actual) != {(i, m) for i in ids for m in MODES}:
            raise ValueError('INCOMPLETE_FINAL_IDS')
        print('COMPLETE', len(actual), 'reservations', client.reserved, flush=True)


if __name__ == '__main__':
    main()
