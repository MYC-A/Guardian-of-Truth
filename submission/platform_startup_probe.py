"""Diagnostic-only reproduction of the bundled vLLM startup. Never submit for scoring.

Reads no input and writes no predictions; exits 2 after GUARDIAN_STARTUP_PROBE done.
The archive carries runtime/ and model/<REVISION>/ metadata (config, tokenizer),
but no weight files: vLLM starts with --load-format dummy. This exercises
synthetic initialization and any reached engine/kernel/graph paths. Random
weights/scales, temporary allocations and checkpoint loading differ from the
real submission; neither memory equivalence nor checkpoint readiness is proven.
"""
import argparse
import json
import os
from pathlib import Path
try:
    import resource
except ImportError:
    resource = None
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import threading
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import platform_environment_probe as base  # noqa: E402

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
ENGINE_VERSION = '0.19.1'
MODEL = f'Qwen/Qwen3.8-27B-FP8@{REVISION}:vllm-{ENGINE_VERSION}'
WEIGHT_SUFFIXES = ('.safetensors', '.bin', '.pt', '.pth', '.gguf', '.npz')
LOG_TAIL_BYTES = 24576
TOTAL_BUDGET_SECONDS = 1500   # platform limit is 1800; keep margin for teardown
SERVER_RESERVE_SECONDS = 330  # do not start a server variant with less time left
SERVER_STARTUP_SECONDS = 420
TEARDOWN_RESERVE_SECONDS = 10
STARTED = time.monotonic()


class BudgetExpired(TimeoutError):
    pass

CHECKS = r'''
import ctypes, json, os, sys, traceback, subprocess, tempfile
from pathlib import Path
failures = []
def step(label, action):
    try:
        print(label + ':' + str(action()), flush=True)
    except BaseException as error:
        failures.append(label)
        print(label + ':ERROR:' + type(error).__name__ + ':' + str(error)[:400], flush=True)
        print(''.join(traceback.format_exception(error)[-3:])[-1200:], flush=True)
print('PYTHON:' + sys.version.split()[0] + ' ' + sys.executable)
print('LD_LIBRARY_PATH:' + repr(os.environ.get('LD_LIBRARY_PATH')))
def compile_library(cpp=False, lto=False):
    compiler = os.environ['CXX' if cpp else 'CC']
    source = ('#include <vector>\n#include <numeric>\n'
              'extern "C" int answer(){std::vector<int> v{10,12,20};return std::accumulate(v.begin(),v.end(),0);}\n'
              if cpp else '#include <stdlib.h>\nint answer(){return abs(-42);}\n')
    with tempfile.TemporaryDirectory(prefix='guardian-compiler-') as folder:
        path = Path(folder) / ('probe.cpp' if cpp else 'probe.c')
        path.write_text(source)
        library = Path(folder) / 'probe.so'
        argv = [compiler, '-O2', '-shared', '-fPIC', str(path), '-o', str(library)]
        if lto:
            argv.append('-flto')
        result = subprocess.run(argv, capture_output=True, text=True, timeout=45)
        if result.returncode:
            raise RuntimeError(result.stderr[-1600:])
        value = ctypes.CDLL(str(library)).answer()
        if value != 42:
            raise RuntimeError('COMPILED_LIBRARY_WRONG_RESULT:' + str(value))
        return 'OK compiler=' + compiler + ' answer=42'
step('c_compile_and_load', compile_library)
step('cpp_compile_and_load', lambda: compile_library(cpp=True))
step('cpp_lto_compile_and_load', lambda: compile_library(cpp=True, lto=True))
for name in ('cuda', 'nvidia-ml'):
    step(name + '_dlopen', lambda name=name: ctypes.CDLL('lib' + name + '.so.1') and 'OK')
for module in ('torch', 'triton', 'transformers', 'vllm', 'flashinfer'):
    step(module + '_import', lambda module=module: getattr(__import__(module), '__version__', '?'))
def torch_matmul():
    import torch
    x = torch.ones((16, 16), device='cuda', dtype=torch.float16)
    value = (x @ x)[0, 0].item(); torch.cuda.synchronize()
    return 'OK ' + str(value) + ' cuda=' + str(torch.version.cuda) + ' ' + torch.cuda.get_device_name(0)
step('torch_cuda_matmul', torch_matmul)
def libcuda_dirs():
    from triton.backends.nvidia import driver
    return json.dumps(driver.libcuda_dirs())
step('triton_libcuda_dirs', libcuda_dirs)
def triton_kernel():
    import torch, triton, triton.language as tl
    @triton.jit
    def add(a, b, out, n, BLOCK: tl.constexpr):
        offsets = tl.program_id(0) * BLOCK + tl.arange(0, BLOCK)
        mask = offsets < n
        tl.store(out + offsets, tl.load(a + offsets, mask=mask) + tl.load(b + offsets, mask=mask), mask=mask)
    a = torch.ones(1000, device='cuda'); out = torch.empty_like(a)
    add[(4,)](a, a, out, 1000, BLOCK=256); torch.cuda.synchronize()
    return 'OK ' + str(out[0].item())
step('triton_kernel', triton_kernel)
def vllm_platform():
    from vllm.platforms import current_platform
    return type(current_platform).__name__
step('vllm_platform', vllm_platform)
print('CHECKS_SUMMARY:' + json.dumps(dict(failed=failures)), flush=True)
sys.exit(1 if failures else 0)
'''


