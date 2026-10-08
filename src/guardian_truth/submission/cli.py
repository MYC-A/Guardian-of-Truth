"""Competition I/O, owned llama-server lifecycle and unchanged B2 inference.

Only prompt/response enter the inference pipeline. The model is local and all
transport endpoints are fixed to loopback. Technical primary failures abort the
submission rather than manufacturing a negative prediction.
"""
from __future__ import annotations

import argparse
from concurrent.futures import ThreadPoolExecutor, as_completed
import csv
import json
import os
from pathlib import Path
import socket
import secrets
import subprocess
import tempfile
import threading
import time
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

    def call(self, request, attempt=0, tag=''):
        from guardian_truth.integrated.transport import sha
        if request.get('model') != self.model:
            raise ValueError('REQUEST_MODEL_MISMATCH')
        key = sha(dict(model=self.model, request=request, attempt=attempt))
        with self.lock:
            lock = self.key_locks.setdefault(key, threading.Lock())
        with lock:
            if key in self.cache:
                return dict(self.cache[key], cached=True)
            start = time.monotonic()
            record = dict(key=key, request_sha256=sha(request), model=self.model,
                          attempt=attempt, tag=tag, cached=False, content=None, usage=None)
            try:
                # Uses the server's own tokenizer and chat template, not bytes/4.
                count = http_json(self.base + '/v1/chat/completions/input_tokens', request, api_key=self.api_key)
                tokens = count.get('input_tokens')
                if type(tokens) is not int or tokens < 0:
                    raise ValueError('INVALID_TOKEN_COUNT')
                record['input_tokens'] = tokens
                if tokens + request['max_tokens'] > self.context:
                    record['transport'] = dict(status='NOT_EXECUTED_CONTEXT_BUDGET')
                else:
                    data = http_json(self.base + '/v1/chat/completions', request, self.timeout, api_key=self.api_key)
                    choice = data['choices'][0]
                    record.update(content=choice['message'].get('content'),
                                  finish_reason=choice.get('finish_reason'), usage=data.get('usage'),
                                  timings=data.get('timings'), response_model=data.get('model'),
                                  transport=dict(status=200))
            except Exception as error:
                record['transport'] = dict(status='EXC', error=type(error).__name__, detail=str(error)[:300])
            record['seconds'] = round(time.monotonic() - start, 4)
            with self.lock:
                self.calls.append(record)
            self.cache[key] = record
            return dict(record)


class ModelServer:
    def __init__(self, root, work, slots, context, *, port=None, attach=False, fast=False):
        self.root, self.work = Path(root), Path(work)
        self.slots, self.context = slots, context
        self.port, self.attach, self.fast = port, attach, fast
        self.process, self.log = None, None
        self.api_key = None if attach else secrets.token_hex(24)

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
            loader = self.root / 'runtime/lib/ld-linux-x86-64.so.2'
            if loader.is_file():
                command = [str(loader), '--library-path',
                           str(self.root / 'runtime/llama') + ':' + str(self.root / 'runtime/lib'), *command]
            environment = dict(os.environ)
            environment['LD_LIBRARY_PATH'] = str(self.root / 'runtime/llama') + ':' + str(self.root / 'runtime/lib')
            try:
                self.process = subprocess.Popen(command, stdout=self.log, stderr=subprocess.STDOUT,
                                                env=environment, start_new_session=(os.name != 'nt'))
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
            if props.get('model_alias') != MODEL:
                raise ValueError('SERVED_MODEL_MISMATCH')
            if props.get('default_generation_settings', {}).get('n_ctx') != self.context:
                raise ValueError('SERVED_CONTEXT_MISMATCH')
            if self.process is not None and self.process.poll() is not None:
                raise RuntimeError('MODEL_START_FAILED')
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=10)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log is not None:
            self.log.close()


