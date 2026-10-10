"""Diagnostic-only reproduction of the bundled vLLM startup. Never submit for scoring.

Reads no input and writes no predictions; exits 2 after GUARDIAN_STARTUP_PROBE done.
The archive carries runtime/ and model/<REVISION>/ metadata (config, tokenizer),
but no weight files: vLLM starts with --load-format dummy (random weights of the
real FP8 architecture), so engine, kernels, CUDA graphs and memory match the
real start while the upload stays a few GB.
"""
import argparse
import json
import os
from pathlib import Path
import resource
import secrets
import shutil
import signal
import socket
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request

sys.path.insert(0, str(Path(__file__).resolve().parent))
import platform_environment_probe as base  # noqa: E402

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
ENGINE_VERSION = '0.19.1'
MODEL = f'Qwen/Qwen3.8-27B-FP8@{REVISION}:vllm-{ENGINE_VERSION}'
DRIVER_BRIDGE = '/usr/local/nvidia/lib64:/usr/local/nvidia/lib'
WEIGHT_SUFFIXES = ('.safetensors', '.bin', '.pt', '.pth', '.gguf', '.npz')
LOG_TAIL_BYTES = 24576
TOTAL_BUDGET_SECONDS = 1500   # platform limit is 1800; keep margin for teardown
SERVER_RESERVE_SECONDS = 330  # do not start a server variant with less time left
SERVER_STARTUP_SECONDS = 420
STARTED = time.monotonic()

CHECKS = r'''
import ctypes, json, os, sys, traceback
def step(label, action):
    try:
        print(label + ':' + str(action()), flush=True)
    except BaseException as error:
        print(label + ':ERROR:' + type(error).__name__ + ':' + str(error)[:400], flush=True)
        print(''.join(traceback.format_exception(error)[-3:])[-1200:], flush=True)
print('PYTHON:' + sys.version.split()[0] + ' ' + sys.executable)
print('LD_LIBRARY_PATH:' + repr(os.environ.get('LD_LIBRARY_PATH')))
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
'''


def emit(name, value):
    print('GUARDIAN_STARTUP_PROBE ' + json.dumps(dict(probe=name, result=value), ensure_ascii=False,
                                                  sort_keys=True), flush=True)


def remaining():
    return TOTAL_BUDGET_SECONDS - (time.monotonic() - STARTED)


def free_port():
    with socket.socket() as probe:
        probe.bind(('127.0.0.1', 0))
        return probe.getsockname()[1]