def emit(name, value):
    print('GUARDIAN_STARTUP_PROBE ' + json.dumps(dict(probe=name, result=value), ensure_ascii=True,
                                                  sort_keys=True), flush=True)


def remaining():
    return max(0, TOTAL_BUDGET_SECONDS - (time.monotonic() - STARTED))


def phase_timeout(limit):
    timeout = min(limit, remaining() - TEARDOWN_RESERVE_SECONDS)
    if timeout <= 0:
        raise BudgetExpired('WHOLE_PROBE_BUDGET')
    return timeout


def owned_probe(*args, **kwargs):
    """The helper's bounded wait reserves cleanup; don't interrupt that cleanup."""
    alarm_active = (hasattr(signal, 'getitimer') and
                    threading.current_thread() is threading.main_thread() and
                    signal.getitimer(signal.ITIMER_REAL)[0] > 0)
    if alarm_active:
        signal.setitimer(signal.ITIMER_REAL, 0)
    try:
        return base.run_probe(*args, **kwargs)
    finally:
        if alarm_active and remaining() > TEARDOWN_RESERVE_SECONDS:
            signal.setitimer(signal.ITIMER_REAL, remaining() - TEARDOWN_RESERVE_SECONDS)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def host_facts(root):
    facts = dict(uname=list(os.uname()) if hasattr(os, 'uname') else None,
                 cpu_count=os.cpu_count(), home=os.environ.get('HOME'),
                 cwd=os.getcwd(), archive_root=str(root))
    try:
        facts['home_writable'] = os.access(os.environ.get('HOME', '/nonexistent'), os.W_OK)
    except OSError:
        facts['home_writable'] = None
    usage = {}
    for path in ('/dev/shm', tempfile.gettempdir(), str(root), os.environ.get('HOME') or '/'):
        try:
            total, used, free = shutil.disk_usage(path)
            usage[path] = dict(total_gib=round(total / 2**30, 2), free_gib=round(free / 2**30, 2))
        except OSError as error:
            usage[path] = type(error).__name__
    facts['disk'] = usage
    facts['rlimits'] = {} if resource is None else {name: list(resource.getrlimit(getattr(resource, name))) for name in (
        'RLIMIT_NOFILE', 'RLIMIT_NPROC', 'RLIMIT_MEMLOCK', 'RLIMIT_STACK', 'RLIMIT_AS')
        if hasattr(resource, name)}
    conf = {}
    for path in [Path('/etc/ld.so.conf'), *sorted(Path('/etc/ld.so.conf.d').glob('*'))][:32]:
        try:
            with path.open(encoding='utf-8', errors='replace') as stream:
                conf[str(path)] = stream.read(512)
        except OSError as error:
            conf[str(path)] = type(error).__name__
    facts['ld_so_conf'] = conf
    wrapper = root / 'runtime/python/run_python.sh'
    facts['bundled_runtime'] = wrapper.is_file()
    if wrapper.is_file():
        with wrapper.open(encoding='utf-8', errors='replace') as stream:
            facts['run_python_sh'] = stream.read(4096)
    model = root / 'model' / REVISION
    facts['model_metadata_files'] = sorted(path.name for path in model.iterdir())[:64] if model.is_dir() else None
    facts['weights_present'] = bool(model.is_dir() and any(
        path.suffix in WEIGHT_SUFFIXES for path in model.iterdir()))
    return facts


