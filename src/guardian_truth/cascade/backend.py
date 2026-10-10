"""Model backends for the cascade: owned llama.cpp (reused) or owned vLLM, loopback only.

vLLM is a separate, opt-in serving profile. The B2 LocalClient needs llama's
`/v1/chat/completions/input_tokens`; VllmLocalClient keeps the same contract
(exact server-side token count before every completion) through vLLM's
`/tokenize` with chat messages, so B2 escalation can run unchanged on vLLM.
"""
from __future__ import annotations

import os
from pathlib import Path
import secrets
import socket
import subprocess
import threading
import time
import urllib.error

from guardian_truth.submission.cli import MODEL, LocalClient, http_json


class TriageClient:
    def __init__(self, base, api_key=None, timeout=300):
        self.base, self.api_key, self.timeout = base, api_key, timeout
        self.lock = threading.Lock()
        self.calls = []

    def complete(self, request, tag=''):
        start = time.monotonic()
        record = dict(tag=tag, status=None)
        data = None
        try:
            data = http_json(self.base + '/v1/chat/completions', request, self.timeout, api_key=self.api_key)
            record.update(status=200, usage=data.get('usage'), timings=data.get('timings'),
                          finish_reason=data['choices'][0].get('finish_reason'))
        except urllib.error.HTTPError as error:
            record.update(status='HTTP', http_status=error.code, detail=error.read()[:300].decode('utf-8', 'replace'))
        except Exception as error:
            record.update(status='EXC', error=type(error).__name__, detail=str(error)[:300])
        record['seconds'] = round(time.monotonic() - start, 4)
        with self.lock:
            self.calls.append(record)
        return data, record


class VllmLocalClient(LocalClient):
    """LocalClient contract on vLLM: exact served-template token count before each completion.

    Same cache key, singleflight, record fields and context-budget refusal as the
    llama LocalClient; only the two transport endpoints differ.
    """
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
            wire = dict(request, chat_template_kwargs=dict(enable_thinking=False))
            try:
                with self.lock:
                    self.preflight_http += 1
                count = http_json(self.base + '/tokenize', dict(model=self.model, messages=request['messages'],
                                                                 add_generation_prompt=True,
                                                                 chat_template_kwargs=dict(enable_thinking=False)),
                                  api_key=self.api_key)
                tokens = count.get('count')
                if type(tokens) is not int or tokens < 0:
                    raise ValueError('INVALID_TOKEN_COUNT')
                record['input_tokens'] = tokens
                if tokens + request['max_tokens'] > self.context:
                    record['transport'] = dict(status='NOT_EXECUTED_CONTEXT_BUDGET')
                else:
                    with self.lock:
                        self.completion_http += 1
                    data = http_json(self.base + '/v1/chat/completions', wire, self.timeout, api_key=self.api_key)
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


class VllmServer:
    """Owned `vllm serve` process with the same identity checks as ModelServer."""
    def __init__(self, python, model_dir, work, slots, context, *, port=None, gpu_memory_utilization=0.92,
                 quantization=None, extra_args=()):
        self.python, self.model_dir, self.work = str(python), str(model_dir), Path(work)
        self.slots, self.context, self.port = slots, context, port
        self.gpu_memory_utilization, self.quantization = gpu_memory_utilization, quantization
        self.extra_args = list(extra_args)
        self.api_key = secrets.token_hex(24)
        self.process = self.log = None
        self.props = None

    def command(self):
        command = [self.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', self.model_dir,
                   '--served-model-name', MODEL, '--host', '127.0.0.1', '--port', str(self.port),
                   '--api-key', self.api_key, '--max-model-len', str(self.context),
                   '--max-num-seqs', str(self.slots), '--enable-prefix-caching',
                   '--gpu-memory-utilization', str(self.gpu_memory_utilization),
                   '--max-logprobs', '20', '--disable-log-requests']
        if self.quantization:
            command += ['--quantization', self.quantization]
        return command + self.extra_args

    def __enter__(self):
        if self.port is None:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', 0))
                self.port = probe.getsockname()[1]
        self.log = (self.work / 'vllm-server.log').open('w', encoding='utf-8')
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1', VLLM_NO_USAGE_STATS='1',
                   DO_NOT_TRACK='1')
        self.process = subprocess.Popen(self.command(), stdout=self.log, stderr=subprocess.STDOUT, env=env,
                                        start_new_session=(os.name != 'nt'))
        try:
            deadline = time.monotonic() + 900
            while True:
                if self.process.poll() is not None:
                    raise RuntimeError('VLLM_START_FAILED: see vllm-server.log')
                try:
                    models = http_json(f'http://127.0.0.1:{self.port}/v1/models', timeout=2, api_key=self.api_key)
                    break
                except Exception:
                    if time.monotonic() >= deadline:
                        raise RuntimeError('VLLM_HEALTH_TIMEOUT')
                time.sleep(1)
            served = {m.get('id'): m for m in models.get('data', [])}
            if MODEL not in served:
                raise ValueError('SERVED_MODEL_MISMATCH')
            if served[MODEL].get('max_model_len') not in (None, self.context):
                raise ValueError('SERVED_CONTEXT_MISMATCH')
            self.props = dict(backend='vllm', model=served[MODEL], slots=self.slots, context=self.context)
            return self
        except BaseException:
            self.__exit__(None, None, None)
            raise

    def __exit__(self, *args):
        if self.process is not None and self.process.poll() is None:
            self.process.terminate()
            try:
                self.process.wait(timeout=20)
            except subprocess.TimeoutExpired:
                self.process.kill()
                self.process.wait()
        if self.log is not None:
            self.log.close()
