"""Fixed-work owned-engine concurrency diagnostic, never pipeline predictions.

Use an external whole-process timeout. Every arm owns a fresh pinned Q8 server,
8 slots of 32768 tokens and 8 CPU threads, irrespective of client concurrency.
"""
from __future__ import annotations

import argparse
from concurrent.futures import FIRST_COMPLETED, ThreadPoolExecutor, wait
import copy
import json
import math
import os
from pathlib import Path
import time
from unittest.mock import patch

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import MODEL, LocalClient, ModelServer
from scripts.qwen_inference_bench import NATIVE_SHA256, digest, native_metrics, write_json

VERSION = 'qwen-fixed-work-engine-scaling-v1'
MODEL_SHA256 = 'aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1'
CPU_ENV = dict(LLAMA_ARG_THREADS='8', LLAMA_ARG_THREADS_BATCH='8', OMP_NUM_THREADS='8')
SLOTS, CONTEXT, REQUESTS, TOKENS, WARMUP_TOKENS = 8, 32768, 8, 256, 16
TEXT = 'A support agent records an ordinary service conversation and explains the available next steps. ' * 120


def request(ordinal, tokens=TOKENS):
    # Early, fixed-width salts prevent exact-client-cache collapse and reduce
    # cross-request prompt reuse. The SAME eight wires are used in both arms.
    return dict(model=MODEL, temperature=0, max_tokens=tokens, ignore_eos=True,
                cache_prompt=False, chat_template_kwargs=dict(enable_thinking=False),
                messages=[dict(role='system', content='Write a detailed numbered paraphrase of the supplied synthetic text.'),
                          dict(role='user', content=f'Nonce {ordinal:08d}.\n{TEXT}')])


def _number(value):
    return type(value) in (int, float) and math.isfinite(value) and value >= 0


def receipt_errors(receipt, wire):
    if not isinstance(receipt, dict):
        return ['INVALID_RECEIPT_SHAPE']
    errors = []
    transport = receipt.get('transport')
    if not isinstance(transport, dict) or transport.get('status') != 200:
        errors.append('TRANSPORT_FAILURE')
    if receipt.get('finish_reason') != 'length':
        errors.append('UNEXPECTED_FINISH')
    usage = receipt.get('usage') if isinstance(receipt.get('usage'), dict) else {}
    timings = receipt.get('timings') if isinstance(receipt.get('timings'), dict) else {}
    if type(usage.get('completion_tokens')) is not int or usage['completion_tokens'] != wire['max_tokens']:
        errors.append('GENERATED_TOKEN_COUNT_MISMATCH')
    if type(usage.get('prompt_tokens')) is not int or usage['prompt_tokens'] < 0:
        errors.append('INVALID_PROMPT_USAGE')
    if type(receipt.get('input_tokens')) is not int or receipt['input_tokens'] < 0:
        errors.append('INVALID_NATIVE_PREFLIGHT')
    elif receipt['input_tokens'] + wire['max_tokens'] > CONTEXT:
        errors.append('CONTEXT_BUDGET_EXCEEDED')
    if receipt.get('request_sha256') != sha(wire) or receipt.get('model') != MODEL:
        errors.append('REQUEST_IDENTITY_MISMATCH')
    if receipt.get('response_model') != MODEL:
        errors.append('RESPONSE_MODEL_MISMATCH')
    if receipt.get('cached') is not False:
        errors.append('UNEXPECTED_CLIENT_CACHE_HIT')
    if not isinstance(receipt.get('content'), str):
        errors.append('MISSING_GENERATED_CONTENT')
    if not all(_number(timings.get(k)) for k in ('prompt_ms', 'predicted_ms')):
        errors.append('INVALID_NATIVE_TIMINGS')
    if type(timings.get('predicted_n')) is not int or timings['predicted_n'] != wire['max_tokens']:
        errors.append('NATIVE_GENERATED_COUNT_MISMATCH')
    if type(timings.get('prompt_n')) is not int or timings['prompt_n'] < 0:
        errors.append('INVALID_NATIVE_PROMPT_COUNT')
    return errors


def _append(path, record):
    with Path(path).open('a', encoding='utf-8', newline='\n') as stream:
        stream.write(json.dumps(record, ensure_ascii=False, allow_nan=False) + '\n')
        stream.flush()
        os.fsync(stream.fileno())