def submission_environment(cache, *, bundled):
    """Mirror the failed archive: run() caches, bootstrap flags, adapter removals."""
    environment = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       HF_HOME=str(cache / 'huggingface'), XDG_CACHE_HOME=str(cache),
                       VLLM_CACHE_ROOT=str(cache / 'vllm'), TRITON_CACHE_DIR=str(cache / 'triton'),
                       TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                       VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', SPT_NOENV='1')
    environment.pop('GUARDIAN_USE_SYSTEM_COMPILER', None)
    if bundled:
        environment.update(GUARDIAN_BUNDLED_PYTHON='1', PYTHONUTF8='1')
        for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
            environment.pop(key, None)
    return environment


def server_command(python, model_dir, port, api_key):
    """The adapter's exact flags plus --load-format dummy (no weight files shipped)."""
    return [python, '-m', 'vllm.entrypoints.openai.api_server', '--model', str(model_dir),
            '--tokenizer', str(model_dir), '--served-model-name', MODEL,
            '--host', '127.0.0.1', '--port', str(port), '--api-key', api_key,
            '--max-model-len', '32768', '--max-num-seqs', '16',
            '--gpu-memory-utilization', '0.88', '--generation-config', 'vllm',
            '--chat-template-content-format', 'string',
            '--enable-prefix-caching', '--enable-chunked-prefill', '--dtype', 'bfloat16',
            '--kv-cache-dtype', 'auto', '--load-format', 'dummy']


def exited(process, unreaped):
    if unreaped:
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if result is None:
            return None
        return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
    return process.poll()


def http(url, payload=None, api_key=None, timeout=5):
    request = urllib.request.Request(url, data=None if payload is None else json.dumps(payload).encode(),
                                     headers={'Content-Type': 'application/json'})
    if api_key:
        request.add_header('Authorization', 'Bearer ' + api_key)
    class NoRedirect(urllib.request.HTTPRedirectHandler):
        def redirect_request(self, *args):
            return None
    with urllib.request.build_opener(urllib.request.ProxyHandler({}), NoRedirect()).open(
            request, timeout=phase_timeout(timeout)) as response:
        return response.status, response.read(4096).decode('utf-8', 'replace')


def log_excerpt(path, values):
    def bounded(raw, limit, boundary=False):
        text = base.redact(raw.decode('utf-8', 'replace'), values, tail_boundary=boundary)
        kept, budget = [], limit - 2
        for character in reversed(text):
            cost = len(json.dumps(character, ensure_ascii=True)) - 2
            if cost > budget:
                break
            kept.append(character)
            budget -= cost
        return ''.join(reversed(kept))
    try:
        with path.open('rb') as stream:
            size = stream.seek(0, os.SEEK_END)
            offset = max(0, size - LOG_TAIL_BYTES)
            stream.seek(offset)
            tail = stream.read(LOG_TAIL_BYTES)
            stream.seek(0)
            head = stream.read(8192)
        report = dict(log_bytes=size, tail=bounded(tail, LOG_TAIL_BYTES, bool(offset)),
                      head=bounded(head, 8192), log_capture='BOUNDED_HEAD_AND_TAIL')
        return report
    except OSError as error:
        return dict(log_read_error=type(error).__name__,
                    log_read_detail=base.redact(str(error), values)[:512])


def wait_gpu_released(limit=90):
    tool = shutil.which('nvidia-smi')
    if not tool:
        return 'NVIDIA_SMI_NOT_FOUND'
    try:
        deadline = time.monotonic() + phase_timeout(limit)
    except BudgetExpired:
        return dict(released=None, outcome='SKIPPED_FOR_TIME_BUDGET')
    used = None
    while time.monotonic() < deadline:
        try:
            # Use the same owned supervisor; file captures avoid pipe/RAM leaks.
            code = ('import os; os.execv(' + repr(tool) + ', [' + repr(tool) +
                    ", '--query-gpu=memory.used', '--format=csv,noheader,nounits'])")
            result = owned_probe('gpu_release_check', code,
                timeout=phase_timeout(min(10, max(0, deadline - time.monotonic()))))
            used = int(result.get('stdout', '').split()[0]) if result.get('returncode') == 0 else None
            if result.get('cleanup_error'):
                return dict(used_mib=used, released=False, cleanup_error=result['cleanup_error'])
            if used is not None and used < 2048:
                return dict(used_mib=used, released=True)
        except BudgetExpired:
            break
        except (ValueError, IndexError):
            pass
        time.sleep(min(2, max(0, deadline - time.monotonic()), max(0, remaining() - TEARDOWN_RESERVE_SECONDS)))
    return dict(used_mib=used, released=False)


