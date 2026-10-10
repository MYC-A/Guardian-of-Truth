"""Competition I/O, owned llama-server and frozen B2 or opt-in compact inference.

Only prompt/response enter the inference pipeline. The model is local and all
transport endpoints are fixed to loopback. Row failures are retained as diagnostics; an explicitly versioned output
recovery uses an available model classification or the user-selected fallback0.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import hashlib
import json
import os
from pathlib import Path
import socket
import secrets
import signal
import subprocess
import tempfile
import threading
import time
import urllib.error
import urllib.request

MODEL = 'qwen3.8-27b@71bc7b627595:Q8_0:llamacpp-b11459'


def read_rows(path):
    import pandas as pd
    path = Path(path)
    with path.open('rb') as f:
        parquet = f.read(4) == b'PAR1'
    if parquet:
        frame = pd.read_parquet(path)
        if not frame.columns.is_unique:
            raise ValueError('DUPLICATE_COLUMNS')
        source = frame.to_dict('records')
    else:
        with path.open(encoding='utf-8-sig', newline='') as f:
            reader = csv.DictReader(f)
            if reader.fieldnames is None or len(reader.fieldnames) != len(set(reader.fieldnames)):
                raise ValueError('MISSING_OR_DUPLICATE_COLUMNS')
            if not {'id', 'prompt', 'response'}.issubset(reader.fieldnames):
                raise ValueError('REQUIRED_COLUMNS: id,prompt,response')
            source = list(reader)
    if parquet and not {'id', 'prompt', 'response'}.issubset(frame.columns):
        raise ValueError('REQUIRED_COLUMNS: id,prompt,response')
    result, seen = [], set()
    for index, row in enumerate(source):
        clean = {}
        for key in ('id', 'prompt', 'response'):
            if not isinstance(row.get(key), str):
                raise ValueError(f'NON_STRING_OR_NULL_{key}: row {index}')
            clean[key] = row[key]
        if not clean['id'] or clean['id'] in seen:
            raise ValueError(f'EMPTY_OR_DUPLICATE_ID: row {index}')
        seen.add(clean['id'])
        result.append(clean)
    return result


def write_predictions(path, predictions, output_format='parquet'):
    import pandas as pd
    frame = pd.DataFrame(predictions, columns=['id', 'label'])
    frame['label'] = frame['label'].astype('int64')
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(prefix=path.name + '.', suffix='.tmp', dir=path.parent)
    os.close(fd)
    try:
        if output_format == 'parquet':
            frame.to_parquet(tmp, index=False)
        else:
            frame.to_csv(tmp, index=False, encoding='utf-8', lineterminator='\n')
        os.replace(tmp, path)
    finally:
        if os.path.exists(tmp):
            os.unlink(tmp)


def http_json(url, payload=None, timeout=20, api_key=None):
    # Never follow an HTTP redirect out of the local model process.
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, req, fp, code, msg, headers, newurl):
            return None
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    data = None if payload is None else json.dumps(payload).encode('utf-8')
    headers = {'Content-Type': 'application/json'}
    if api_key:
        headers['Authorization'] = 'Bearer ' + api_key
    req = urllib.request.Request(url, data=data, headers=headers)
    with opener.open(req, timeout=timeout) as response:
        return json.load(response)


class LocalClient:
    """In-memory singleflight cache, exact wire/attempt identity; no historical replies."""
    def __init__(self, port, context, timeout=600, api_key=None):
        self.model = MODEL
        self.base = f'http://127.0.0.1:{port}'
        self.context, self.timeout = context, timeout
        self.api_key = api_key
        self.lock = threading.Lock()
        self.key_locks, self.cache = {}, {}
        self.calls = []
        self.preflight_http = self.completion_http = self.cache_hits = 0

    def call(self, request, attempt=0, tag=''):
        from guardian_truth.integrated.transport import sha
        if request.get('model') != self.model:
            raise ValueError('REQUEST_MODEL_MISMATCH')
        key = sha(dict(model=self.model, request=request, attempt=attempt))
        with self.lock:
            lock = self.key_locks.setdefault(key, threading.Lock())
        with lock:
            if key in self.cache:
                with self.lock:
                    self.cache_hits += 1
                return dict(self.cache[key], cached=True)
            start = time.monotonic()
            record = dict(key=key, request_sha256=sha(request), model=self.model,
                          attempt=attempt, tag=tag, cached=False, content=None, usage=None)
            try:
                # Uses the server's own tokenizer and chat template, not bytes/4.
                with self.lock:
                    self.preflight_http += 1
                count = http_json(self.base + '/v1/chat/completions/input_tokens', request, api_key=self.api_key)
                tokens = count.get('input_tokens')
                if type(tokens) is not int or tokens < 0:
                    raise ValueError('INVALID_TOKEN_COUNT')
                record['input_tokens'] = tokens
                if tokens + request['max_tokens'] > self.context:
                    record['transport'] = dict(status='NOT_EXECUTED_CONTEXT_BUDGET')
                else:
                    with self.lock:
                        self.completion_http += 1
                    data = http_json(self.base + '/v1/chat/completions', request, self.timeout, api_key=self.api_key)
                    choice = data['choices'][0]
                    record.update(content=choice['message'].get('content'),
                                  finish_reason=choice.get('finish_reason'), usage=data.get('usage'),
                                  timings=data.get('timings'), response_model=data.get('model'),
                                  transport=dict(status=200))
            except Exception as error:
                record['transport'] = dict(status='EXC', error=type(error).__name__, detail=str(error)[:300])
                if isinstance(error, urllib.error.HTTPError):
                    record['transport']['http_status'] = error.code
            record['seconds'] = round(time.monotonic() - start, 4)
            with self.lock:
                self.calls.append(record)
            self.cache[key] = record
            return dict(record)


class ModelServer:
    def __init__(self, root, work, slots, context, *, port=None, attach=False, fast=False,
                 batch_size=None, ubatch_size=None, spec_type=None):
        if type(slots) is not int or slots < 1:
            raise ValueError('INVALID_SERVER_SLOTS')
        if spec_type not in (None, 'ngram-mod'):
            raise ValueError('INVALID_SPEC_TYPE')
        if attach and (fast or batch_size is not None or ubatch_size is not None or spec_type is not None):
            raise ValueError('ATTACH_CANNOT_CHANGE_BACKEND_FLAGS')
        self.root, self.work = Path(root), Path(work)
        self.slots, self.context = slots, context
        self.port, self.attach, self.fast = port, attach, fast
        self.process, self.log = None, None
        self.api_key = None if attach else secrets.token_hex(24)
        self.batch_size, self.ubatch_size = batch_size, ubatch_size
        self.spec_type = spec_type
        self.signal_handlers = {}
        self.props = None

    def __enter__(self):
        if self.port is None:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                self.port = probe.getsockname()[1]
        if not self.attach:
            # Fail before spawning if the requested port already belongs to a
            # different process. A per-launch API key also closes the bind race.
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', self.port))
            self.log = (self.work / 'llama-server.log').open('w', encoding='utf-8')
            binary = self.root / 'runtime/llama/llama-server'
            command = [str(binary), '-m', str(self.root / 'model/Qwen3.8-27B-Q8_0.gguf'),
                       '--alias', MODEL, '--host', '127.0.0.1', '--port', str(self.port),
                       '-ngl', '999', '-c', str(self.slots * self.context), '-np', str(self.slots),
                       '--reasoning', 'off', '--no-context-shift', '--metrics', '--api-key', self.api_key]
            if self.fast:
                command += ['-fa', 'on']
            if self.batch_size is not None:
                command += ['-b', str(self.batch_size)]
            if self.ubatch_size is not None:
                command += ['-ub', str(self.ubatch_size)]
            if self.spec_type is not None:
                command += ['--spec-type', self.spec_type]
            loader = self.root / 'runtime/lib/ld-linux-x86-64.so.2'
            if loader.is_file():
                command = [str(loader), '--library-path',
                           str(self.root / 'runtime/llama') + ':' + str(self.root / 'runtime/lib'), *command]
            environment = dict(os.environ)
            environment['LD_LIBRARY_PATH'] = str(self.root / 'runtime/llama') + ':' + str(self.root / 'runtime/lib')
            try:
                self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                                env=environment, start_new_session=(os.name != 'nt'))
                if threading.current_thread() is threading.main_thread():
                    for signum in (signal.SIGTERM, signal.SIGINT):
                        self.signal_handlers[signum] = signal.getsignal(signum)
                        signal.signal(signum, self._handle_signal)
            except BaseException:
                self.log.close()
                raise
        try:
            deadline = time.monotonic() + 120
            while True:
                if self.process is not None and self.process.poll() is not None:
                    raise RuntimeError('MODEL_START_FAILED: see llama-server.log')
                try:
                    health = http_json(f'http://127.0.0.1:{self.port}/health', timeout=2)
                    if health.get('status') == 'ok':
                        break
                except Exception:
                    if self.attach or time.monotonic() >= deadline:
                        raise RuntimeError('MODEL_HEALTH_FAILED')
                time.sleep(0.2)
            props = http_json(f'http://127.0.0.1:{self.port}/props', api_key=self.api_key)
            self.props = props
            if props.get('model_alias') != MODEL:
                raise ValueError('SERVED_MODEL_MISMATCH')
            if props.get('default_generation_settings', {}).get('n_ctx') != self.context:
                raise ValueError('SERVED_CONTEXT_MISMATCH')
            if 'total_slots' in props:
                if type(props['total_slots']) is not int or props['total_slots'] != self.slots:
                    raise ValueError('SERVED_SLOTS_MISMATCH')
            elif self.attach:
                raise ValueError('SERVED_SLOTS_NOT_VERIFIED')
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError('MODEL_START_FAILED')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        for signum, previous in self.signal_handlers.items():
            signal.signal(signum, previous)
        self.signal_handlers.clear()
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log is not None:
            self.log.close()

    def _handle_signal(self, signum, frame):
        self.__exit__(None, None, None)
        raise SystemExit(128 + signum)


def predict_one(row, client, layers, pre_profile='legacy', *, model=None, provider='local-llamacpp'):
    from guardian_truth.submission.primary import PrimaryReviewHook
    from guardian_truth.submission.blind_compact import CompactPrimaryReviewHook, PROFILES
    from guardian_truth.repair.v5 import ARMS, run_v5
    from guardian_truth.submission.recovery import recover_output
    from guardian_truth.verification.admission import interpret_receipt_v2
    if pre_profile not in PROFILES:
        raise ValueError('INVALID_PRE_PROFILE')
    effective_model = MODEL if model is None else model
    if (not isinstance(effective_model, str) or not effective_model
            or effective_model != client.model):
        raise ValueError('PREDICTOR_CLIENT_MODEL_MISMATCH')
    if model is not None and getattr(layers, 'model', effective_model) != effective_model:
        raise ValueError('PREDICTOR_LAYERS_MODEL_MISMATCH')
    hook_class = PrimaryReviewHook if pre_profile == 'legacy' else CompactPrimaryReviewHook
    profile_args = {} if pre_profile == 'legacy' else dict(profile=pre_profile)
    hook = hook_class(client, 'blind2', effective_model, original_row=row,
                      max_tokens=3400, max_request_bytes=60000, **profile_args)
    snapshot, stage_errors = {}, []
    def capture(value):
        snapshot.clear()
        snapshot.update(value)
    try:
        rec = run_v5(row, hook, flags=ARMS['R_fix'], provider=provider, model=effective_model, attempt=0,
                     tolerate_component_errors=True, on_primary=capture)
    except Exception as error:
        stage_errors.append(dict(stage='review_pipeline', admission='TECHNICAL_FAILURE', error_type=type(error).__name__))
        rec = snapshot or None
        # Initial observer precedes admission v2. Re-admit the actual successful
        # receipt against the same packet already sent, never a new packet.
        if rec is not None and 'A_adm2' not in rec and hook.review_request is not None:
            step = next((s for s in rec['A'].get('steps', []) if s.get('tag') == 'review'), None)
            if step is not None:
                try:
                    admission = interpret_receipt_v2(step, json.loads(hook.review_request['messages'][1]['content']))
                    rec['A_adm2'] = {k: admission.get(k) for k in ('decision', 'admission')}
                    if admission.get('admitted'):
                        value = admission['admitted']
                        rec['A_adm2'].update(target_id=value['regulated_action']['target_id'], reason=value['reason'])
                    rec['base_error'] = bool(rec['A'].get('guard_error')) or admission.get('decision') == 'ERROR'
                except Exception as admission_error:
                    stage_errors.append(dict(stage='primary_readmission', admission='TECHNICAL_FAILURE',
                                             error_type=type(admission_error).__name__))
    try:
        layer = layers.findings(row)
    except Exception as error:
        layer = dict(findings=[], admission='TECHNICAL_FAILURE', error_type=type(error).__name__)
    raw = dict(id=row['id'], input_row_sha256=row_fingerprint(row), pre_profile=pre_profile, rec=rec,
               pre_steps=hook.log, layer_trace=layer, primary_receipt=hook.first_receipt)
    if model is not None or provider != 'local-llamacpp':
        raw['inference_profile'] = dict(model=effective_model, provider=provider)
    if stage_errors:
        raw['stage_errors'] = stage_errors
    if rec is None:
        raw.update(binary=None, error='PRIMARY_INFERENCE_FAILURE')
    try:
        strict = finalize_trace(raw)
    except Exception as error:
        strict = dict(raw, binary=None, error='DECISION_EXCEPTION:' + type(error).__name__)
    return recover_output(strict)


def row_fingerprint(row):
    data = {key: row[key] for key in ('prompt', 'response')}
    return hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     separators=(',', ':')).encode('utf-8')).hexdigest()


def scheduled_rows(rows, order='input'):
    """Submission order only; original output alignment and every row stay intact."""
    if order == 'input':
        return list(rows)
    if order == 'longest-first':
        # Bytes are a cheap scheduling proxy, NEVER a context-budget estimate.
        # Stable sorting preserves input order for ties; no label/ID routing.
        return sorted(rows, key=lambda row: -sum(len(row[k].encode('utf-8')) for k in ('prompt', 'response')))
    raise ValueError('INVALID_QUEUE_ORDER')


def finalize_trace(raw):
    """Shared live/offline projection; never invokes a model or reads a label."""
    from experiments.research_records import failed_record, technical_gaps
    from guardian_truth.v6fix.pipeline import decide
    # Preserve an exception outside the declared projection. It cannot be
    # repaired by interpreting an incomplete record as an ordinary negative.
    if raw.get('error') not in (None, 'PRIMARY_INFERENCE_FAILURE'):
        return dict(raw)
    if raw.get('output_recovery') and raw.get('technical_error'):
        raw = dict(raw, error=raw['technical_error'], binary=None)
        raw.pop('output_recovery', None)
        raw.pop('technical_error', None)
        if raw['error'] != 'PRIMARY_INFERENCE_FAILURE':
            return raw
    rec = raw.get('rec')
    decision = decide(rec, raw['layer_trace']['findings'])
    trace = dict(raw, binary=decision['binary'], owner=decision['decision_owner'], accusation=decision['accusation'])
    trace.pop('error', None)
    trace['technical_gaps'] = technical_gaps(trace)
    primary_valid = rec is not None and (rec.get('A_adm2') or {}).get('decision') in ('ERROR', 'NO_ERROR', 'UNKNOWN')
    if rec is not None and 'A_adm2' not in rec:
        primary_valid = (rec.get('A') or {}).get('final') in ('ERROR', 'NO_ERROR', 'UNKNOWN')
    # The blind pre-pass is optional: Hook's declared fallback can execute the
    # unchanged reviewer after an injection exceeds its byte cap. Its failed or
    # skipped proposal stays in technical_gaps, but does not invalidate a valid
    # terminal reviewer receipt. Inspect the actual primary receipt separately.
    # A separately established violation survives a failed auxiliary pass;
    # an invalid primary receipt must never manufacture a negative decision.
    if decision['binary'] == 0 and (failed_record(dict(rec=rec)) or not primary_valid):
        trace['binary'] = None
        trace['error'] = 'PRIMARY_INFERENCE_FAILURE'
    return trace


def failure_summary(trace):
    """Small diagnostic for platform stdout; full evidence stays in receipts."""
    rec = trace.get('rec') or {}
    steps = (rec.get('A') or {}).get('steps') or []
    primary = next((s for s in steps if s.get('tag') == 'review'), {})
    receipt = trace.get('primary_receipt') or {}
    content = receipt.get('content', primary.get('raw_content'))
    from guardian_truth.integrated.reviewer import decode_reply, Reply
    value, decoded, normalization = decode_reply(content)
    schema_errors = []
    if decoded:
        try:
            Reply.model_validate(value)
        except Exception as error:
            if hasattr(error, 'errors'):
                schema_errors = [{k: item[k] for k in ('type', 'loc')}
                                 for item in error.errors(include_input=False, include_context=False, include_url=False)]
    admission = (rec.get('A_adm2') or {}).get('admission') or ''
    reference_error = next((code for code in ('TARGET_INVALID', 'NORM_REFERENCE_INVALID',
                                             'EVIDENCE_REFERENCE_OR_ACTOR_INVALID', 'EMPTY_ACCUSATION')
                            if str(admission).endswith(':' + code)), None)
    def category(value):
        return ':'.join(value.split(':')[:2]) if isinstance(value, str) else value
    transport = primary.get('transport') or {}
    return dict(id=trace.get('id'), error=category(trace.get('error', trace.get('technical_error'))),
                output_recovery=trace.get('output_recovery'),
                partial_model_decision=trace.get('partial_model_decision'),
                explanation_status=trace.get('explanation_status'),
                json_valid=decoded, normalization=normalization, schema_errors=schema_errors,
                reference_error=reference_error,
                raw_decision=value.get('decision') if isinstance(value, dict) and value.get('decision') in ('ERROR', 'NO_ERROR', 'UNKNOWN') else None,
                raw_content_bytes=len(content.encode('utf-8')) if isinstance(content, str) else None,
                raw_content_sha256=hashlib.sha256(content.encode('utf-8')).hexdigest() if isinstance(content, str) else None,
                input_tokens=receipt.get('input_tokens'),
                primary_admission=category((rec.get('A_adm2') or {}).get('admission')),
                review_admission=category(primary.get('admission')),
                finish_reason=primary.get('finish_reason'),
                transport={k: transport.get(k) for k in ('status', 'error', 'http_status')},
                request_sha256=primary.get('request_sha256'),
                effective_request_sha256=next((s.get('effective_request_sha256') for s in trace.get('pre_steps', [])
                                               if s.get('tag') == 'primary_wire'), primary.get('request_sha256')),
                technical_gaps=trace.get('technical_gaps', []),
                recovery=[{k: category(s.get(k)) if k == 'admission' else s.get(k)
                           for k in ('tag', 'attempt', 'admission', 'terminal_request_sha256')}
                          for s in trace.get('pre_steps', []) if s.get('tag') == 'primary_review_retry'])


def main(argv=None):
    started = time.monotonic()
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--output-format', choices=['parquet', 'csv'], default='parquet')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--slots', type=int, help='Native GPU slots; defaults to workers for the unchanged baseline')
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--port', type=int)
    parser.add_argument('--attach', action='store_true', help='Diagnostics only: use existing verified local model')
    parser.add_argument('--fast', action='store_true', help='Separate profile: enable FlashAttention; quality must be measured')
    parser.add_argument('--batch-size', type=int, help='Separate performance profile: logical prefill batch limit')
    parser.add_argument('--ubatch-size', type=int, help='Separate performance profile: physical prefill microbatch limit')
    parser.add_argument('--spec-type', choices=['none', 'ngram-mod'], default='none',
                        help='Separate opt-in speculative profile; none preserves the native baseline')
    parser.add_argument('--queue-order', choices=['input', 'longest-first'], default='input',
                        help='Opt-in submission scheduling by source bytes; output retains input order')
    parser.add_argument('--skip-inapplicable-f', action='store_true',
                        help='Opt-in: skip current F capability only when parsed move has no assistant call')
    parser.add_argument('--pre-profile', choices=['legacy', 'dedup', 'compact'], default='legacy',
                        help='Frozen baseline or opt-in compaction; new profiles require live quality/timing comparison')
    options = parser.parse_args(argv)
    if options.workers < 1 or options.context < 4096 or (options.attach and options.port is None):
        parser.error('invalid workers/context/attach port')
    gpu_slots = options.workers if options.slots is None else options.slots
    spec_type = None if options.spec_type == 'none' else options.spec_type
    if gpu_slots < 1:
        parser.error('slots must be positive')
    if options.attach and (options.fast or options.batch_size is not None
                           or options.ubatch_size is not None or spec_type is not None):
        parser.error('attach cannot change backend flags; launch a separate owned server profile')
    if any(value is not None and value < 1 for value in (options.batch_size, options.ubatch_size)):
        parser.error('batch sizes must be positive')
    if Path(options.input).resolve() == Path(options.output).resolve():
        parser.error('input and output must differ')
    if Path(options.output).exists():
        parser.error('output already exists; choose a fresh path')
    input_sha256 = hashlib.sha256(Path(options.input).read_bytes()).hexdigest()
    rows = read_rows(options.input)
    if hashlib.sha256(Path(options.input).read_bytes()).hexdigest() != input_sha256:
        raise ValueError('INPUT_CHANGED_DURING_READ')
    if not rows:
        write_predictions(options.output, [], options.output_format)
        return
    work = options.work_dir or Path(tempfile.mkdtemp(prefix='guardian-qwen-'))
    work.mkdir(parents=True, exist_ok=True)
    # No research records or gold/caches are read. IDs only align the output.
    traces = {}
    try:
        with ModelServer(options.root, work, gpu_slots, options.context,
                         port=options.port, attach=options.attach, fast=options.fast,
                         batch_size=options.batch_size, ubatch_size=options.ubatch_size, spec_type=spec_type) as server:
            client = LocalClient(server.port, options.context, api_key=server.api_key)
            from guardian_truth.v6fix.pipeline import Layers
            layer_options = dict(skip_inapplicable_f=True) if options.skip_inapplicable_f else {}
            layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700,
                            tolerate_component_errors=True, **layer_options)
            submission_rows = scheduled_rows(rows, options.queue_order)
            with ThreadPoolExecutor(max_workers=options.workers) as executor:
                futures = {executor.submit(predict_one, row, client, layers, options.pre_profile): row['id'] for row in submission_rows}
                for future in as_completed(futures):
                    identifier = futures[future]
                    try:
                        trace = future.result()
                    except Exception as error:
                        trace = dict(id=identifier, binary=None, error=f'{type(error).__name__}: {error}')
                    from guardian_truth.submission.recovery import recover_output
                    trace = recover_output(trace)
                    traces[identifier] = trace
                    with (work / 'traces.jsonl').open('a', encoding='utf-8', newline='\n') as f:
                        f.write(json.dumps(trace, ensure_ascii=False, default=str) + '\n')
                    if trace.get('error'):
                        print('prediction_failure=' + json.dumps(failure_summary(trace), ensure_ascii=False), flush=True)
                    elif trace.get('output_recovery') or any(s.get('tag') == 'primary_root_close' for s in trace.get('pre_steps', [])):
                        print('prediction_recovery=' + json.dumps(failure_summary(trace), ensure_ascii=False), flush=True)
                    print(f'{len(traces)}/{len(rows)}', flush=True)
            (work / 'calls.json').write_text(json.dumps(client.calls, ensure_ascii=False), encoding='utf-8')
        invalid = [r['id'] for r in rows if type(traces[r['id']].get('binary')) is not int
                   or traces[r['id']]['binary'] not in (0, 1)]
        report = dict(rows=len(rows), completed=len(rows) - len(invalid), invalid_ids=invalid,
                      input_sha256=input_sha256,
                      cli_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                      profile='B2-fast' if options.fast else 'B2',
                      pre_profile=options.pre_profile,
                      pre_completion_budget=1700 if options.pre_profile == 'compact' else 3400,
                      pre_contract_sha256=hashlib.sha256((Path(__file__).parent / 'blind_compact.py').read_bytes()).hexdigest(),
                      model=MODEL, calls=len(client.calls),
                      workers=options.workers, gpu_slots=gpu_slots, context_per_slot=options.context,
                      spec_type=options.spec_type,
                      queue_order=options.queue_order,
                      submission_order=[r['id'] for r in submission_rows],
                      skip_inapplicable_f=options.skip_inapplicable_f,
                      f_skipped_rows=sum((t.get('layer_trace', {}).get('f_eligibility') or {}).get('status') ==
                                        'SKIPPED_NO_CURRENT_ASSISTANT_CALL' for t in traces.values()),
                      explicit_flash=options.fast, batch_size=options.batch_size, ubatch_size=options.ubatch_size,
                      server_props=server.props, preflight_http=client.preflight_http,
                      completion_http=client.completion_http, cache_hits=client.cache_hits,
                      primary_contract='reason-last', primary_recovery_enabled=False,
                      raw_model_recoveries=sum((t.get('output_recovery') or {}).get('mode') == 'RAW_MODEL_DECISION' for t in traces.values()),
                      default_zero_fallbacks=sum((t.get('output_recovery') or {}).get('mode') == 'DEFAULT_ZERO' for t in traces.values()),
                      root_close_recoveries=sum(any(s.get('tag') == 'primary_root_close' for s in t.get('pre_steps', []))
                                                for t in traces.values()),
                      input_tokens=sum((c.get('usage') or {}).get('prompt_tokens', 0) for c in client.calls),
                      output_tokens=sum((c.get('usage') or {}).get('completion_tokens', 0) for c in client.calls))
        if invalid:
            report['failures'] = [failure_summary(traces[identifier]) for identifier in invalid]
            report.update(seconds=time.monotonic() - started, output_written=False)
            (work / 'run.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
            raise RuntimeError(f'INCOMPLETE_PREDICTIONS: {invalid}; traces at {work}')
        write_predictions(options.output, [dict(id=r['id'], label=traces[r['id']]['binary']) for r in rows],
                          options.output_format)
        report.update(seconds=time.monotonic() - started, output_written=True)
        (work / 'run.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    finally:
        print(f'receipts={work} elapsed={time.monotonic()-started:.2f}s', flush=True)


if __name__ == '__main__':
    main()
