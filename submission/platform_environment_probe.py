"""Diagnostic-only platform entrypoint. No model, input reads or predictions.

Intentionally exits nonzero after printing evidence; never submit for scoring.
"""
import argparse
import importlib.metadata
import json
import os
from pathlib import Path
import secrets
import shutil
import signal
import subprocess
import sys
import tempfile
import threading
import time

TAIL_BYTES = 16384


def owned_group_handles(pgid, owner_token, proc_root=Path('/proc')):
    """Standalone adapter helper: pidfds pin verified session/group members."""
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


def require_cleanup_support():
    if os.name == 'nt':
        return 'direct_child'  # No Windows descendant-cleanup guarantee.
    if (sys.platform.startswith('linux') and hasattr(os, 'pidfd_open')
            and hasattr(signal, 'pidfd_send_signal') and Path('/proc').is_dir()):
        try:
            descriptor = os.pidfd_open(os.getpid(), 0)
            try:
                signal.pidfd_send_signal(descriptor, 0)
            finally:
                os.close(descriptor)
            return 'pidfd'
        except OSError:
            pass  # Old kernels / container syscall filters may block pidfd.
    if all(hasattr(os, name) for name in (
            'waitid', 'P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT', 'CLD_EXITED', 'killpg')):
        return 'unreaped_leader'
    raise RuntimeError('NO_SAFE_CHILD_GROUP_CLEANUP_AVAILABLE')


def wait_child(process, timeout):
    if not getattr(process, '_guardian_unreaped_leader', False):
        return process.wait(timeout=timeout)
    deadline = time.monotonic() + timeout
    while True:
        # WNOWAIT keeps our child (including its zombie) unreaped, pinning its
        # PID/PGID until cleanup has signalled the private process group.
        result = os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        if result is not None:
            return result.si_status if result.si_code == os.CLD_EXITED else -result.si_status
        remaining = deadline - time.monotonic()
        if remaining <= 0:
            raise subprocess.TimeoutExpired(process.args, timeout)
        time.sleep(min(0.05, remaining))


def cleanup_anchored_group(process):
    # Do not call poll()/wait() before group signalling: either would reap the
    # leader and permit PID reuse. ECHILD fails closed without signalling.
    for signum in (signal.SIGTERM, signal.SIGKILL):
        os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOHANG | os.WNOWAIT)
        try:
            os.killpg(process.pid, signum)
        except ProcessLookupError:
            pass
        if signum == signal.SIGTERM:
            time.sleep(0.2)
    process.wait(timeout=2)


def cleanup_child(process, owner_token):
    if getattr(process, '_guardian_unreaped_leader', False):
        cleanup_anchored_group(process)
        return
    if os.name == 'nt':
        if process.poll() is None:
            process.kill()
        process.wait(timeout=2)
        return
    # Even after the leader exits, its marked descendants need cleanup.
    for signum, seconds in ((signal.SIGTERM, 2), (signal.SIGKILL, 1)):
        deadline = time.monotonic() + seconds
        while True:
            handles = owned_group_handles(process.pid, owner_token)
            if not handles:
                process.wait(timeout=2)
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
    handles = owned_group_handles(process.pid, owner_token)
    try:
        if handles:
            raise RuntimeError('OWNED_PROBE_GROUP_SURVIVED_CLEANUP')
    finally:
        for _, descriptor in handles:
            os.close(descriptor)
        process.wait(timeout=2)


def sensitive_values(environment):
    return sorted({value for key, value in environment.items() if value and (
        key.upper().endswith(('_KEY', '_TOKEN')) or 'PASSWORD' in key.upper()
        or 'SECRET' in key.upper())}, key=len, reverse=True)


def redact(text, values, *, tail_boundary=False):
    for value in values:
        if tail_boundary:
            for length in range(min(len(value) - 1, len(text)), 0, -1):
                if text.startswith(value[-length:]):
                    text = '[REDACTED]' + text[length:]
                    break
        text = text.replace(value, '[REDACTED]')
    return text


def read_tail(stream, values):
    size = stream.seek(0, os.SEEK_END)
    offset = max(0, size - TAIL_BYTES)
    stream.seek(offset)
    text = redact(stream.read(TAIL_BYTES).decode('utf-8', errors='replace'),
                  values, tail_boundary=bool(offset))
    # emit() uses ensure_ascii: bound the escaped JSON string, including quotes.
    kept, budget = [], TAIL_BYTES - 2
    for character in reversed(text):
        cost = len(json.dumps(character, ensure_ascii=True)) - 2
        if cost > budget:
            break
        kept.append(character)
        budget -= cost
    return ''.join(reversed(kept))