def run_server(name, argv, environment, log_path, port, api_key, startup_timeout):
    """Bounded synthetic engine check with the base supervisor's ownership rules."""
    owner_token = secrets.token_hex(24)
    environment = dict(environment, GUARDIAN_VLLM_OWNER_TOKEN=owner_token)
    values = sorted(set(base.sensitive_values(environment)) | {api_key, owner_token}, key=len, reverse=True)
    report, process, handlers = dict(startup_timeout=startup_timeout), None, {}
    launching, cleaning, pending_signal, pending_budget = False, False, None, False
    started = time.monotonic()
    def interrupted(signum, frame):
        nonlocal pending_signal
        if launching or cleaning:
            pending_signal = signum
            return
        raise SystemExit(128 + signum)
    def budget_interrupted(signum, frame):
        nonlocal pending_budget
        if launching or cleaning:
            pending_budget = True
            return
        raise BudgetExpired('WHOLE_PROBE_BUDGET')
    try:
        startup_timeout = phase_timeout(startup_timeout)
        report['startup_timeout'] = startup_timeout
        mode = base.require_cleanup_support()
        report['cleanup_mode'] = mode
        unreaped = mode == 'unreaped_leader'
        if threading.current_thread() is threading.main_thread():
            for signum in (signal.SIGTERM, signal.SIGINT):
                handlers[signum] = signal.getsignal(signum)
                signal.signal(signum, interrupted)
            if unreaped:
                handlers[signal.SIGCHLD] = signal.getsignal(signal.SIGCHLD)
                signal.signal(signal.SIGCHLD, signal.SIG_DFL)
            if hasattr(signal, 'SIGALRM'):
                handlers[signal.SIGALRM] = signal.getsignal(signal.SIGALRM)
                signal.signal(signal.SIGALRM, budget_interrupted)
        elif unreaped:
            raise RuntimeError('UNREAPED_LEADER_REQUIRES_MAIN_THREAD')
        with log_path.open('wb') as log:
            launching = True
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       env=environment, start_new_session=(os.name != 'nt'))
        process._guardian_unreaped_leader = unreaped
        launching = False
        if pending_signal is not None:
            raise SystemExit(128 + pending_signal)
        while True:
            code = exited(process, unreaped)
            elapsed = round(time.monotonic() - started, 1)
            if code is not None:
                report.update(outcome='SERVER_EXITED', returncode=code, seconds=elapsed)
                break
            if elapsed >= startup_timeout or remaining() <= TEARDOWN_RESERVE_SECONDS:
                report.update(outcome='STARTUP_TIMEOUT', seconds=elapsed)
                break
            try:
                status, _ = http(f'http://127.0.0.1:{port}/health', timeout=3)
            except (urllib.error.URLError, OSError, ValueError):
                status = None
            if status == 200:
                report.update(ready_seconds=elapsed)
                try:
                    _, models = http(f'http://127.0.0.1:{port}/v1/models', api_key=api_key, timeout=5)
                    served = [item for item in json.loads(models).get('data', [])
                              if item.get('id') == MODEL and item.get('max_model_len') == 32768]
                    if len(served) != 1:
                        raise ValueError('SERVED_IDENTITY_OR_CONTEXT_MISMATCH')
                    status, body = http(f'http://127.0.0.1:{port}/v1/chat/completions', dict(
                        model=MODEL, max_tokens=8, temperature=0,
                        chat_template_kwargs=dict(enable_thinking=False),
                        messages=[dict(role='user', content='Ответь одним словом: да или нет?')]),
                        api_key=api_key, timeout=120)
                    report.update(completion_status=status,
                                  completion_response=base.redact(body, values)[:4096])
                    data = json.loads(body)
                    choices = data.get('choices') if isinstance(data, dict) else None
                    message = (choices[0].get('message') if isinstance(choices, list) and
                               len(choices) == 1 and isinstance(choices[0], dict) else None)
                    if (status != 200 or not isinstance(message, dict) or
                            not isinstance(message.get('content'), str) or not message['content'].strip()):
                        # A random checkpoint may immediately emit EOS. Report
                        # this separately; never infer useful real-weight output.
                        usage = data.get('usage', {}) if isinstance(data, dict) else {}
                        tokens = usage.get('completion_tokens') if isinstance(usage, dict) else None
                        if (status == 200 and isinstance(message, dict) and
                                message.get('content') in ('', None) and
                                isinstance(tokens, int) and not isinstance(tokens, bool) and tokens > 0 and
                                choices[0].get('finish_reason') in ('stop', 'length')):
                            report.update(outcome='SERVER_READY_DUMMY_EMPTY_COMPLETION',
                                          completion_tokens=tokens, finish_reason=choices[0]['finish_reason'],
                                          seconds=round(time.monotonic() - started, 1))
                            break
                        raise ValueError('INVALID_COMPLETION_RESPONSE')
                    report.update(outcome='SERVER_READY_AND_COMPLETED', completion_status=status,
                                  completion_excerpt=base.redact(body[:600], values),
                                  seconds=round(time.monotonic() - started, 1))
                except Exception as error:
                    if isinstance(error, urllib.error.HTTPError):
                        report.update(completion_status=error.code,
                                      completion_response=base.redact(error.read(4096).decode('utf-8', 'replace'), values))
                    report.update(outcome='SERVER_READY_COMPLETION_FAILED', error=type(error).__name__,
                                  detail=base.redact(str(error), values)[:600],
                                  seconds=round(time.monotonic() - started, 1))
                break
            time.sleep(min(2, max(0, startup_timeout - (time.monotonic() - started)),
                           max(0, remaining() - TEARDOWN_RESERVE_SECONDS)))
    except Exception as error:
        report.update(outcome=report.get('outcome', 'PROBE_ERROR'), error=type(error).__name__,
                      detail=base.redact(str(error), values)[:1024])
    finally:
        cleaning = True
        launching = False
        if process is not None:
            process._guardian_unreaped_leader = unreaped
            try:
                base.cleanup_child(process, owner_token)
            except Exception as error:
                report['cleanup_error'] = dict(error=type(error).__name__,
                                               detail=base.redact(str(error), values)[:600])
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
        if pending_signal is not None:
            raise SystemExit(128 + pending_signal)
    report.update(log_excerpt(log_path, values))
    if pending_budget:
        report['budget_expired_during_teardown'] = True
    report['gpu_after_cleanup'] = wait_gpu_released()
    emit(name, report)
    return report


