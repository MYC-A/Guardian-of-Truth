"""Exact legacy reviewer-wire capture and an opt-in, bounded native-engine screen.

prepare is offline. run starts owned local servers and is NEVER a pipeline-F1 test.
Use PYTHONPATH=src:. from the checkout (PowerShell: src;.).
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import copy
import cProfile
from contextlib import ExitStack
import hashlib
import io
import json
import os
from pathlib import Path
import pstats
import time
from unittest.mock import patch
import urllib.request
import zipfile

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, LocalClient, ModelServer, predict_one, read_rows, row_fingerprint
from guardian_truth.verification.admission import interpret_receipt_v2

VERSION = 'exact-legacy-reviewer-screen-v1'
NATIVE_SHA256 = '1ed587e4c0b30bb4221268b2fb4934813eb88abc8e58d3df978e22dcc0b57d2f'
CONFIGS = {
    'base': dict(workers=8, slots=8, spec_type=None),
    'queue16': dict(workers=16, slots=8, spec_type=None),
    'ngram': dict(workers=8, slots=8, spec_type='ngram-mod'),
    'ngram_queue16': dict(workers=16, slots=8, spec_type='ngram-mod'),
}


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            h.update(chunk)
    return h.hexdigest()


def write_json(path, value):
    with Path(path).open('x', encoding='utf-8', newline='\n') as stream:
        json.dump(value, stream, ensure_ascii=False, indent=2)
        stream.write('\n')


class Captured(BaseException):
    """Bypass production Exception recovery; no inferred/mocked verdict needed."""
    def __init__(self, request, attempt):
        self.request, self.attempt = copy.deepcopy(request), attempt


class CaptureClient:
    model = MODEL

    def __init__(self, calls):
        self.calls = {}
        for receipt in calls:
            key = receipt['key']
            if key in self.calls:
                raise ValueError('DUPLICATE_EXPORTED_CALL_KEY')
            self.calls[key] = receipt

    def call(self, request, attempt=0, tag=''):
        key = sha(dict(model=MODEL, request=request, attempt=attempt))
        if key not in self.calls:
            raise ValueError('EXACT_CAPTURE_CACHE_MISS:' + tag)
        receipt = self.calls[key]
        if receipt['tag'] != tag or receipt['request_sha256'] != sha(request) or receipt['attempt'] != attempt:
            raise ValueError('EXPORTED_CALL_IDENTITY_MISMATCH')
        if tag == 'review':
            raise Captured(request, attempt)
        if tag != 'pre_blind':
            raise ValueError('UNEXPECTED_PRE_REVIEW_CALL:' + tag)
        return copy.deepcopy(receipt)


def select_quantiles(wires, count):
    """Select by actual baseline input length, never label/prediction/case name."""
    if type(count) is not int or count < 2 or count > len(wires):
        raise ValueError('INVALID_SAMPLE_SIZE')
    ordered = sorted(wires, key=lambda r: (r['input_tokens'], r['ordinal']))
    indexes = [round(i * (len(wires) - 1) / (count - 1)) for i in range(count)]
    selected = {ordered[i]['ordinal'] for i in indexes}
    if len(selected) != count:
        raise ValueError('NON_UNIQUE_QUANTILE_SELECTION')
    # Actual submission order retained; includes both the minimum and maximum.
    return [r['id'] for r in wires if r['ordinal'] in selected]


def prepare(bundle, input_path, output, count=16):
    rows = read_rows(input_path)  # Explicitly drops labels.
    with zipfile.ZipFile(bundle) as archive:
        manifest = json.loads(archive.read('export_manifest.json'))
        names = archive.namelist()
        if len(names) != len(set(names)) or set(manifest) != set(names) - {'export_manifest.json'}:
            raise ValueError('EXPORT_MANIFEST_MEMBER_SET_MISMATCH')
        for name, expected in manifest.items():
            raw = archive.read(name)
            if len(raw) != expected['bytes'] or hashlib.sha256(raw).hexdigest() != expected['sha256']:
                raise ValueError('EXPORT_MEMBER_HASH_MISMATCH:' + name)
        prefix = 'legacy/rep1/receipts/'
        run = json.loads(archive.read(prefix + 'run.json'))
        calls = json.loads(archive.read(prefix + 'calls.json'))
        traces = [json.loads(line) for line in archive.read(prefix + 'traces.jsonl').decode('utf-8').splitlines() if line.strip()]
    ids = [r['id'] for r in rows]
    trace_ids = [r['id'] for r in traces]
    if len(trace_ids) != len(set(trace_ids)) or set(trace_ids) != set(ids) or len(calls) != run['calls']:
        raise ValueError('INCOMPLETE_CAPTURE_EXPORT')
    if run['input_sha256'] != digest(input_path):
        raise ValueError('INPUT_SHA_MISMATCH')
    index = {r['id']: r for r in traces}
    client, wires = CaptureClient(calls), []
    profiler = cProfile.Profile()
    start = time.monotonic()
    # The capture must be entirely offline even if a future adapter changes.
    with ExitStack() as stack:
        for target in ('socket.socket.connect', 'socket.socket.connect_ex', 'socket.create_connection'):
            stack.enter_context(patch(target, side_effect=AssertionError('NETWORK_FORBIDDEN_IN_CAPTURE')))
        profiler.enable()
        try:
            for ordinal, row in enumerate(rows):
                trace = index[row['id']]
                if trace['input_row_sha256'] != row_fingerprint(row):
                    raise ValueError('ROW_FINGERPRINT_MISMATCH')
                try:
                    predict_one(row, client, None, 'legacy')
                except Captured as captured:
                    receipt = trace['primary_receipt']
                    if captured.attempt != receipt['attempt'] or sha(captured.request) != receipt['request_sha256']:
                        raise ValueError('PRIMARY_WIRE_CAPTURE_MISMATCH')
                    wires.append(dict(id=row['id'], ordinal=ordinal, input_row_sha256=row_fingerprint(row),
                        request=captured.request, attempt=captured.attempt, request_sha256=sha(captured.request),
                        input_tokens=receipt['input_tokens']))
                else:
                    raise ValueError('PRIMARY_WIRE_NOT_CAPTURED')
        finally:
            profiler.disable()
    seconds = time.monotonic() - start
    plan = dict(version=VERSION, model=MODEL, scope='Reviewer-only native engine screen; not pipeline predictions or F1',
        input_sha256=digest(input_path), export_sha256=digest(bundle), rows=len(wires),
        capture_seconds=seconds, capture_scope='Profiled local reconstruction including source parsing; excludes export loading',
        selected_ids=select_quantiles(wires, count), selection='Actual input-token quantiles including min/max; original row order',
        wires=wires)
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    write_json(output / 'plan.json', plan)
    stream = io.StringIO()
    pstats.Stats(profiler, stream=stream).strip_dirs().sort_stats('cumulative').print_stats(35)
    (output / 'capture_profile.txt').write_text(stream.getvalue(), encoding='utf-8', newline='\n')
    write_json(output / 'capture_summary.json', {k: v for k, v in plan.items() if k != 'wires'})
    return plan


def validate_plan(plan):
    if plan.get('version') != VERSION or plan.get('model') != MODEL:
        raise ValueError('UNSUPPORTED_PLAN_IDENTITY')
    wires, selected = plan['wires'], plan['selected_ids']
    ids = [w['id'] for w in wires]
    if (len(ids) != len(set(ids)) or len(ids) != plan['rows']
            or [w['ordinal'] for w in wires] != list(range(len(wires)))
            or selected != select_quantiles(wires, len(selected))):
        raise ValueError('INVALID_PLAN_ID_SET_OR_SELECTION')
    for wire in wires:
        request = wire['request']
        if request.get('model') != MODEL or sha(request) != wire['request_sha256'] or wire['attempt'] != 0:
            raise ValueError('INVALID_FROZEN_WIRE')
        if (type(wire['input_tokens']) is not int or wire['input_tokens'] < 0
                or type(request['max_tokens']) is not int or request['max_tokens'] < 1
                or wire['input_tokens'] + request['max_tokens'] > 32768):
            raise ValueError('PLAN_EXCEEDS_FROZEN_CONTEXT')
        messages = request['messages']
        if (len(messages) != 2 or messages[0]['role'] != 'system' or messages[1]['role'] != 'user'
                or not isinstance(json.loads(messages[1]['content']), dict)):
            raise ValueError('INVALID_REVIEW_PACKET_SHAPE')
    return [w for w in wires if w['id'] in set(selected)]


def native_metrics(server):
    # Reuse the same loopback-only, redirect-free transport boundary.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    req = urllib.request.Request(f'http://127.0.0.1:{server.port}/metrics',
                                 headers={'Authorization': 'Bearer ' + server.api_key})
    with opener.open(req, timeout=10) as response:
        return response.read().decode('utf-8')


def compare_receipts(base, candidate):
    indexes = [{r['id']: r for r in records} for records in (base, candidate)]
    if any(len(index) != len(records) for index, records in zip(indexes, (base, candidate))) or set(indexes[0]) != set(indexes[1]):
        raise ValueError('UNPAIRED_SCREEN_IDS')
    flips = []
    for identifier, before in indexes[0].items():
        after = indexes[1][identifier]
        if before['request_sha256'] != after['request_sha256']:
            raise ValueError('UNPAIRED_SCREEN_REQUEST')
        fields = ('decision', 'admission', 'admitted')
        changed = [key for key in fields if before.get(key) != after.get(key)]
        if changed:
            flips.append(dict(id=identifier, changed=changed,
                before={k: before.get(k) for k in fields}, after={k: after.get(k) for k in fields}))
    return dict(rows=len(base), decision_flips=sum('decision' in f['changed'] for f in flips),
        admission_flips=sum('admission' in f['changed'] for f in flips),
        admitted_payload_flips=sum('admitted' in f['changed'] for f in flips), flips=flips,
        caveat='Payload/text differences require source review; they are not automatically cause-quality regressions')


def run(plan_path, root, output, arms, repetitions=1):
    plan = json.loads(Path(plan_path).read_text(encoding='utf-8'))
    selected = validate_plan(plan)
    if repetitions not in (1, 2) or len(arms) != len(set(arms)) or not arms or any(a not in CONFIGS for a in arms):
        raise ValueError('INVALID_BOUNDED_SCREEN_MATRIX')
    if 'base' not in arms or len(selected) * len(arms) * repetitions > 128:
        raise ValueError('BASE_REQUIRED_OR_SCREEN_CALL_CAP_EXCEEDED')
    output = Path(output)
    output.mkdir(parents=True, exist_ok=False)
    root = Path(root)
    # Hash the large model only once before all phases, not between timed arms.
    identity = dict(model_sha256=digest(root / 'model/Qwen3.8-27B-Q8_0.gguf'),
                    runtime_sha256=digest(root / 'runtime/llama/llama-server'))
    if identity['model_sha256'] != 'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1':
        raise ValueError('FROZEN_MODEL_FILE_MISMATCH')
    if identity['runtime_sha256'] != NATIVE_SHA256:
        raise ValueError('FROZEN_NATIVE_FILE_MISMATCH')
    write_json(output / 'protocol.json', dict(version=VERSION, plan_sha256=digest(plan_path),
        identity=identity, configs={a: CONFIGS[a] for a in arms}, repetitions=repetitions,
        maximum_completions=len(selected) * len(arms) * repetitions, retry=0,
        fresh_server_each_arm=True, warmup=False, order='Given arms then reverse on repetition 2',
        cpu_env=dict(LLAMA_ARG_THREADS='8', LLAMA_ARG_THREADS_BATCH='8', OMP_NUM_THREADS='8'),
        context_per_slot=32768, scope=plan['scope'],
        acceptance='Screen only: >=10% batch speed gain, zero transport/context/schema/admission regressions; then full paired valid46 required'))
    results, paired = [], {}
    for rep in range(repetitions):
        for arm in (arms if rep == 0 else list(reversed(arms))):
            config = CONFIGS[arm]
            work = output / f'{arm}_rep{rep + 1}'
            work.mkdir()
            phase_start = time.monotonic()
            with patch.dict(os.environ, dict(LLAMA_ARG_THREADS='8', LLAMA_ARG_THREADS_BATCH='8', OMP_NUM_THREADS='8')), \
                 ModelServer(root, work, config['slots'], 32768, spec_type=config['spec_type']) as server:
                startup = time.monotonic() - phase_start
                client = LocalClient(server.port, 32768, api_key=server.api_key)
                (work / 'metrics_before.txt').write_text(native_metrics(server), encoding='utf-8')
                start = time.monotonic()
                receipts = []
                with ThreadPoolExecutor(max_workers=config['workers']) as pool:
                    pending = {pool.submit(client.call, w['request'], w['attempt'], 'review'): w for w in selected}
                    for future in as_completed(pending):
                        wire, receipt = pending[future], future.result()
                        packet = json.loads(wire['request']['messages'][1]['content'])
                        admission = interpret_receipt_v2(receipt, packet)
                        record = dict(id=wire['id'], request_sha256=wire['request_sha256'], receipt=receipt,
                            decision=admission.get('decision'), admission=admission.get('admission'),
                            admitted=admission.get('admitted'))
                        receipts.append(record)
                        with (work / 'receipts.jsonl').open('a', encoding='utf-8', newline='\n') as stream:
                            stream.write(json.dumps(record, ensure_ascii=False) + '\n')
                batch_seconds = time.monotonic() - start
                (work / 'metrics_after.txt').write_text(native_metrics(server), encoding='utf-8')
                write_json(work / 'props.json', server.props)
            summary = dict(arm=arm, repetition=rep + 1, rows=len(receipts), startup_seconds=startup,
                batch_seconds=batch_seconds, whole_phase_seconds=time.monotonic() - phase_start,
                input_tokens=sum((r['receipt'].get('usage') or {}).get('prompt_tokens', 0) for r in receipts),
                output_tokens=sum((r['receipt'].get('usage') or {}).get('completion_tokens', 0) for r in receipts),
                transport_failures=sum((r['receipt'].get('transport') or {}).get('status') != 200 for r in receipts),
                non_stop=sum(r['receipt'].get('finish_reason') != 'stop' for r in receipts),
                unadmitted=sum(r['admission'] != 'ADMITTED' for r in receipts),
                preflight_http=client.preflight_http, completion_http=client.completion_http,
                scope=plan['scope'])
            write_json(work / 'summary.json', summary)
            paired[(rep, arm)] = (summary, receipts)
            results.append(summary)
            print(json.dumps(summary), flush=True)
            # One failed transport stops the screen rather than spending more GPU.
            if summary['transport_failures']:
                write_json(output / 'STOPPED.json', dict(reason='TRANSPORT_FAILURE', completed=results))
                return results
    write_json(output / 'results.json', results)
    comparisons = []
    for rep in range(repetitions):
        baseline, base_receipts = paired[(rep, 'base')]
        for arm in arms:
            if arm == 'base':
                continue
            candidate, candidate_receipts = paired[(rep, arm)]
            comparisons.append(dict(arm=arm, repetition=rep + 1,
                batch_speedup=baseline['batch_seconds'] / candidate['batch_seconds'],
                baseline=baseline, candidate=candidate,
                reviewer_comparison=compare_receipts(base_receipts, candidate_receipts),
                accepted=False, status='SCREEN_ONLY_FULL_PIPELINE_COMPARISON_REQUIRED'))
    write_json(output / 'paired.json', comparisons)
    return results


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    commands = parser.add_subparsers(dest='command', required=True)
    capture = commands.add_parser('prepare')
    capture.add_argument('--bundle', type=Path, required=True)
    capture.add_argument('--input', type=Path, required=True)
    capture.add_argument('--output', type=Path, required=True)
    capture.add_argument('--sample-size', type=int, default=16)
    bench = commands.add_parser('run')
    bench.add_argument('--plan', type=Path, required=True)
    bench.add_argument('--root', type=Path, required=True)
    bench.add_argument('--output', type=Path, required=True)
    bench.add_argument('--arms', nargs='+', choices=list(CONFIGS), default=['base', 'queue16', 'ngram'])
    bench.add_argument('--repetitions', type=int, choices=(1, 2), default=1)
    args = parser.parse_args()
    if args.command == 'prepare':
        plan = prepare(args.bundle, args.input, args.output, args.sample_size)
        print(json.dumps({k: plan[k] for k in ('rows', 'capture_seconds', 'selected_ids')}))
    else:
        run(args.plan, args.root, args.output, args.arms, args.repetitions)


if __name__ == '__main__':
    main()