def _call(client, wire, ordinal, tag):
    start = time.monotonic()
    try:
        receipt = client.call(copy.deepcopy(wire), attempt=0, tag=tag)
    except Exception as error:
        receipt = dict(transport=dict(status='EXC', error=type(error).__name__), content=None)
    end = time.monotonic()
    return dict(ordinal=ordinal, request=wire, receipt=receipt, errors=receipt_errors(receipt, wire),
                client_interval_monotonic=dict(start=start, end=end, seconds=end - start))


def _batch(client, wires, concurrency, path):
    records, failed, next_ordinal = [], False, 0
    start = time.monotonic()
    with ThreadPoolExecutor(max_workers=concurrency) as pool:
        pending = {}

        def submit():
            nonlocal next_ordinal
            future = pool.submit(_call, client, wires[next_ordinal], next_ordinal, 'scaling')
            pending[future] = next_ordinal
            next_ordinal += 1

        for _ in range(min(concurrency, len(wires))):
            submit()
        while pending:
            ready, _ = wait(pending, return_when=FIRST_COMPLETED)
            for future in sorted(ready, key=lambda f: pending[f]):
                pending.pop(future)
                if future.cancelled():
                    continue
                record = future.result()
                records.append(record)
                _append(path, record)
                failed = failed or bool(record['errors'])
            if failed:
                for future in pending:
                    future.cancel()
            else:
                while next_ordinal < len(wires) and len(pending) < concurrency:
                    submit()
    return sorted(records, key=lambda r: r['ordinal']), time.monotonic() - start


def summarize(records, batch_seconds):
    good = len(records) == REQUESTS and not any(r['errors'] for r in records)
    receipts = [r['receipt'] if isinstance(r['receipt'], dict) else {} for r in records]
    usage = [r.get('usage') if isinstance(r.get('usage'), dict) else {} for r in receipts]
    count = lambda key: sum(u[key] for u in usage if type(u.get(key)) is int and u[key] >= 0)
    generated, prompt = count('completion_tokens'), count('prompt_tokens')
    timings = [r.get('timings') if isinstance(r.get('timings'), dict) else {} for r in receipts]
    native_valid = all(all(_number(t.get(k)) for k in ('prompt_ms', 'predicted_ms')) for t in timings)
    return dict(status='COMPLETE' if good else 'FAILED', completed_requests=len(records),
                expected_requests=REQUESTS, generated_tokens=generated, expected_generated_tokens=REQUESTS * TOKENS,
                invalid_usage_receipts=sum(any(type(u.get(k)) is not int or u[k] < 0
                                              for k in ('completion_tokens', 'prompt_tokens')) for u in usage),
                prompt_tokens=prompt, batch_wall_seconds=batch_seconds,
                aggregate_output_tokens_per_second=generated / batch_seconds if good and batch_seconds > 0 else None,
                native_prompt_seconds_sum=sum(t['prompt_ms'] for t in timings) / 1000 if native_valid else None,
                native_decode_seconds_sum=sum(t['predicted_ms'] for t in timings) / 1000 if native_valid else None,
                native_interval_contract='Sums of per-request native intervals; may overlap at concurrency 8, not wall time',
                failures=[dict(ordinal=r['ordinal'], errors=r['errors']) for r in records if r['errors']])