def run_variant(name, python, environment, work, model_dir, *, server=True, checks=True):
    child = None
    if checks:
        script = work / (name + '_checks.py')
        script.write_text(CHECKS, encoding='utf-8')
        # Dependency checks have a separate fresh cache; server remains cold.
        check_environment = submission_environment(work / (name + '_checks_cache'),
            bundled=environment.get('GUARDIAN_BUNDLED_PYTHON') == '1')
        if environment.get('GUARDIAN_USE_SYSTEM_COMPILER') == '1':
            check_environment['GUARDIAN_USE_SYSTEM_COMPILER'] = '1'
        child = owned_probe(name + '_checks', None, timeout=phase_timeout(180),
                               argv=[python, '-X', 'utf8', '-u', str(script)], environment=check_environment)
        if child.get('cleanup_error'):
            emit(name + '_server', dict(outcome='SKIPPED_AFTER_CHECK_CLEANUP_FAILURE'))
            return child, None
    if not server:
        return child, None
    if remaining() < SERVER_RESERVE_SECONDS:
        emit(name + '_server', dict(outcome='SKIPPED_FOR_TIME_BUDGET', remaining_seconds=round(remaining())))
        return child, None
    port, api_key = free_port(), secrets.token_hex(24)
    timeout = phase_timeout(SERVER_STARTUP_SECONDS)
    return child, run_server(name + '_server', server_command(python, model_dir, port, api_key), environment,
                             work / (name + '_vllm-server.log'), port, api_key, timeout)


