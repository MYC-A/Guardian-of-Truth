"""Cascade CLI: triage every row by logprobs, escalate by priority to B2 within a wall deadline.

    python -m guardian_truth.cascade.cli --input valid.parquet --output out.parquet \
        --root /workspace/guardian/runtime --mode cascade --deadline 1680

Modes:
  triage-only  one-token triage for all rows (calibration / fastest profile);
  cascade      triage, then B2 (unchanged predict_one) in priority order while
               the remaining budget admits another row.
Only id/prompt/response are read. Labels are never read here.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import os
from pathlib import Path
import sys
import tempfile
import time

from guardian_truth.cascade import triage
from guardian_truth.cascade.backend import TriageClient, VllmLocalClient, VllmServer
from guardian_truth.cascade.controller import Dispatcher, Estimator, Policy, final_label, priority
from guardian_truth.submission.cli import MODEL, LocalClient, ModelServer, read_rows, write_predictions


def triage_row(client, row, views, backend, max_chars):
    scores, receipts = {}, []
    for view in views:
        limit, value = max_chars, None
        for attempt in range(2):
            request, info = triage.build_request(row, view, MODEL, max_chars=limit, backend=backend)
            data, record = client.complete(request, tag=f'triage:{view}')
            record.update(id=row['id'], view=view, attempt=attempt, fit=info)
            receipts.append(record)
            if data is not None:
                value = triage.score_view(data, view)
                record['p'] = value
                break
            if record.get('http_status') == 400:  # context overflow: shrink once
                limit //= 2
                continue
            break
        scores[view] = value
    return triage.combine(scores.values()), scores, receipts


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--output-format', choices=['parquet', 'csv'], default='parquet')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--mode', choices=['triage-only', 'cascade'], default='cascade')
    parser.add_argument('--backend', choices=['llamacpp', 'vllm'], default='llamacpp')
    parser.add_argument('--vllm-python', default=sys.executable)
    parser.add_argument('--vllm-model', type=Path, help='Local HF-format checkpoint directory (offline)')
    parser.add_argument('--vllm-quantization')
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--slots', type=int)
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--views', default='violation,compliance')
    parser.add_argument('--triage-max-chars', type=int, default=60000)
    parser.add_argument('--deadline', type=float, default=1680.0, help='Whole-process wall budget, seconds')
    parser.add_argument('--reserve', type=float, default=60.0)
    parser.add_argument('--b2-prior-seconds', type=float, default=300.0)
    parser.add_argument('--direct-threshold', type=float, default=0.5)
    parser.add_argument('--or-threshold', type=float)
    parser.add_argument('--skip-below', type=float)
    parser.add_argument('--pre-profile', choices=['legacy', 'dedup', 'compact'], default='legacy')
    options = parser.parse_args(argv)
    views = [v for v in options.views.split(',') if v]
    if not views or any(v not in triage.VIEWS for v in views):
        parser.error('unknown view')
    if Path(options.output).exists():
        parser.error('output already exists; choose a fresh path')
    if options.backend == 'vllm' and options.vllm_model is None:
        parser.error('--vllm-model is required for the vllm backend')
    deadline = started + options.deadline
    slots = options.slots or options.workers
    rows = read_rows(options.input)
    by_id = {r['id']: r for r in rows}
    work = options.work_dir or Path(tempfile.mkdtemp(prefix='guardian-cascade-'))
    work.mkdir(parents=True, exist_ok=True)
    policy = Policy(options.direct_threshold, options.or_threshold, options.skip_below)
    report = dict(version=triage.VERSION, mode=options.mode, backend=options.backend, rows=len(rows),
                  model=MODEL, workers=options.workers, slots=slots, context=options.context, views=views,
                  policy=policy.__dict__, deadline=options.deadline, reserve=options.reserve,
                  input_sha256=hashlib.sha256(Path(options.input).read_bytes()).hexdigest())
    abandoned = []
    if options.backend == 'llamacpp':
        server = ModelServer(options.root, work, slots, options.context)
    else:
        server = VllmServer(options.vllm_python, options.vllm_model, work, slots, options.context,
                            quantization=options.vllm_quantization)
    with server:
        report['startup_seconds'] = round(time.monotonic() - started, 2)
        base = f'http://127.0.0.1:{server.port}'
        tclient = TriageClient(base, server.api_key)
        scores, view_scores = {}, {}
        t0 = time.monotonic()
        with ThreadPoolExecutor(max_workers=options.workers) as pool:
            futures = {pool.submit(triage_row, tclient, row, views, options.backend, options.triage_max_chars):
                       row['id'] for row in rows}
            for future in as_completed(futures):
                identifier = futures[future]
                try:
                    p, per_view, _ = future.result()
                except Exception:
                    p, per_view = None, {}
                scores[identifier], view_scores[identifier] = p, per_view
        report['triage_seconds'] = round(time.monotonic() - t0, 2)
        with (work / 'triage_scores.jsonl').open('w', encoding='utf-8') as f:
            for row in rows:
                f.write(json.dumps(dict(id=row['id'], p=scores.get(row['id']), views=view_scores.get(row['id'])),
                                   ensure_ascii=False) + '\n')
        (work / 'triage_calls.json').write_text(json.dumps(tclient.calls, ensure_ascii=False, default=str),
                                                encoding='utf-8')
        b2 = {}
        if options.mode == 'cascade':
            from guardian_truth.submission.cli import predict_one
            from guardian_truth.v6fix.pipeline import Layers
            client_class = LocalClient if options.backend == 'llamacpp' else VllmLocalClient
            client = client_class(server.port, options.context, api_key=server.api_key)
            layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700,
                            tolerate_component_errors=True)
            traces_path = work / 'b2_traces.jsonl'

            def run_row(identifier):
                trace = predict_one(by_id[identifier], client, layers, options.pre_profile)
                with traces_path.open('a', encoding='utf-8') as f:
                    f.write(json.dumps(trace, ensure_ascii=False, default=str) + '\n')
                if (trace.get('output_recovery') or {}).get('mode') == 'DEFAULT_ZERO':
                    return None  # B2 failed: the triage decides this row
                return trace.get('binary')

            order = priority(scores, policy)
            dispatcher = Dispatcher(run_row, options.workers, deadline, options.reserve,
                                    Estimator(prior_seconds=options.b2_prior_seconds))
            outcome = dispatcher.run(order)
            b2, abandoned = outcome['results'], outcome['abandoned']
            report.update(escalation_order=order, escalated=len(outcome['durations']) + len(abandoned),
                          b2_completed=sum(v in (0, 1) for v in b2.values()), abandoned=abandoned,
                          skipped_budget=outcome['skipped_budget'], b2_durations=outcome['durations'],
                          b2_estimate_final=outcome['estimate_final'], b2_calls=len(client.calls))
            (work / 'b2_calls.json').write_text(json.dumps(client.calls, ensure_ascii=False, default=str),
                                                encoding='utf-8')
        predictions, owners = [], {}
        for row in rows:
            label, owner = final_label(scores.get(row['id']), b2.get(row['id']), policy)
            predictions.append(dict(id=row['id'], label=label))
            owners[owner] = owners.get(owner, 0) + 1
        write_predictions(options.output, predictions, options.output_format)
        report.update(owners=owners, positives=sum(p['label'] for p in predictions),
                      seconds=round(time.monotonic() - started, 2), output_written=True)
        (work / 'run.json').write_text(json.dumps(report, indent=2, ensure_ascii=False, default=str),
                                       encoding='utf-8')
        print(f'receipts={work} elapsed={report["seconds"]}s owners={owners}', flush=True)
    if abandoned:
        sys.stdout.flush()
        os._exit(0)  # in-flight B2 threads are abandoned by design; do not wait for their HTTP timeouts


if __name__ == '__main__':
    main()
