"""Opt-in research transport; B2 prompts, admission and output recovery are reused.

No historical cache, automatic retry, schema replacement, truncation or reasoning
to content conversion. FP8/vLLM is a new inference profile, not Q8 equivalence.
Run with an external whole-process supervisor in addition to --duration.
"""
from __future__ import annotations

import argparse
import copy
from concurrent.futures import ThreadPoolExecutor, as_completed
import hashlib
import json
import math
import os
from pathlib import Path
import secrets
import signal
import socket
import subprocess
import sys
import threading
import time
import urllib.error
import urllib.request

from guardian_truth.integrated.transport import sha
from submission.platform_environment_probe import require_cleanup_support, cleanup_child
from guardian_truth.submission.cli import predict_one, read_rows, write_predictions

VERSION = 'qwen35-b2-system-vllm-v1'
ENGINE_VERSION = '0.19.1'
REVISION = '9d1823d2dee688a6b25e77009dc727688c44936e'
REPOSITORY = 'Qwen/Qwen3.5-35B-A3B-FP8'
MODEL = f'Qwen/Qwen3.5-35B-A3B-FP8@{REVISION}:vllm-{ENGINE_VERSION}'
STARTUP_LOG_TAIL_BYTES = 64 * 1024


def write_json(path, value):
    path = Path(path)
    temporary = path.with_suffix(path.suffix + '.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False), encoding='utf-8')
    os.replace(temporary, path)


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def _pairs(pairs):
    result = {}
    for key, value in pairs:
        if key in result:
            raise ValueError('DUPLICATE_RESPONSE_KEY')
        result[key] = value
    return result


def http(url, payload, timeout, api_key):
    """Loopback only, no proxy/redirect/retry; retain original response bytes."""
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    if not url.startswith('http://127.0.0.1:'):
        raise ValueError('NON_LOOPBACK_ENDPOINT')
    body = None if payload is None else json.dumps(payload, allow_nan=False).encode('utf-8')
    request = urllib.request.Request(url, data=body, headers={
        'Content-Type': 'application/json', 'Authorization': 'Bearer ' + api_key})
    opener = urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect())
    with opener.open(request, timeout=timeout) as response:
        return response.read()


