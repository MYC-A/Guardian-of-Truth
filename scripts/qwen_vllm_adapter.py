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
import threading
import time
import urllib.error
import urllib.request

from guardian_truth.integrated.transport import sha
from guardian_truth.submission.cli import predict_one, read_rows, write_predictions

VERSION = 'qwen-vllm-research-transport-v1'
ENGINE_VERSION = '0.19.1'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
MODEL = f'Qwen/Qwen3.8-27B-FP8@{REVISION}:vllm-{ENGINE_VERSION}'


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
        self.budget_preflight_http, self.token_counts = 0, {}

    def count_tokens(self, request):
        """Native input token count of the exact wire this client would send (same /tokenize preflight)."""
        _, preflight = prepare_wire(copy.deepcopy(request), self.model)
        key = sha(preflight)
        with self.lock:
            if key in self.token_counts:
                return self.token_counts[key]
            self.budget_preflight_http += 1
        count = decode(self.transport(self.base + '/tokenize', preflight, self.remaining(), self.api_key))
        tokens, ids = count.get('count'), count.get('tokens')
        if (type(tokens) is not int or tokens < 0 or not isinstance(ids, list) or len(ids) != tokens
                or type(count.get('max_model_len')) is not int or count['max_model_len'] != self.context):
            raise ValueError('INVALID_NATIVE_TOKEN_COUNT')
        with self.lock:
            self.token_counts[key] = tokens
        return tokens


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