def host_facts(root):
    facts = dict(uname=list(os.uname()), cpu_count=os.cpu_count(), home=os.environ.get('HOME'),
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
    facts['rlimits'] = {name: list(resource.getrlimit(getattr(resource, name))) for name in (
        'RLIMIT_NOFILE', 'RLIMIT_NPROC', 'RLIMIT_MEMLOCK', 'RLIMIT_STACK', 'RLIMIT_AS')
        if hasattr(resource, name)}
    conf = {}
    for path in [Path('/etc/ld.so.conf'), *sorted(Path('/etc/ld.so.conf.d').glob('*'))][:32]:
        try:
            conf[str(path)] = path.read_text(errors='replace')[:512]
        except OSError as error:
            conf[str(path)] = type(error).__name__
    facts['ld_so_conf'] = conf
    tool = shutil.which('ldconfig') or ('/sbin/ldconfig' if Path('/sbin/ldconfig').exists() else None)
    if tool:
        try:
            listing = subprocess.run([tool, '-p'], capture_output=True, text=True, timeout=15).stdout
            facts['ldconfig_driver_entries'] = [line.strip() for line in listing.splitlines()
                                                if 'libcuda' in line or 'libnvidia-ml' in line][:16]
        except Exception as error:
            facts['ldconfig_driver_entries'] = type(error).__name__
    else:
        facts['ldconfig_driver_entries'] = 'LDCONFIG_NOT_FOUND'
    wrapper = root / 'runtime/python/run_python.sh'
    facts['bundled_runtime'] = wrapper.is_file()
    if wrapper.is_file():
        facts['run_python_sh'] = wrapper.read_text(errors='replace')[:4096]
        facts['bundled_driver_libraries'] = sorted(path.name for path in (root / 'runtime').rglob('libcuda.so*'))[:8]
    model = root / 'model' / REVISION
    facts['model_metadata_files'] = sorted(path.name for path in model.iterdir())[:64] if model.is_dir() else None
    facts['weights_present'] = bool(model.is_dir() and any(
        path.suffix in WEIGHT_SUFFIXES for path in model.iterdir()))
    return facts


def submission_environment(cache, *, bundled, driver_bridge=False):
    """Mirror the failed archive: run() caches, bootstrap flags, adapter removals."""
    environment = dict(os.environ, HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                       HF_HOME=str(cache / 'huggingface'), XDG_CACHE_HOME=str(cache),
                       VLLM_CACHE_ROOT=str(cache / 'vllm'), TRITON_CACHE_DIR=str(cache / 'triton'),
                       TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                       VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1',
                       PYTHONNOUSERSITE='1', SPT_NOENV='1')
    if bundled:
        environment.update(GUARDIAN_BUNDLED_PYTHON='1', PYTHONUTF8='1')
        for key in ('LD_LIBRARY_PATH', 'PYTHONPATH', 'PYTHONHOME', 'LD_PRELOAD'):
            environment.pop(key, None)
        if driver_bridge:
            environment['LD_LIBRARY_PATH'] = DRIVER_BRIDGE
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
    with urllib.request.build_opener(urllib.request.ProxyHandler({})).open(request, timeout=timeout) as response:
        return response.status, response.read(4096).decode('utf-8', 'replace')


def log_excerpt(path, values):
    data = path.read_bytes() if path.exists() else b''
    text = data.decode('utf-8', 'replace')
    report = dict(log_bytes=len(data), tail=base.redact(text[-LOG_TAIL_BYTES:], values, tail_boundary=True))
    marker = text.find('Traceback (most recent call last)')
    if 0 <= marker < len(text) - LOG_TAIL_BYTES:
        report['first_traceback'] = base.redact(text[marker:marker + 8192], values)
    return report


def wait_gpu_released(limit=90):
    tool = shutil.which('nvidia-smi')
    if not tool:
        return 'NVIDIA_SMI_NOT_FOUND'
    deadline = time.monotonic() + limit
    used = None
    while time.monotonic() < deadline:
        try:
            used = int(subprocess.run([tool, '--query-gpu=memory.used', '--format=csv,noheader,nounits'],
                                      capture_output=True, text=True, timeout=10).stdout.split()[0])
            if used < 2048:
                return dict(used_mib=used, released=True)
        except Exception:
            pass
        time.sleep(2)
    return dict(used_mib=used, released=False)


def run_server(name, argv, environment, log_path, port, api_key, startup_timeout):
    """Start one server, wait for /health, send one tiny completion, always clean the group."""
    owner_token = secrets.token_hex(24)
    environment = dict(environment, GUARDIAN_VLLM_OWNER_TOKEN=owner_token)
    values = sorted(set(base.sensitive_values(environment)) | {api_key, owner_token}, key=len, reverse=True)
    report, process, handlers = dict(startup_timeout=startup_timeout), None, {}
    started = time.monotonic()
    try:
        mode = base.require_cleanup_support()
        report['cleanup_mode'] = mode
        unreaped = mode == 'unreaped_leader'
        if unreaped:
            handlers[signal.SIGCHLD] = signal.getsignal(signal.SIGCHLD)
            signal.signal(signal.SIGCHLD, signal.SIG_DFL)
        with log_path.open('wb') as log:
            process = subprocess.Popen(argv, stdout=log, stderr=subprocess.STDOUT, stdin=subprocess.DEVNULL,
                                       env=environment, start_new_session=True)
        process._guardian_unreaped_leader = unreaped
        while True:
            code = exited(process, unreaped)
            elapsed = round(time.monotonic() - started, 1)
            if code is not None:
                report.update(outcome='SERVER_EXITED', returncode=code, seconds=elapsed)
                break
            if elapsed > startup_timeout:
                report.update(outcome='STARTUP_TIMEOUT', seconds=elapsed)
                break
            try:
                status, _ = http(f'http://127.0.0.1:{port}/health', timeout=3)
            except (urllib.error.URLError, OSError, ValueError):
                status = None
            if status == 200:
                report.update(ready_seconds=elapsed)
                try:
                    status, body = http(f'http://127.0.0.1:{port}/v1/chat/completions', dict(
                        model=MODEL, max_tokens=8, temperature=0,
                        messages=[dict(role='user', content='Ответь одним словом: да или нет?')]),
                        api_key=api_key, timeout=120)
                    report.update(outcome='SERVER_READY_AND_COMPLETED', completion_status=status,
                                  completion_excerpt=base.redact(body[:600], values),
                                  seconds=round(time.monotonic() - started, 1))
                except Exception as error:
                    report.update(outcome='SERVER_READY_COMPLETION_FAILED', error=type(error).__name__,
                                  detail=base.redact(str(error), values)[:600],
                                  seconds=round(time.monotonic() - started, 1))
                break
            time.sleep(2)
    except Exception as error:
        report.update(outcome=report.get('outcome', 'PROBE_ERROR'), error=type(error).__name__,
                      detail=base.redact(str(error), values)[:1024])
    finally:
        if process is not None:
            try:
                base.cleanup_child(process, owner_token)
            except Exception as error:
                report['cleanup_error'] = dict(error=type(error).__name__,
                                               detail=base.redact(str(error), values)[:600])
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
    report.update(log_excerpt(log_path, values))
    report['gpu_after_cleanup'] = wait_gpu_released()
    emit(name, report)
    return report


def run_variant(name, python, environment, work, model_dir, *, server=True, checks=True):
    child = None
    if checks:
        script = work / (name + '_checks.py')
        script.write_text(CHECKS, encoding='utf-8')
        child = base.run_probe(name + '_checks', None, timeout=180,
                               argv=[python, '-X', 'utf8', '-u', str(script)], environment=environment)
    if not server:
        return child, None
    if remaining() < SERVER_RESERVE_SECONDS:
        emit(name + '_server', dict(outcome='SKIPPED_FOR_TIME_BUDGET', remaining_seconds=round(remaining())))
        return child, None
    port, api_key = free_port(), secrets.token_hex(24)
    timeout = min(SERVER_STARTUP_SECONDS, max(60, remaining() - 120))
    return child, run_server(name + '_server', server_command(python, model_dir, port, api_key), environment,
                             work / (name + '_vllm-server.log'), port, api_key, timeout)


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.parse_args(arguments)
    root = Path(__file__).resolve().parents[1]
    emit('purpose', 'DIAGNOSTIC_ONLY_NO_INPUT_READ_NO_PREDICTIONS_DUMMY_WEIGHTS')
    facts = host_facts(root)
    emit('host_facts', facts)
    work = Path(tempfile.mkdtemp(prefix='guardian-startup-probe-'))
    cache = work / 'cache'
    cache.mkdir()
    model_dir = root / 'model' / REVISION
    # Host Python with the driver path removed: does libcuda resolve without LD_LIBRARY_PATH?
    stripped = dict(os.environ)
    stripped.pop('LD_LIBRARY_PATH', None)
    checks = work / 'host_checks.py'
    checks.write_text(CHECKS, encoding='utf-8')
    for label, environment in (('host_default_env', dict(os.environ)), ('host_without_ld_library_path', stripped)):
        base.run_probe(label, None, timeout=180, argv=[sys.executable, '-X', 'utf8', '-u', str(checks)],
                       environment=environment)
    can_serve = model_dir.is_dir() and (model_dir / 'config.json').is_file()
    if not can_serve:
        emit('server_variants', 'SKIPPED_NO_MODEL_METADATA')
    wrapper = root / 'runtime/python/run_python.sh'
    if facts['bundled_runtime']:
        _, exact = run_variant('bundled_exact', str(wrapper),
                               submission_environment(cache / 'exact', bundled=True), work, model_dir,
                               server=can_serve)
        if exact is None or not str(exact.get('outcome', '')).startswith('SERVER_READY'):
            run_variant('bundled_driver_bridge', str(wrapper),
                        submission_environment(cache / 'bridge', bundled=True, driver_bridge=True),
                        work, model_dir, server=can_serve)
    else:
        emit('bundled_variants', 'SKIPPED_NO_BUNDLED_RUNTIME')
    if can_serve:
        run_variant('host_vllm', sys.executable, submission_environment(cache / 'host', bundled=False),
                    work, model_dir, checks=False)
    emit('done', dict(result='DIAGNOSTIC_COMPLETE_NO_OUTPUT_FILE_EXPECTED_PLATFORM_FAILURE',
                      seconds=round(time.monotonic() - STARTED, 1)))
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