def emit(name, value):
    print('GUARDIAN_ENV_PROBE ' + json.dumps(dict(probe=name, result=value),
                                           ensure_ascii=True, sort_keys=True), flush=True)


def run_probe(name, code, timeout=30, *, python=None, environment_overrides=None,
              argv=None, environment=None):
    """Bounded child. Defaults: host Python -c code in os.environ; argv/environment replace them."""
    process, handlers = None, {}
    launching, cleaning, pending_signal = False, False, None
    owner_token = secrets.token_hex(24)
    base_environment = os.environ if environment is None else environment
    environment = dict(base_environment, PYTHONDONTWRITEBYTECODE='1',
        OMP_NUM_THREADS='2', OPENBLAS_NUM_THREADS='1', GUARDIAN_VLLM_OWNER_TOKEN=owner_token)
    environment.update(environment_overrides or {})
    values = sorted(set(sensitive_values(os.environ) + sensitive_values(environment)),
                    key=len, reverse=True) + [owner_token]
    command = (list(argv) if argv is not None
               else [str(python or sys.executable), '-X', 'utf8', '-u', '-c', code])
    report = {}
    def interrupted(signum, frame):
        nonlocal pending_signal
        if launching or cleaning:
            pending_signal = signum
            return
        raise SystemExit(128 + signum)
    try:
        cleanup_mode = require_cleanup_support()
        if cleanup_mode is not None:
            report['cleanup_mode'] = cleanup_mode
        with tempfile.TemporaryFile() as stdout, tempfile.TemporaryFile() as stderr:
            try:
                if threading.current_thread() is threading.main_thread():
                    for signum in (signal.SIGTERM, signal.SIGINT):
                        handlers[signum] = signal.getsignal(signum)
                        signal.signal(signum, interrupted)
                    if cleanup_mode == 'unreaped_leader':
                        handlers[signal.SIGCHLD] = signal.getsignal(signal.SIGCHLD)
                        signal.signal(signal.SIGCHLD, signal.SIG_DFL)
                elif cleanup_mode == 'unreaped_leader':
                    raise RuntimeError('UNREAPED_LEADER_REQUIRES_MAIN_THREAD')
                launching = True
                process = subprocess.Popen(command,
                    stdout=stdout, stderr=stderr, env=environment, start_new_session=(os.name != 'nt'))
                process._guardian_unreaped_leader = cleanup_mode == 'unreaped_leader'
                launching = False
                if pending_signal is not None:
                    raise SystemExit(128 + pending_signal)
                try:
                    report['returncode'] = wait_child(process, timeout)
                except subprocess.TimeoutExpired:
                    report.update(error='TIMEOUT', seconds=timeout)
                except Exception as error:
                    report.update(error=type(error).__name__, detail=redact(str(error), values)[:1024])
            finally:
                cleaning = True
                launching = False
                if process is not None:
                    process._guardian_unreaped_leader = cleanup_mode == 'unreaped_leader'
                    try:
                        cleanup_child(process, owner_token)
                    except Exception as error:
                        report['cleanup_error'] = dict(error=type(error).__name__,
                            detail=redact(str(error), values)[:1024])
                for label, stream in (('stdout', stdout), ('stderr', stderr)):
                    try:
                        report[label] = read_tail(stream, values)
                    except Exception as error:
                        report[label + '_read_error'] = type(error).__name__
    except Exception as error:
        if report.get('error'):
            report['diagnostic_error'] = type(error).__name__
        else:
            report.update(error=type(error).__name__, detail=redact(str(error), values)[:1024])
    finally:
        for signum, previous in handlers.items():
            signal.signal(signum, previous)
        if pending_signal is not None:
            raise SystemExit(128 + pending_signal)
    emit(name, report)
    return report