def decode(raw):
    return json.loads(raw.decode('utf-8'), object_pairs_hook=_pairs,
                      parse_constant=lambda _: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def prepare_wire(request, model):
    if not isinstance(request, dict) or request.get('model') != model:
        raise ValueError('REQUEST_MODEL_MISMATCH')
    if type(request.get('max_tokens')) is not int or request['max_tokens'] < 1:
        raise ValueError('INVALID_MAX_TOKENS')
    if request.get('stream', False) is not False or request.get('n', 1) != 1:
        raise ValueError('ONLY_SINGLE_NONSTREAM_REPLY')
    if not isinstance(request.get('messages'), list) or not request['messages']:
        raise ValueError('INVALID_MESSAGES')
    # This adapter supports B2's text-only, system/user chat, not arbitrary
    # assistant prefills or tools whose rendering also depends on tool_choice.
    if any(not isinstance(m, dict) or set(m) != {'role', 'content'}
           or m['role'] not in ('system', 'user') or not isinstance(m['content'], str)
           for m in request['messages']):
        raise ValueError('UNSUPPORTED_MESSAGE_RENDERING')
    if any(k in request for k in ('tools', 'tool_choice', 'documents', 'truncate_prompt_tokens',
                                 'chat_template', 'mm_processor_kwargs', 'media_io_kwargs')):
        raise ValueError('UNSUPPORTED_RENDER_PARAMETER')
    wire = copy.deepcopy(request)
    kwargs = wire.setdefault('chat_template_kwargs', {})
    if not isinstance(kwargs, dict):
        raise ValueError('INVALID_TEMPLATE_KWARGS')
    if 'enable_thinking' in kwargs and kwargs['enable_thinking'] is not False:
        raise ValueError('THINKING_CONFLICT')
    kwargs['enable_thinking'] = False
    for key, value in dict(add_generation_prompt=True, continue_final_message=False,
                           add_special_tokens=False).items():
        if key in wire and wire[key] is not value:
            raise ValueError('RENDER_FLAG_CONFLICT')
        if key in kwargs and kwargs[key] is not value:
            raise ValueError('TEMPLATE_RENDER_FLAG_CONFLICT')
        wire[key] = value
    preflight = {key: copy.deepcopy(wire[key]) for key in (
        'model', 'messages', 'chat_template_kwargs', 'add_generation_prompt',
        'continue_final_message', 'add_special_tokens')}
    return wire, preflight


def owned_group_handles(pgid, owner_token, proc_root=Path('/proc')):
    """Open pidfds before checking ownership; never signal a recycled PID/PGID.

    A dead group leader is irrelevant. Only live members of our original session
    and group with our inherited random marker are returned. Foreign members are
    skipped, including a later unrelated group that reused the numeric PGID.
    """
    handles = []
    try:
        for directory in proc_root.iterdir():
            if not directory.name.isdigit():
                continue
            descriptor = None
            try:
                fields = (directory / 'stat').read_text().rsplit(')', 1)[1].split()
                if fields[0] == 'Z' or int(fields[2]) != pgid or int(fields[3]) != pgid:
                    continue
                # Capture the kernel process identity before /proc ownership
                # checks. If the PID dies/recycles, this fd cannot hit its heir.
                descriptor = os.pidfd_open(int(directory.name), 0)
                marker = ('GUARDIAN_VLLM_OWNER_TOKEN=' + owner_token).encode()
                if marker not in (directory / 'environ').read_bytes().split(b'\0'):
                    continue
                handles.append((int(directory.name), descriptor))
                descriptor = None
            except (FileNotFoundError, ProcessLookupError):
                pass
            finally:
                if descriptor is not None:
                    os.close(descriptor)
        return handles
    except BaseException:
        for _, descriptor in handles:
            os.close(descriptor)
        raise


class VllmClient:
    def __init__(self, port, context, work, *, api_key, backend_manifest,
                 timeout=90, deadline=None, max_calls=520, transport=http):
        if type(port) is not int or not 0 < port < 65536 or type(context) is not int or context < 1:
            raise ValueError('INVALID_ENDPOINT_OR_CONTEXT')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise ValueError('INVALID_TIMEOUT')
        if type(max_calls) is not int or max_calls < 1:
            raise ValueError('INVALID_CALL_CAP')
        if not isinstance(backend_manifest, dict) or backend_manifest.get('model') != MODEL:
            raise ValueError('BACKEND_MANIFEST_MISMATCH')
        self.model, self.context, self.timeout = MODEL, context, timeout
        self.backend_manifest = copy.deepcopy(backend_manifest)
        self.backend_sha256 = sha(self.backend_manifest)
        self.base, self.api_key = f'http://127.0.0.1:{port}', api_key
        self.work = Path(work)
        self.work.mkdir(parents=True, exist_ok=False)
        if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            raise ValueError('INVALID_DEADLINE')
        if backend_manifest.get('context', context) != context:
            raise ValueError('BACKEND_CONTEXT_MISMATCH')
        self.deadline = deadline
        self.max_calls, self.transport = max_calls, transport
        self.lock, self.key_locks, self.cache = threading.Lock(), {}, {}
        self.calls = []
        self.preflight_http = self.completion_http = self.cache_hits = 0

    def remaining(self):
        remaining = self.timeout if self.deadline is None else min(self.timeout, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError('WHOLE_RUN_DEADLINE')
        return remaining

    def call(self, request, attempt=0, tag=''):
        request = copy.deepcopy(request)
        wire, preflight = prepare_wire(request, self.model)
        key = sha(dict(backend=self.backend_sha256, wire=wire, request=request, attempt=attempt))
        with self.lock:
            lock = self.key_locks.setdefault(key, threading.Lock())
        with lock:
            if key in self.cache:
                with self.lock:
                    self.cache_hits += 1
                return dict(copy.deepcopy(self.cache[key]), cached=True)
            start = time.monotonic()
            record = dict(key=key, request_sha256=sha(request), wire_sha256=sha(wire),
                          backend_sha256=self.backend_sha256, model=self.model, attempt=attempt,
                          tag=tag, cached=False, content=None, usage=None,
                          request=request, wire=wire, preflight=preflight)
            with self.lock:
                ordinal = len(self.calls)
                self.calls.append(record)
            path = self.work / f'{ordinal:05d}.json'
            write_json(path, dict(record, phase='RESERVED'))
            try:
                timeout = self.remaining()
                with self.lock:
                    self.preflight_http += 1
                raw = self.transport(self.base + '/tokenize', preflight, timeout, self.api_key)
                record['preflight_raw_utf8'] = raw.decode('utf-8')
                count = decode(raw)
                tokens, ids = count.get('count'), count.get('tokens')
                if (type(tokens) is not int or tokens < 0 or not isinstance(ids, list)
                        or len(ids) != tokens or any(type(t) is not int or t < 0 for t in ids)):
                    raise ValueError('INVALID_NATIVE_TOKEN_COUNT')
                if type(count.get('max_model_len')) is not int or count['max_model_len'] != self.context:
                    raise ValueError('SERVED_CONTEXT_MISMATCH')
                record['input_tokens'] = tokens
                if tokens + wire['max_tokens'] > self.context:
                    record['transport'] = dict(status='NOT_EXECUTED_CONTEXT_BUDGET')
                else:
                    timeout = self.remaining()
                    with self.lock:
                        if self.completion_http >= self.max_calls:
                            raise RuntimeError('COMPLETION_CALL_CAP')
                        self.completion_http += 1
                        record['completion_reservation'] = self.completion_http
                    # Persist before HTTP: a killed process cannot masquerade as
                    # zero calls. This adapter never resumes an old output path.
                    write_json(path, dict(record, phase='COMPLETION_RESERVED'))
                    raw = self.transport(self.base + '/v1/chat/completions', wire, timeout, self.api_key)
                    record['response_raw_utf8'] = raw.decode('utf-8')
                    write_json(path, dict(record, phase='RAW_RECEIVED'))
                    data = decode(raw)
                    record['raw_response'] = data
                    if not isinstance(data, dict) or data.get('model') != self.model:
                        raise ValueError('RESPONSE_MODEL_MISMATCH')
                    choices = data.get('choices')
                    if not isinstance(choices, list) or len(choices) != 1 or not isinstance(choices[0], dict):
                        raise ValueError('INVALID_CHOICES')
                    choice = choices[0]
                    message, usage = choice.get('message'), data.get('usage')
                    if (not isinstance(message, dict) or not isinstance(message.get('content'), str)
                            or choice.get('finish_reason') not in ('stop', 'length')):
                        raise ValueError('INVALID_CONTENT_OR_FINISH')
                    if (not isinstance(usage, dict) or type(usage.get('prompt_tokens')) is not int
                            or usage['prompt_tokens'] != tokens
                            or type(usage.get('completion_tokens')) is not int
                            or not 0 <= usage['completion_tokens'] <= wire['max_tokens']):
                        raise ValueError('PREFLIGHT_USAGE_MISMATCH')
                    record.update(content=message['content'], finish_reason=choice['finish_reason'],
                                  usage=usage, response_model=data['model'], transport=dict(status=200),
                                  timings=data.get('timings'))
            except Exception as error:
                record['transport'] = dict(status='EXC', error=type(error).__name__, detail=str(error)[:300])
                if isinstance(error, urllib.error.HTTPError):
                    record['transport']['http_status'] = error.code
                    record['http_error_body'] = error.read(65536).decode('utf-8', 'replace')
            record['seconds'] = time.monotonic() - start
            write_json(path, dict(record, phase='FINISHED'))
            self.cache[key] = copy.deepcopy(record)
            return copy.deepcopy(record)


class OwnedVllmServer:
    """Pinned opt-in server; receipt identities derive from actual local assets."""
    def __init__(self, python, model_dir, work, context, slots, *, deadline, asset_manifest,
                 startup_timeout=300, gpu_memory_utilization=0.88, enforce_eager=False):
        if type(context) is not int or context < 1 or type(slots) is not int or slots < 1:
            raise ValueError('INVALID_CONTEXT_OR_SLOTS')
        if not 0 < gpu_memory_utilization < 1 or startup_timeout <= 0:
            raise ValueError('INVALID_SERVER_LIMIT')
        self.python, self.model_dir, self.work = str(python), Path(model_dir), Path(work)
        self.context, self.slots = context, slots
        self.deadline, self.startup_timeout = deadline, startup_timeout
        self.asset_manifest, self.enforce_eager = Path(asset_manifest), enforce_eager
        self.gpu_memory_utilization = gpu_memory_utilization
        self.api_key = secrets.token_hex(24)
        self.process = self.log = None
        self.cleanup_mode = None
        self.pgid = None
        self.owner_token = secrets.token_hex(24)
        self.cleanup_done = False
        self.handlers = {}
        self.popen_started = None
        with socket.socket() as probe:
            probe.bind(('127.0.0.1', 0))
            self.port = probe.getsockname()[1]

    def command(self):
        command = [self.python, '-m', 'vllm.entrypoints.openai.api_server', '--model', str(self.model_dir),
                '--tokenizer', str(self.model_dir), '--served-model-name', MODEL,
                '--host', '127.0.0.1', '--port', str(self.port), '--api-key', self.api_key,
                '--max-model-len', str(self.context), '--max-num-seqs', str(self.slots),
                '--gpu-memory-utilization', str(self.gpu_memory_utilization), '--generation-config', 'vllm',
                '--chat-template-content-format', 'string',  # request logging is opt-in in vLLM 0.19 (--disable-log-requests removed)
                '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16',
                '--kv-cache-dtype', 'auto']
        if self.enforce_eager:
            command.append('--enforce-eager')
        command.extend(['--language-model-only', '--max-num-batched-tokens', '8192',
                        '--structured-outputs-config',
                        json.dumps(dict(backend='xgrammar',disable_any_whitespace=True))])
        return command

    def __enter__(self):
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONNOUSERSITE='1', SPT_NOENV='1')
        for key in ('PYTHONHOME', 'LD_PRELOAD'):
            env.pop(key, None)
        self.cleanup_mode = require_cleanup_support()
        env['GUARDIAN_VLLM_OWNER_TOKEN'] = self.owner_token
        remaining = min(30, self.deadline - time.monotonic())
        if remaining <= 0:
            raise TimeoutError('WHOLE_RUN_DEADLINE')
        installed = subprocess.check_output([self.python, '-c',
            "import importlib.metadata; print(importlib.metadata.version('vllm'))"],
            timeout=remaining, text=True, env=env).strip()
        if installed != ENGINE_VERSION:
            raise ValueError('ENGINE_VERSION_MISMATCH')
        # The resolved snapshot directory is part of the pinned revision contract.
        if self.model_dir.resolve().name != REVISION:
            raise ValueError('CHECKPOINT_SNAPSHOT_REVISION_MISMATCH')
        asset_manifest_sha256 = digest(self.asset_manifest)
        supplied = json.loads(self.asset_manifest.read_text(encoding='utf-8'))
        if supplied.get('repository') != 'Qwen/Qwen3.5-35B-A3B-FP8' or supplied.get('revision') != REVISION:
            raise ValueError('ASSET_MANIFEST_IDENTITY_MISMATCH')
        files = supplied.get('files')
        if not isinstance(files, list) or not files:
            raise ValueError('INVALID_ASSET_MANIFEST')
        verified = {}
        for entry in files:
            if not isinstance(entry, dict):
                raise ValueError('INVALID_ASSET_ENTRY')
            name, size, checksum = entry.get('path'), entry.get('size'), entry.get('sha256')
            if (not isinstance(name, str) or Path(name).is_absolute() or '..' in Path(name).parts
                    or '\\' in name or name in verified or type(size) is not int or size < 1
                    or not isinstance(checksum, str) or len(checksum) != 64
                    or any(c not in '0123456789abcdef' for c in checksum)):
                raise ValueError('INVALID_ASSET_ENTRY')
            path = self.model_dir / name
            if not path.is_file() or path.stat().st_size != size:
                raise ValueError('ASSET_SIZE_MISMATCH')
            if not name.endswith('.safetensors') and digest(path) != checksum:
                raise ValueError('SMALL_ASSET_HASH_MISMATCH')
            verified[name] = entry
        assets = {}
        for name in ('config.json', 'tokenizer.json', 'tokenizer_config.json', 'model.safetensors.index.json'):
            if name not in verified:
                raise ValueError('ASSET_MANIFEST_MISSING_REQUIRED_FILE')
            assets[name] = digest(self.model_dir / name)
        for path in sorted(self.model_dir.glob('*.jinja')):
            assets[path.name] = digest(path)
        config = json.loads((self.model_dir / 'config.json').read_text(encoding='utf-8'))
        quantization = config.get('quantization_config')
        if not isinstance(quantization, dict) or quantization.get('quant_method') != 'fp8':
            raise ValueError('CHECKPOINT_QUANTIZATION_MISMATCH')
        index = json.loads((self.model_dir / 'model.safetensors.index.json').read_text(encoding='utf-8'))
        weight_map = index.get('weight_map')
        if not isinstance(weight_map, dict) or not weight_map:
            raise ValueError('INVALID_CHECKPOINT_INDEX')
        shards = {}
        for name in set(weight_map.values()):
            if not isinstance(name, str) or Path(name).name != name or not name.endswith('.safetensors'):
                raise ValueError('INVALID_CHECKPOINT_SHARD_NAME')
            path = self.model_dir / name
            if not path.is_file() or path.stat().st_size < 1:
                raise ValueError('CHECKPOINT_SHARD_MISSING')
            shards[name] = path.stat().st_size
            if name not in verified or verified[name]['size'] != shards[name]:
                raise ValueError('SHARD_NOT_IN_VERIFIED_MANIFEST')
        if set(shards) != {name for name in verified if name.endswith('.safetensors')}:
            raise ValueError('INDEX_MANIFEST_SHARD_SET_MISMATCH')
        self.manifest = dict(version=VERSION, model=MODEL, engine_version=installed, revision=REVISION,
                             model_dir=str(self.model_dir.resolve()), assets=assets, quantization=quantization,
                             context=self.context, slots=self.slots, generation_config='vllm',
                             content_format='string', gpu_memory_utilization=self.gpu_memory_utilization,
                             enable_thinking=False, code_sha256=digest(__file__))
        self.manifest.update(shard_sizes=shards,
                             asset_manifest_sha256=asset_manifest_sha256,
                             enforce_eager=self.enforce_eager, prefix_caching=True, chunked_prefill=True,
                             dtype='bfloat16', kv_cache_dtype='auto',
                             weight_integrity='EXTERNAL_FULL_SHA_MANIFEST_ADAPTER_CHECKS_STAT_AND_SMALL_HASHES')
        write_json(self.work / 'backend.json', self.manifest)
        self.log = (self.work / 'vllm-server.log').open('w', encoding='utf-8')
        try:
            with socket.socket() as probe:
                probe.bind(('127.0.0.1', self.port))
            self.popen_started = time.monotonic()
            if self.cleanup_mode == 'unreaped_leader':
                self.handlers[signal.SIGCHLD] = signal.getsignal(signal.SIGCHLD)
                signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            self.process = subprocess.Popen(self.command(), stdout=self.log, stderr=subprocess.STDOUT,
                                            env=env, start_new_session=(os.name != 'nt'))
            self.process._guardian_unreaped_leader = self.cleanup_mode == 'unreaped_leader'
            # start_new_session creates a session/group whose ID is this PID.
            # Capture it once, never rediscover it from a potentially dead leader.
            if os.name != 'nt':
                self.pgid = self.process.pid
            if threading.current_thread() is threading.main_thread():
                for signum in (signal.SIGTERM, signal.SIGINT):
                    self.handlers[signum] = signal.getsignal(signum)
                    signal.signal(signum, self._signal)
            stop = min(self.deadline, time.monotonic() + self.startup_timeout)
            while time.monotonic() < stop:
                if self.child_status() is not None:
                    raise RuntimeError('VLLM_START_FAILED')
                try:
                    models = decode(http(f'http://127.0.0.1:{self.port}/v1/models', None,
                                         min(2, stop - time.monotonic()), self.api_key))
                except Exception:
                    time.sleep(min(0.2, max(0, stop - time.monotonic())))
                    continue
                served = [m for m in models.get('data', []) if isinstance(m, dict) and m.get('id') == MODEL]
                if len(served) != 1 or type(served[0].get('max_model_len')) is not int or served[0]['max_model_len'] != self.context:
                    raise ValueError('SERVED_IDENTITY_OR_CONTEXT_MISMATCH')
                self.props = models
                return self
            raise TimeoutError('VLLM_STARTUP_DEADLINE')
        except BaseException as error:
            # Observe the failure before cleanup can change a live process's
            # status. Diagnostics and cleanup must preserve the startup cause.
            failure = dict(error=type(error).__name__, detail=self._redact_startup_text(str(error)),
                           returncode=None, seconds_since_popen=None, diagnostic_errors=[])
            try:
                if self.popen_started is not None:
                    failure['seconds_since_popen'] = time.monotonic() - self.popen_started
                if self.process is not None:
                    failure['returncode'] = self.child_status()
            except BaseException as diagnostic_error:
                failure['diagnostic_errors'].append(type(diagnostic_error).__name__)
            try:
                self.__exit__()
            except BaseException as cleanup_error:
                failure['cleanup_error'] = dict(error=type(cleanup_error).__name__,
                    detail=self._redact_startup_text(str(cleanup_error)))
            try:
                self._report_startup_failure(failure)
            except BaseException:
                pass
            raise

    def _redact_startup_text(self, text):
        for secret in (self.api_key, self.owner_token):
            text = text.replace(secret, '[REDACTED]')
        return text

    def _report_startup_failure(self, failure):
        """Best-effort bounded post-cleanup log capture; never issue a retry."""
        path = self.work / 'vllm-server.log'
        failure['log_path'] = self._redact_startup_text(str(path))
        failure['log_tail'] = ''
        try:
            with path.open('rb') as stream:
                size = stream.seek(0, os.SEEK_END)
                offset = max(0, size - STARTUP_LOG_TAIL_BYTES)
                stream.seek(offset)
                raw = stream.read(STARTUP_LOG_TAIL_BYTES)
            text = raw.decode('utf-8', errors='replace')
            if offset:
                # A tail boundary may bisect one of our secrets. Remove a
                # leading suffix before replacing complete tokens below.
                for secret in (self.api_key, self.owner_token):
                    for start in range(1, len(secret)):
                        if text.startswith(secret[start:]):
                            text = '[REDACTED]' + text[len(secret) - start:]
                            break
            text = self._redact_startup_text(text)
            # UTF-8 replacement characters can expand malformed raw bytes.
            encoded = text.encode('utf-8')
            failure['log_tail'] = encoded[-STARTUP_LOG_TAIL_BYTES:].decode('utf-8', errors='ignore')
            failure['log_bytes'] = size
            failure['log_tail_truncated'] = bool(offset or len(encoded) > STARTUP_LOG_TAIL_BYTES)
        except BaseException as diagnostic_error:
            failure['diagnostic_errors'].append('LOG_READ:' + type(diagnostic_error).__name__)
        try:
            write_json(self.work / 'startup_failure.json', failure)
        except BaseException as diagnostic_error:
            failure['diagnostic_errors'].append('RECEIPT_WRITE:' + type(diagnostic_error).__name__)
        try:
            metadata = {key: value for key, value in failure.items() if key != 'log_tail'}
            print('=== GUARDIAN VLLM STARTUP FAILURE BEGIN ===', file=sys.stderr)
            print(json.dumps(metadata, ensure_ascii=False), file=sys.stderr)
            print(failure['log_tail'], file=sys.stderr)
            print('=== GUARDIAN VLLM STARTUP FAILURE END ===', file=sys.stderr, flush=True)
        except BaseException:
            pass

    def _signal(self, signum, frame):
        self.__exit__()
        raise SystemExit(128 + signum)

    def child_status(self):
        if self.cleanup_mode != 'unreaped_leader':
            return self.process.poll()
        result=os.waitid(os.P_PID,self.process.pid,os.WEXITED|os.WNOHANG|os.WNOWAIT)
        if result is None:return None
        return result.si_status if result.si_code==os.CLD_EXITED else -result.si_status

    def __exit__(self, exc_type=None, exc=None, tb=None):
        if self.cleanup_done:return
        self.cleanup_done=True
        failure=None
        try:
            if self.process is not None:cleanup_child(self.process,self.owner_token)
            write_json(self.work/'cleanup.json',dict(cleanup_mode=self.cleanup_mode,released_process_group=True))
        except BaseException as error:
            failure=error
            write_json(self.work/'cleanup.json',dict(cleanup_mode=self.cleanup_mode,error=type(error).__name__))
        finally:
            for signum,handler in self.handlers.items():signal.signal(signum,handler)
            if self.log is not None:self.log.close()
        if failure is not None:raise failure


def emit_row_progress(trace, completed, total, started, completion_http):
    """Diagnostics only: no source text, ids or model request changes."""
    try:
        print('GUARDIAN_B2 ' + json.dumps(dict(event='row', completed=completed, total=total,
            seconds=round(time.monotonic() - started, 2), binary=trace.get('binary'),
            recovery=(trace.get('output_recovery') or {}).get('mode'),
            completion_http=completion_http), sort_keys=True), flush=True)
    except Exception:
        pass