class TokenBudget:
    """Request budget = served context in native tokens (input + reserved completion), replacing the byte cap."""
    def __init__(self, client):
        self.client, self.context = client, client.context

    def count(self, request):
        return self.client.count_tokens(request)


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
        self.pgid = None
        self.owner_token = secrets.token_hex(24)
        self.cleanup_done = False
        self.handlers = {}
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
        return command

    def __enter__(self):
        env = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                   VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONNOUSERSITE='1', SPT_NOENV='1')
        for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
            env.pop(key, None)
        if os.name != 'nt' and (not hasattr(os, 'pidfd_open') or not hasattr(signal, 'pidfd_send_signal')
                                or not Path('/proc').is_dir()):
            raise RuntimeError('LINUX_PIDFD_CLEANUP_REQUIRED')
        if os.name != 'nt':
            descriptor = os.pidfd_open(os.getpid(), 0)
            os.close(descriptor)
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
        if supplied.get('repository') != 'Qwen/Qwen3.8-27B-FP8' or supplied.get('revision') != REVISION:
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
            self.process = subprocess.Popen(self.command(), stdout=self.log, stderr=subprocess.STDOUT,
                                            env=env, start_new_session=(os.name != 'nt'))
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
                if self.process.poll() is not None:
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
        except BaseException:
            self.__exit__()
            raise

    def _signal(self, signum, frame):
        self.__exit__()
        raise SystemExit(128 + signum)

    def __exit__(self, *args):
        status = dict(status='CLEANED', pgid=self.pgid, method='PIDFD_OWNERSHIP_VERIFIED_GROUP_MEMBERS')
        try:
            if not self.cleanup_done and self.process is not None:
                if self.pgid is not None:
                    self._cleanup_group()
                elif self.process.poll() is None:
                    self.process.terminate()
                    try:
                        self.process.wait(timeout=10)
                    except subprocess.TimeoutExpired:
                        self.process.kill()
                # Reap the leader even when it exited before its children.
                self.process.wait(timeout=2)
                self.cleanup_done = True
        except BaseException as error:
            status.update(status='CLEANUP_FAILED', error=type(error).__name__, detail=str(error)[:300])
            raise
        finally:
            try:
                for signum, previous in self.handlers.items():
                    signal.signal(signum, previous)
            finally:
                self.handlers.clear()
                if self.log is not None:
                    self.log.close()
                write_json(self.work / 'cleanup.json', status)

    def _cleanup_group(self):
        # Group cleanup does not depend on leader.poll(). Re-scan after TERM
        # because the leader can exit first and engines can spawn during shutdown.
        for signum, seconds in ((signal.SIGTERM, 10), (signal.SIGKILL, 2)):
            deadline = time.monotonic() + seconds
            while True:
                handles = owned_group_handles(self.pgid, self.owner_token)
                if not handles:
                    return
                try:
                    for _, descriptor in handles:
                        try:
                            signal.pidfd_send_signal(descriptor, signum)
                        except ProcessLookupError:
                            pass
                finally:
                    for _, descriptor in handles:
                        os.close(descriptor)
                if time.monotonic() >= deadline:
                    break
                time.sleep(min(0.05, max(0, deadline - time.monotonic())))
        handles = owned_group_handles(self.pgid, self.owner_token)
        try:
            if handles:
                raise RuntimeError('OWNED_ENGINE_GROUP_SURVIVED_CLEANUP')
        finally:
            for _, descriptor in handles:
                os.close(descriptor)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--python', required=True)
    parser.add_argument('--model-dir', type=Path, required=True, help='Pinned HF snapshots/<revision> directory')
    parser.add_argument('--asset-manifest', type=Path, required=True, help='External pinned full asset verification receipt')
    parser.add_argument('--enforce-eager', action='store_true')
    parser.add_argument('--startup-timeout', type=float, default=300,
                        help='Seconds for vLLM readiness (torch.compile + CUDA graph capture need more without eager)')
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True, help='Fresh research artifact directory')
    parser.add_argument('--context', type=int, default=32768)
    parser.add_argument('--workers', type=int, default=1)
    parser.add_argument('--slots', type=int, default=8)
    parser.add_argument('--timeout', type=float, default=90)
    parser.add_argument('--duration', type=float, default=1800)
    parser.add_argument('--max-calls', type=int, default=520)
    parser.add_argument('--limit', type=int, default=2)
    parser.add_argument('--token-budget', action='store_true',
                        help='Research arm: check requests against the served context in native tokens instead of the 60 000-byte cap')
    parser.add_argument('--checklist', action='store_true',
                        help='Research arm: build per-policy checklists at runtime and add them to the review')
    args = parser.parse_args(argv)
    if (not 1 <= args.workers <= args.slots or args.limit < 1 or args.max_calls < 1
            or not math.isfinite(args.duration) or args.duration <= 0):
        parser.error('invalid workers/slots/limit/call cap/duration')
    started = time.monotonic()
    deadline = started + args.duration
    input_hash = digest(args.input)
    rows = read_rows(args.input)[:args.limit]
    if digest(args.input) != input_hash:
        raise ValueError('INPUT_CHANGED_DURING_READ')
    args.output.mkdir(parents=True, exist_ok=False)
    write_json(args.output / 'protocol.json', dict(version=VERSION, model=MODEL, input_sha256=input_hash,
        rows=len(rows), limit=args.limit, workers=args.workers, slots=args.slots, context=args.context,
        timeout=args.timeout, duration=args.duration, max_calls=args.max_calls,
        prediction_contract='B2 legacy + unchanged submission recovery' + (' + policy checklist' if args.checklist else '')
                            + (' + native-token request budget' if args.token_budget else ''),
        checklist=args.checklist, token_budget=args.token_budget, code_sha256=digest(__file__)))
    traces, client = {}, None
    try:
        with OwnedVllmServer(args.python, args.model_dir, args.output, args.context, args.slots,
                             deadline=deadline, asset_manifest=args.asset_manifest,
                             enforce_eager=args.enforce_eager,
                             startup_timeout=args.startup_timeout) as server:
            client = VllmClient(server.port, args.context, args.output / 'calls', api_key=server.api_key,
                backend_manifest=server.manifest, timeout=args.timeout, deadline=deadline, max_calls=args.max_calls)
            from guardian_truth.v6fix.pipeline import Layers
            layers = Layers(client, MODEL, budget=20000, attempts=(0, 1), frules_max_tokens=700,
                            tolerate_component_errors=True)
            checklists = None
            if args.checklist:
                from guardian_truth.checklist.build import build as build_checklists
                built_at = time.monotonic()
                checklists = build_checklists(client, MODEL, rows, workers=args.workers)
                write_json(args.output / 'checklists.json', dict(seconds=time.monotonic() - built_at,
                           policies=len(checklists), checklists=checklists))
            with ThreadPoolExecutor(max_workers=args.workers) as executor:
                extra = {} if checklists is None else dict(checklists=checklists)   # off: unchanged call
                if args.token_budget:
                    extra['token_budget'] = TokenBudget(client)
                futures = {executor.submit(predict_one, row, client, layers, model=MODEL,
                                           provider='local-vllm', **extra): row['id'] for row in rows}
                for future in as_completed(futures):
                    identifier = futures[future]
                    # Unexpected code failures stop this diagnostic; never fabricate a prediction.
                    trace = future.result()
                    traces[identifier] = trace
                    with (args.output / 'traces.jsonl').open('a', encoding='utf-8') as stream:
                        stream.write(json.dumps(trace, ensure_ascii=False, allow_nan=False) + '\n')
            write_predictions(args.output / 'predictions.parquet',
                              [dict(id=row['id'], label=traces[row['id']]['binary']) for row in rows])
        write_json(args.output / 'DONE.json', dict(rows=len(traces), seconds=time.monotonic() - started,
            completion_http=client.completion_http, preflight_http=client.preflight_http,
            budget_preflight_http=client.budget_preflight_http,
            cache_hits=client.cache_hits, technical_calls=sum(c['transport']['status'] != 200 for c in client.calls),
            default_zero_fallbacks=sum((t.get('output_recovery') or {}).get('mode') == 'DEFAULT_ZERO' for t in traces.values())))
    except BaseException as error:
        write_json(args.output / 'STOPPED.json', dict(error=type(error).__name__, detail=str(error)[:500],
                   rows=len(traces), seconds=time.monotonic() - started,
                   completion_http=client.completion_http if client else 0))
        raise


if __name__ == '__main__':
    main()