def main(arguments=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', required=True)
    parser.add_argument('--output', required=True)
    parser.parse_args(arguments)
    emit('purpose', 'DIAGNOSTIC_ONLY_NO_INPUT_READ_NO_MODEL_NO_PREDICTIONS')
    emit('supervisor_capabilities', dict(platform=sys.platform, os_name=os.name,
        pidfd_open=hasattr(os, 'pidfd_open'), pidfd_send_signal=hasattr(signal, 'pidfd_send_signal'),
        waitid=hasattr(os, 'waitid'), wnowait=hasattr(os, 'WNOWAIT'), proc_present=Path('/proc').is_dir()))
    devices = {}
    for folder, pattern in ((Path('/dev'), 'nvidia*'), (Path('/proc/driver/nvidia/gpus'), '*')):
        try:
            devices[str(folder)] = [str(path) for path in sorted(folder.glob(pattern))][:64]
        except OSError as error:
            devices[str(folder)] = type(error).__name__
    emit('gpu_device_inventory', devices)
    versions = {}
    for name in ('vllm', 'torch', 'transformers', 'triton', 'flashinfer-python',
                 'flashinfer-cubin', 'flashinfer-jit-cache', 'pandas', 'pyarrow'):
        try:
            versions[name] = importlib.metadata.version(name)
        except Exception as error:
            versions[name] = 'UNAVAILABLE:' + type(error).__name__
    emit('host', dict(python=sys.version.split()[0], executable=sys.executable, packages=versions,
        selected_environment={key: (os.environ[key][:2048] if key in os.environ else None) for key in (
            'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES', 'LD_LIBRARY_PATH',
            'CUDA_HOME', 'CUDA_PATH', 'TRITON_LIBCUDA_PATH', 'FLASHINFER_WORKSPACE_BASE')},
        executables={name: shutil.which(name) for name in ('nvcc', 'ptxas', 'nvidia-smi', 'gcc', 'g++', 'ninja')}))
    memory = {}
    for name in ('memory.max', 'memory.current', 'memory.events'):
        path = Path('/sys/fs/cgroup') / name
        try:
            with path.open(encoding='utf-8') as stream:
                memory[name] = stream.read(4096)
        except OSError as error:
            memory[name] = type(error).__name__
    emit('cgroup', memory)
    run_probe('driver_libraries', '''import ctypes,ctypes.util,json
for name in ('cuda','nvidia-ml'):
 print(json.dumps(dict(library=name,find=ctypes.util.find_library(name))))
 try:
  ctypes.CDLL('lib'+name+'.so.1');print(name+': DLOPEN_OK')
 except Exception as error:print(name+': '+str(error))
''', 15)
    run_probe('nvidia_smi', '''import os,shutil
tool=shutil.which('nvidia-smi')
if tool:
 os.execv(tool,[tool,'--query-gpu=name,driver_version,memory.total,memory.free','--format=csv,noheader'])
else:print('NVIDIA_SMI_NOT_FOUND')
''', 15)
    run_probe('torch_cuda', '''import torch,json
print(json.dumps(dict(torch=torch.__version__,compiled_cuda=torch.version.cuda,available=torch.cuda.is_available())))
if torch.cuda.is_available():
 print(json.dumps(dict(name=torch.cuda.get_device_name(0),capability=torch.cuda.get_device_capability(0),devices=torch.cuda.device_count(),total_memory_bytes=torch.cuda.get_device_properties(0).total_memory,free_and_total_memory_bytes=torch.cuda.mem_get_info(0))))
 a=torch.ones((16,16),device='cuda',dtype=torch.float16)
 b=a@a;torch.cuda.synchronize();print('CUDA_SMALL_MATMUL_OK:'+str(b[0,0].item()))
''')
    run_probe('vllm_import', '''import vllm,json
print(json.dumps(dict(version=vllm.__version__,path=vllm.__file__)))
from vllm.platforms import current_platform
print('PLATFORM:'+str(current_platform))
''')
    run_probe('model_config_support', '''import json,transformers
from transformers import AutoConfig
print(json.dumps(dict(transformers=transformers.__version__,model_type='qwen3_5',architecture='Qwen3_5ForConditionalGeneration')))
try:
 config=AutoConfig.for_model('qwen3_5',text_config={'model_type':'qwen3_5_text'})
 print('AUTOCONFIG_OK:'+type(config).__name__)
except Exception as error:print('AUTOCONFIG_ERROR:'+type(error).__name__+':'+str(error))
try:
 from vllm.model_executor.models import ModelRegistry
 print('VLLM_ARCH_REGISTERED:'+str('Qwen3_5ForConditionalGeneration' in ModelRegistry.get_supported_archs()))
except Exception as error:print('VLLM_REGISTRY_ERROR:'+type(error).__name__+':'+str(error))
''')
    emit('done', 'DIAGNOSTIC_COMPLETE_NO_OUTPUT_FILE_EXPECTED_PLATFORM_FAILURE')
    return 2


if __name__ == '__main__':
    raise SystemExit(main())