def predict_one(row, client, layers):
    from experiments.guardian_addons.variants2 import Hook2
    from experiments.research_records import failed_record, technical_gaps
    from guardian_truth.repair.v5 import ARMS, run_v5
    from guardian_truth.v6fix.pipeline import decide
    hook = Hook2(client, 'blind2', MODEL, original_row=row,
                 max_tokens=3400, max_request_bytes=60000)
    rec = run_v5(row, hook, flags=ARMS['R_fix'], provider='local-llamacpp', model=MODEL, attempt=0)
    layer = layers.findings(row)
    decision = decide(rec, layer['findings'])
    trace = dict(id=row['id'], rec=rec, pre_steps=hook.log, layer_trace=layer,
                 binary=decision['binary'], owner=decision['decision_owner'], accusation=decision['accusation'])
    trace['technical_gaps'] = technical_gaps(trace)
    primary_valid = (rec.get('A_adm2') or {}).get('decision') in ('ERROR', 'NO_ERROR', 'UNKNOWN')
    if 'A_adm2' not in rec:
        primary_valid = (rec.get('A') or {}).get('final') in ('ERROR', 'NO_ERROR', 'UNKNOWN')
    # A separately established violation survives a failed auxiliary pass;
    # an invalid primary receipt must never manufacture a negative decision.
    if decision['binary'] == 0 and (failed_record(trace) or not primary_valid):
        trace['binary'] = None
        trace['error'] = 'PRIMARY_INFERENCE_FAILURE'
    return trace


def main(argv=None):
    parser = argparse.ArgumentParser()
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.add_argument('--output-format', choices=['parquet', 'csv'], default='parquet')
    parser.add_argument('--root', type=Path, default=Path(__file__).resolve().parents[3])
    parser.add_argument('--work-dir', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--port', type=int)
    parser.add_argument('--attach', action='store_true', help='Diagnostics only: use existing verified local model')
    parser.add_argument('--fast', action='store_true', help='Separate profile: enable FlashAttention; quality must be measured')
    options = parser.parse_args(argv)
    if options.workers < 1 or options.context < 4096 or (options.attach and options.port is None):
        parser.error('invalid workers/context/attach port')
    if Path(options.input).resolve() == Path(options.output).resolve():
        parser.error('input and output must differ')
    if Path(options.output).exists():
        parser.error('output already exists; choose a fresh path')
    rows = read_rows(options.input)
    if not rows:
        write_predictions(options.output, [], options.output_format)
        return
    work = options.work_dir or Path(tempfile.mkdtemp(prefix='guardian-qwen-'))
    work.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    # No research records or gold/caches are read. IDs only align the output.
    traces = {}
    try:
        with ModelServer(options.root, work, options.workers, options.context,
                         port=options.port, attach=options.attach, fast=options.fast) as server:
            client = LocalClient(server.port, options.context, api_key=server.api_key)
            from guardian_truth.v6fix.pipeline import Layers
            layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700)
            with ThreadPoolExecutor(max_workers=options.workers) as executor:
                futures = {executor.submit(predict_one, row, client, layers): row['id'] for row in rows}
                for future in as_completed(futures):
                    identifier = futures[future]
                    try:
                        trace = future.result()
                    except Exception as error:
                        trace = dict(id=identifier, binary=None, error=f'{type(error).__name__}: {error}')
                    traces[identifier] = trace
                    with (work / 'traces.jsonl').open('a', encoding='utf-8', newline='\n') as f:
                        f.write(json.dumps(trace, ensure_ascii=False, default=str) + '\n')
                    print(f'{len(traces)}/{len(rows)}', flush=True)
            (work / 'calls.json').write_text(json.dumps(client.calls, ensure_ascii=False), encoding='utf-8')
        invalid = [r['id'] for r in rows if type(traces[r['id']].get('binary')) is not int
                   or traces[r['id']]['binary'] not in (0, 1)]
        report = dict(rows=len(rows), completed=len(rows) - len(invalid), invalid_ids=invalid,
                      seconds=time.monotonic() - started, profile='B2-fast' if options.fast else 'B2',
                      model=MODEL, calls=len(client.calls),
                      input_tokens=sum((c.get('usage') or {}).get('prompt_tokens', 0) for c in client.calls),
                      output_tokens=sum((c.get('usage') or {}).get('completion_tokens', 0) for c in client.calls))
        (work / 'run.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
        if invalid:
            raise RuntimeError(f'INCOMPLETE_PREDICTIONS: {invalid}; traces at {work}')
        write_predictions(options.output, [dict(id=r['id'], label=traces[r['id']]['binary']) for r in rows],
                          options.output_format)
    finally:
        print(f'receipts={work} elapsed={time.monotonic()-started:.2f}s', flush=True)


if __name__ == '__main__':
    main()