def run(root, output, repetitions=1):
    if type(repetitions) is not int or repetitions not in (1, 2):
        raise ValueError('REPETITIONS_MUST_BE_1_OR_2')
    root, output = Path(root), Path(output)
    output.mkdir(parents=True, exist_ok=False)
    results = []
    try:
        identity = dict(model_sha256=digest(root / 'model/Qwen3.8-27B-Q8_0.gguf'),
                        runtime_sha256=digest(root / 'runtime/llama/llama-server'))
        if identity != dict(model_sha256=MODEL_SHA256, runtime_sha256=NATIVE_SHA256):
            raise ValueError('PINNED_MODEL_OR_NATIVE_SHA_MISMATCH')
        wires, warmup = [request(i) for i in range(REQUESTS)], request(99999999, WARMUP_TOKENS)
        code = {p.as_posix(): digest(p) for p in (Path(__file__),
                Path(__file__).with_name('qwen_inference_bench.py'),
                Path(__file__).resolve().parents[1] / 'src/guardian_truth/submission/cli.py')}
        write_json(output / 'protocol.json', dict(version=VERSION, model_alias=MODEL, identity=identity,
            code_sha256=code, repetitions=repetitions, order='1,8 then 8,1 on repetition 2',
            server_slots=SLOTS, context_per_slot=CONTEXT, cpu_env=CPU_ENV,
            fresh_server_and_client_cache_per_arm=True, completion_http_timeout_seconds=90,
            preflight_http_timeout_seconds=20, metrics_http_timeout_seconds=10,
            whole_run_timeout='External operator; no internal whole-run deadline guarantee',
            maximum_completion_attempts=2 * repetitions * (REQUESTS + 1), retries=0,
            batch_requests=wires, batch_request_sha256=[sha(w) for w in wires], warmup_request=warmup,
            warmup_scope='Identical 16-token request on each fresh server, excluded from batch throughput',
            scope='Synthetic fixed-work observed scaling; no policy/quality/gold evaluation or batching-cause proof'))
        for rep in range(repetitions):
            for concurrency in ((1, 8) if rep == 0 else (8, 1)):
                work = output / f'rep{rep + 1}_concurrency{concurrency}'
                work.mkdir()
                phase_start = time.monotonic()
                with patch.dict(os.environ, CPU_ENV), ModelServer(root, work, SLOTS, CONTEXT) as server:
                    startup = time.monotonic() - phase_start
                    client = LocalClient(server.port, CONTEXT, timeout=90, api_key=server.api_key)
                    write_json(work / 'props.json', server.props)
                    (work / 'metrics_before_warmup.txt').write_text(native_metrics(server), encoding='utf-8')
                    warm = _call(client, warmup, -1, 'warmup')
                    write_json(work / 'warmup.json', warm)
                    if warm['errors']:
                        write_json(work / 'calls.json', client.calls)
                        raise RuntimeError('WARMUP_FAILED:' + ','.join(warm['errors']))
                    (work / 'metrics_before_batch.txt').write_text(native_metrics(server), encoding='utf-8')
                    records, seconds = _batch(client, wires, concurrency, work / 'receipts.jsonl')
                    write_json(work / 'calls.json', client.calls)
                    (work / 'metrics_after_batch.txt').write_text(native_metrics(server), encoding='utf-8')
                    summary = dict(summarize(records, seconds), concurrency=concurrency, repetition=rep + 1,
                        startup_seconds=startup, warmup_seconds=warm['client_interval_monotonic']['seconds'],
                        warmup_usage=warm['receipt'].get('usage'), warmup_timings=warm['receipt'].get('timings'),
                        preflight_http=client.preflight_http, completion_http=client.completion_http,
                        client_cache_hits=client.cache_hits)
                summary['whole_arm_seconds_including_shutdown'] = time.monotonic() - phase_start
                write_json(work / 'summary.json', summary)
                results.append(summary)
                print(json.dumps(summary, allow_nan=False), flush=True)
                if summary['status'] != 'COMPLETE':
                    raise RuntimeError('FIXED_WORK_ARM_FAILED')
        comparisons = []
        for rep in range(1, repetitions + 1):
            arms = {r['concurrency']: r for r in results if r['repetition'] == rep}
            comparisons.append(dict(repetition=rep,
                observed_aggregate_tps_ratio_8_vs_1=arms[8]['aggregate_output_tokens_per_second'] / arms[1]['aggregate_output_tokens_per_second'],
                observed_fixed_work_wall_speedup=arms[1]['batch_wall_seconds'] / arms[8]['batch_wall_seconds'],
                generated_tokens_per_arm=REQUESTS * TOKENS,
                conclusion='OBSERVED_SYNTHETIC_SCALING_ONLY',
                limitations='Includes native preflight and client scheduling; no engine-cause attribution or B2 speed/F1 claim'))
        report = dict(version=VERSION, status='COMPLETE', arms=results, comparisons=comparisons)
        write_json(output / 'report.json', report)
        return report
    except Exception as error:
        write_json(output / 'STOPPED.json', dict(version=VERSION, status='STOPPED',
            error_type=type(error).__name__, reason=str(error), completed_arms=results))
        raise


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repetitions', type=int, choices=(1, 2), default=1)
    args = parser.parse_args(argv)
    run(args.root, args.output, args.repetitions)


if __name__ == '__main__':
    main()