def variant_passed(checks, server):
    return bool(checks and checks.get('returncode') == 0 and not checks.get('cleanup_error') and
                server and not server.get('cleanup_error') and server.get('outcome') in (
                    'SERVER_READY_AND_COMPLETED', 'SERVER_READY_DUMMY_EMPTY_COMPLETION') and
                isinstance(server.get('gpu_after_cleanup'), dict) and
                server['gpu_after_cleanup'].get('released') is True)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.parse_args(arguments)
    root = Path(__file__).resolve().parents[1]
    emit('purpose', 'DIAGNOSTIC_ONLY_NO_INPUT_READ_NO_PREDICTIONS_DUMMY_WEIGHTS')
    old_alarm = None
    # A one-shot supervisor deadline interrupts Python waits/network calls;
    # reserve teardown time inside the total budget. Children have owned cleanup.
    if (threading.current_thread() is threading.main_thread() and hasattr(signal, 'setitimer')
            and hasattr(signal, 'SIGALRM')):
        def budget_alarm(signum, frame):
            raise BudgetExpired('WHOLE_PROBE_BUDGET')
        old_alarm = (signal.getsignal(signal.SIGALRM), signal.getitimer(signal.ITIMER_REAL))
        signal.signal(signal.SIGALRM, budget_alarm)
        signal.setitimer(signal.ITIMER_REAL, max(0.001, remaining() - TEARDOWN_RESERVE_SECONDS))
    try:
        phase_timeout(TOTAL_BUDGET_SECONDS)
        facts = host_facts(root)
        emit('host_facts', facts)
        work = Path(tempfile.mkdtemp(prefix='guardian-startup-probe-'))
        model_dir = root / 'model' / REVISION
        can_serve = model_dir.is_dir() and (model_dir / 'config.json').is_file()
        if not can_serve:
            emit('server_variants', 'SKIPPED_NO_MODEL_METADATA')
        wrapper = root / 'runtime/python/run_python.sh'
        checked, exact, system_checks, system_server = None, None, None, None
        if facts['bundled_runtime']:
            checked, exact = run_variant('bundled_exact', str(wrapper),
                submission_environment(work / 'exact_server_cache', bundled=True), work, model_dir,
                server=can_serve)
        else:
            emit('bundled_variants', 'SKIPPED_NO_BUNDLED_RUNTIME')
        if can_serve:
            if (checked and checked.get('cleanup_error')) or (exact and (exact.get('cleanup_error') or
                    isinstance(exact.get('gpu_after_cleanup'), dict) and
                    exact['gpu_after_cleanup'].get('released') is False)):
                emit('host_vllm_server', dict(outcome='SKIPPED_AFTER_PREVIOUS_CLEANUP_FAILURE'))
            else:
                if wrapper.is_file() and 'GUARDIAN_USE_SYSTEM_COMPILER' in wrapper.read_text():
                    environment = submission_environment(work / 'system_compiler_server_cache', bundled=True)
                    environment['GUARDIAN_USE_SYSTEM_COMPILER'] = '1'
                    system_checks, system_server = run_variant(
                        'bundled_system_compiler', str(wrapper), environment, work, model_dir)
                else:
                    run_variant('host_vllm', sys.executable,
                        submission_environment(work / 'host_server_cache', bundled=False), work, model_dir,
                        checks=False)
        emit('validation', dict(bundled_compiler_passed=variant_passed(checked, exact),
                               system_compiler_passed=variant_passed(system_checks, system_server),
                               scope='DUMMY_WEIGHTS_RUNTIME_ONLY_REAL_CHECKPOINT_AND_QUALITY_UNTESTED'))
    except BudgetExpired:
        emit('budget', dict(outcome='WHOLE_PROBE_BUDGET', remaining_seconds=round(remaining(), 1)))
    finally:
        if old_alarm is not None:
            signal.setitimer(signal.ITIMER_REAL, 0)
            signal.signal(signal.SIGALRM, old_alarm[0])
            signal.setitimer(signal.ITIMER_REAL, *old_alarm[1])
    emit('done', dict(result='DIAGNOSTIC_COMPLETE_NO_OUTPUT_FILE_EXPECTED_PLATFORM_FAILURE',
                      seconds=round(time.monotonic() - STARTED, 1)))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
