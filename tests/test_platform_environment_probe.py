import json
import io
import os
from pathlib import Path
import re
import signal
import subprocess
import sys
import time
import pytest
from submission import platform_environment_probe as probe


def test_probe_never_reads_input_or_creates_fake_predictions(tmp_path, monkeypatch, capsys):
    source = tmp_path/'input.parquet'
    source.write_bytes(b'PRIVATE_BENCHMARK_DATA_NOT_TO_PRINT')
    target = tmp_path/'predictions.parquet'
    monkeypatch.setenv('MISTRAL_API_KEY', 'PRIVATE_KEY_NOT_TO_PRINT')
    monkeypatch.setattr(probe.importlib.metadata, 'version', lambda name: 'fixture')
    calls = []
    monkeypatch.setattr(probe, 'run_probe', lambda name, code, timeout=30: calls.append(name))
    assert probe.main(['--input', str(source), '--output', str(target)]) == 2
    output = capsys.readouterr().out
    assert 'DIAGNOSTIC_COMPLETE' in output
    assert 'PRIVATE_BENCHMARK_DATA_NOT_TO_PRINT' not in output
    assert 'PRIVATE_KEY_NOT_TO_PRINT' not in output
    assert not target.exists()
    assert calls == ['driver_libraries', 'nvidia_smi', 'torch_cuda', 'vllm_import', 'model_config_support']


def test_child_timeout_is_recorded_and_does_not_abort_other_probes(monkeypatch, capsys):
    events = []
    class Process:
        pid = 123456789
        def wait(self, timeout):
            raise probe.subprocess.TimeoutExpired('fixture', timeout)
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', lambda *a, **k: Process())
    monkeypatch.setattr(probe, 'cleanup_child', lambda process, token: events.append(process.pid))
    result = probe.run_probe('slow', 'unused', timeout=1)
    assert result == dict(error='TIMEOUT', seconds=1, stdout='', stderr='')
    assert events == [123456789]
    assert json.loads(capsys.readouterr().out.split(' ', 1)[1])['probe'] == 'slow'


def test_child_output_is_bounded_even_on_import_failure(monkeypatch, capsys):
    streams, cleanups = [], []
    class Process:
        pid = 123456789
        def wait(self, timeout):
            return 1
    def spawn(*args, **kwargs):
        assert 'capture_output' not in kwargs
        streams.extend((kwargs['stdout'], kwargs['stderr']))
        assert all(stream.fileno() >= 0 for stream in streams)
        streams[0].write(b'x' * 100000)
        streams[1].write(b'Traceback\n' + b'y' * 100000)
        return Process()
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    monkeypatch.setattr(probe, 'cleanup_child', lambda *a: cleanups.append(True))
    result = probe.run_probe('broken', 'unused')
    assert result['returncode'] == 1
    assert len(result['stdout']) == len(result['stderr']) == probe.TAIL_BYTES - 2
    assert cleanups == [True] and all(stream.closed for stream in streams)


def test_probe_accepts_nonexistent_input_without_reading_it(tmp_path, monkeypatch):
    monkeypatch.setattr(probe.importlib.metadata, 'version', lambda name: 'fixture')
    monkeypatch.setattr(probe, 'run_probe', lambda *a: None)
    assert probe.main(['--input', str(tmp_path / 'missing'), '--output', str(tmp_path / 'output')]) == 2
    assert not (tmp_path / 'output').exists()


@pytest.mark.parametrize('payload', [b'\xff' * 100000, ('\U0001f680' * 20000).encode(), b'a\\"\n' * 10000],
                         ids=['invalid-utf8', 'non-bmp-unicode', 'json-escapes'])
def test_tail_read_and_rendered_json_are_bounded(payload):
    class BoundedReader(io.BytesIO):
        def read(self, size=-1):
            assert size == probe.TAIL_BYTES
            return super().read(size)
    tail = probe.read_tail(BoundedReader(payload), [])
    assert len(json.dumps(tail, ensure_ascii=True).encode('ascii')) <= probe.TAIL_BYTES
    assert tail


def test_child_environment_secrets_and_owner_marker_are_redacted(monkeypatch, capsys):
    monkeypatch.setenv('MISTRAL_API_KEY', 'known-secret-key')
    monkeypatch.setenv('SESSION_TOKEN', 'known-token')
    monkeypatch.setenv('DB_PASSWORD', 'known-password')
    monkeypatch.setenv('CLIENT_SECRET', 'known-client-secret')
    monkeypatch.setenv('LD_LIBRARY_PATH', '/preserve/driver/path')
    class Process:
        pid = 123456789
        def wait(self, timeout):
            return 0
    def spawn(*args, **kwargs):
        assert kwargs['env']['LD_LIBRARY_PATH'] == '/preserve/driver/path'
        text = '|'.join(kwargs['env'][key] for key in (
            'MISTRAL_API_KEY', 'SESSION_TOKEN', 'DB_PASSWORD', 'CLIENT_SECRET', 'GUARDIAN_VLLM_OWNER_TOKEN'))
        kwargs['stdout'].write(text.encode())
        kwargs['stderr'].write(text.encode())
        return Process()
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    monkeypatch.setattr(probe, 'cleanup_child', lambda *a: None)
    report = probe.run_probe('secrets', 'unused')
    output = capsys.readouterr().out
    assert report['stdout'].count('[REDACTED]') == report['stderr'].count('[REDACTED]') == 5
    assert 'known-' not in output


def test_tail_boundary_cannot_publish_partial_secret():
    secret = 'fixture-secret-value'
    raw = b'prefix' + secret.encode() + b'x' * (probe.TAIL_BYTES - 8)
    tail = probe.read_tail(io.BytesIO(raw), [secret])
    assert secret[-8:] not in tail


def test_spawn_and_cleanup_errors_are_recorded_without_stopping_next_probe(monkeypatch):
    original = PermissionError('SECRET_VALUE cannot execute')
    monkeypatch.setenv('APP_SECRET', 'SECRET_VALUE')
    def failed(*args, **kwargs):
        raise original
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', failed)
    report = probe.run_probe('spawn_failure', 'unused')
    assert report['error'] == 'PermissionError'
    assert 'SECRET_VALUE' not in report['detail']
    class Process:
        pid = 123456789
        def wait(self, timeout):
            raise subprocess.TimeoutExpired('fixture', timeout)
    monkeypatch.setattr(probe.subprocess, 'Popen', lambda *a, **k: Process())
    def failed_cleanup(*args):
        raise OSError('fixture cleanup failure')
    monkeypatch.setattr(probe, 'cleanup_child', failed_cleanup)
    report = probe.run_probe('next_timeout', 'unused', timeout=1)
    assert report['error'] == 'TIMEOUT'
    assert report['cleanup_error']['error'] == 'OSError'


def test_parent_interruption_cleans_child_closes_files_and_restores_signals(monkeypatch):
    streams, cleanup = [], []
    previous = {signum: signal.getsignal(signum) for signum in (signal.SIGTERM, signal.SIGINT)}
    class Process:
        pid = 123456789
        def wait(self, timeout):
            raise SystemExit(143)
    def spawn(*args, **kwargs):
        streams.extend((kwargs['stdout'], kwargs['stderr']))
        return Process()
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    monkeypatch.setattr(probe, 'cleanup_child', lambda *a: cleanup.append(True))
    with pytest.raises(SystemExit) as error:
        probe.run_probe('parent_exit', 'unused')
    assert error.value.code == 143
    assert cleanup == [True] and all(stream.closed for stream in streams)
    assert {signum: signal.getsignal(signum) for signum in previous} == previous


@pytest.mark.parametrize('environment,session,state,expected', [
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0', 700, 'S', True),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=foreign\0', 700, 'S', False),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0', 701, 'S', False),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0', 700, 'Z', False),
])
def test_copied_pidfd_helper_excludes_foreign_sessions_and_reused_pgid(
        tmp_path, monkeypatch, environment, session, state, expected):
    process = tmp_path / '701'
    process.mkdir()
    (process / 'stat').write_text(f'701 (probe (child)) {state} 1 700 {session} 0')
    (process / 'environ').write_bytes(environment)
    closed = []
    monkeypatch.setattr(probe.os, 'pidfd_open', lambda *a: 42, raising=False)
    monkeypatch.setattr(probe.os, 'close', closed.append)
    handles = probe.owned_group_handles(700, 'ours', proc_root=tmp_path)
    assert handles == ([(701, 42)] if expected else [])
    assert closed == ([] if expected or state == 'Z' or session != 700 else [42])
    if handles:
        probe.os.close(handles[0][1])


def test_linux_cleanup_uses_verified_pidfds_after_leader_exit(monkeypatch):
    calls, closed, waited = [], [], []
    scans = iter([[(701, 42)], []])
    class Process:
        pid = 700
        def poll(self):
            return 0
        def wait(self, timeout):
            waited.append(timeout)
    with monkeypatch.context() as patch:
        patch.setattr(probe.os, 'name', 'posix')
        patch.setattr(probe.signal, 'SIGKILL', 9, raising=False)
        patch.setattr(probe, 'owned_group_handles', lambda *a: next(scans))
        patch.setattr(probe.signal, 'pidfd_send_signal', lambda fd, sig: calls.append((fd, sig)), raising=False)
        patch.setattr(probe.os, 'close', closed.append)
        patch.setattr(probe.time, 'sleep', lambda seconds: None)
        probe.cleanup_child(Process(), 'ours')
    assert calls == [(42, signal.SIGTERM)] and closed == [42] and waited == [2]


def test_temporary_file_failure_does_not_start_child(monkeypatch):
    def unavailable():
        raise OSError('fixture no temporary space')
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.tempfile, 'TemporaryFile', unavailable)
    monkeypatch.setattr(probe.subprocess, 'Popen', lambda *a, **k: pytest.fail('must not spawn'))
    report = probe.run_probe('no_temp', 'unused')
    assert report['error'] == 'OSError'


@pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'pidfd_open')
                   or not hasattr(signal, 'pidfd_send_signal'), reason='Linux pidfd cleanup integration')
@pytest.mark.parametrize('leader_exits', [True, False])
def test_real_owned_descendant_is_cleaned_after_leader_exit_or_timeout(leader_exits):
    # CPU-only child; no torch/vLLM import or GPU operation.
    worker = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'
    code = ('import subprocess,sys,time\n'
            f'child=subprocess.Popen([sys.executable,"-c",{worker!r}])\n'
            'print("DESCENDANT_PID:"+str(child.pid),flush=True)\n'
            'time.sleep(0.2)\n' + ('' if leader_exits else 'time.sleep(30)\n'))
    started = time.monotonic()
    report = probe.run_probe('real_cleanup', code, timeout=0.5)
    assert time.monotonic() - started < 8
    assert 'cleanup_error' not in report
    assert report.get('error') == (None if leader_exits else 'TIMEOUT')
    pid = int(re.search(r'DESCENDANT_PID:(\d+)', report['stdout']).group(1))
    try:
        state = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0]
    except FileNotFoundError:
        state = None
    assert state in (None, 'Z')


def test_unset_and_empty_cuda_environment_are_distinct(tmp_path, monkeypatch, capsys):
    monkeypatch.delenv('CUDA_VISIBLE_DEVICES', raising=False)
    monkeypatch.setenv('CUDA_HOME', '')
    monkeypatch.setattr(probe.importlib.metadata, 'version', lambda name: 'fixture')
    monkeypatch.setattr(probe, 'run_probe', lambda *args: None)
    probe.main(['--input', str(tmp_path/'absent'), '--output', str(tmp_path/'output')])
    reports = [json.loads(row.split(' ', 1)[1]) for row in capsys.readouterr().out.splitlines()]
    host = next(row['result'] for row in reports if row['probe'] == 'host')
    assert host['selected_environment']['CUDA_VISIBLE_DEVICES'] is None
    assert host['selected_environment']['CUDA_HOME'] == ''


def test_waitid_mode_observes_exit_without_reaping(monkeypatch):
    from types import SimpleNamespace
    calls = []
    process = SimpleNamespace(pid=700, _guardian_unreaped_leader=True)
    process.wait = lambda **kwargs: pytest.fail('must not reap leader before cleanup')
    def observe(which, pid, options):
        calls.append((which, pid, options))
        return SimpleNamespace(si_code=1, si_status=7)
    for name, value in dict(P_PID=1, WEXITED=4, WNOHANG=1, WNOWAIT=0x1000000, CLD_EXITED=1).items():
        monkeypatch.setattr(probe.os, name, value, raising=False)
    monkeypatch.setattr(probe.os, 'waitid', observe, raising=False)
    assert probe.wait_child(process, 1) == 7
    assert calls == [(1, 700, 4 | 1 | 0x1000000)]


def test_waitid_cleanup_signals_group_before_reap_and_refuses_foreign_pid(monkeypatch):
    from types import SimpleNamespace
    calls = []
    process = SimpleNamespace(pid=700, wait=lambda **kwargs: calls.append('reap'))
    monkeypatch.setattr(probe.os, 'waitid', lambda *args: calls.append('owned_unreaped'), raising=False)
    monkeypatch.setattr(probe.os, 'killpg', lambda pid, sig: calls.append(('signal', pid, sig)), raising=False)
    monkeypatch.setattr(probe.signal, 'SIGKILL', 9, raising=False)
    for name, value in dict(P_PID=1, WEXITED=4, WNOHANG=1, WNOWAIT=0x1000000).items():
        monkeypatch.setattr(probe.os, name, value, raising=False)
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: None)
    monkeypatch.setattr(probe, 'live_group_members', lambda pgid: [])
    probe.cleanup_anchored_group(process)
    assert calls == ['owned_unreaped', ('signal', 700, signal.SIGTERM),
                     'owned_unreaped', ('signal', 700, 9), 'owned_unreaped', 'reap']
    calls.clear()
    def foreign(*args):
        raise ChildProcessError('no longer our unreaped child')
    monkeypatch.setattr(probe.os, 'waitid', foreign)
    with pytest.raises(ChildProcessError):
        probe.cleanup_anchored_group(process)
    assert calls == []


def test_anchored_cleanup_waits_for_pending_kill_before_reaping(monkeypatch):
    from types import SimpleNamespace
    calls = []
    process = SimpleNamespace(pid=700, wait=lambda **kwargs: calls.append('reap'))
    for name, value in dict(P_PID=1, WEXITED=4, WNOHANG=1, WNOWAIT=0x1000000).items():
        monkeypatch.setattr(probe.os, name, value, raising=False)
    monkeypatch.setattr(probe.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(probe.os, 'waitid', lambda *a: calls.append('verify_anchor'), raising=False)
    monkeypatch.setattr(probe.os, 'killpg', lambda pid, sig: calls.append(('signal', sig)), raising=False)
    states = iter([[701], [701], []])
    def members(pgid):
        assert pgid == 700 and 'reap' not in calls
        result = next(states)
        calls.append(('live_group', bool(result)))
        return result
    monkeypatch.setattr(probe, 'live_group_members', members)
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: None)
    probe.cleanup_anchored_group(process)
    assert calls[-2:] == [('live_group', False), 'reap']
    assert calls.index(('signal', 9)) < calls.index(('live_group', True))
    assert calls.count('verify_anchor') == 5


def test_anchored_cleanup_reports_live_group_timeout_without_reaping(monkeypatch):
    from types import SimpleNamespace
    process = SimpleNamespace(pid=700, wait=lambda **kwargs: pytest.fail('must retain anchor on failure'))
    for name, value in dict(P_PID=1, WEXITED=4, WNOHANG=1, WNOWAIT=0x1000000).items():
        monkeypatch.setattr(probe.os, name, value, raising=False)
    monkeypatch.setattr(probe.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(probe.os, 'waitid', lambda *a: None, raising=False)
    monkeypatch.setattr(probe.os, 'killpg', lambda *a: None, raising=False)
    monkeypatch.setattr(probe, 'live_group_members', lambda pgid: [701])
    clock = iter([0, 0.5, 1.0, 1.5])
    monkeypatch.setattr(probe.time, 'monotonic', lambda: next(clock))
    monkeypatch.setattr(probe.time, 'sleep', lambda seconds: None)
    with pytest.raises(RuntimeError, match='OWNED_PROBE_GROUP_SURVIVED_CLEANUP'):
        probe.cleanup_anchored_group(process)


def test_live_group_scan_excludes_zombies_and_other_sessions(tmp_path):
    for pid, state, group, session in ((701, 'R', 700, 700), (702, 'Z', 700, 700),
                                        (703, 'S', 700, 703), (704, 'S', 704, 700)):
        folder = tmp_path / str(pid)
        folder.mkdir()
        (folder / 'stat').write_text(f'{pid} (worker (child)) {state} 1 {group} {session} 0')
    assert probe.live_group_members(700, proc_root=tmp_path) == [701]


@pytest.mark.parametrize('pidfd_present', [False, True])
def test_missing_or_blocked_pidfd_uses_waitid(monkeypatch, pidfd_present):
    with monkeypatch.context() as patch:
        patch.setattr(probe.os, 'name', 'posix')
        patch.setattr(probe.sys, 'platform', 'linux')
        for name in ('waitid', 'P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT', 'CLD_EXITED', 'killpg'):
            patch.setattr(probe.os, name, 1, raising=False)
        if pidfd_present:
            def blocked(*args):
                raise PermissionError('pidfd blocked')
            patch.setattr(probe.os, 'pidfd_open', blocked, raising=False)
            patch.setattr(probe.signal, 'pidfd_send_signal', lambda *args: None, raising=False)
        else:
            patch.delattr(probe.os, 'pidfd_open', raising=False)
        assert probe.require_cleanup_support() == 'unreaped_leader'


def test_blocked_pidfd_send_closes_descriptor_before_fallback(monkeypatch):
    closed = []
    with monkeypatch.context() as patch:
        patch.setattr(probe.os, 'name', 'posix')
        patch.setattr(probe.sys, 'platform', 'linux')
        patch.setattr(probe, 'Path', lambda *args: type('Proc', (), {'is_dir': lambda self: True})())
        for name in ('waitid', 'P_PID', 'WEXITED', 'WNOHANG', 'WNOWAIT', 'CLD_EXITED', 'killpg'):
            patch.setattr(probe.os, name, 1, raising=False)
        patch.setattr(probe.os, 'pidfd_open', lambda *args: 42, raising=False)
        def blocked(*args):
            raise PermissionError('pidfd_send_signal blocked')
        patch.setattr(probe.signal, 'pidfd_send_signal', blocked, raising=False)
        patch.setattr(probe.os, 'close', closed.append)
        assert probe.require_cleanup_support() == 'unreaped_leader'
    assert closed == [42]


def test_signal_during_spawn_is_deferred_until_cleanup_can_own_child(monkeypatch):
    cleanup = []
    class Process:
        pid = 700
    def spawn(*args, **kwargs):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        return Process()
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    monkeypatch.setattr(probe, 'cleanup_child', lambda *args: cleanup.append(True))
    with pytest.raises(SystemExit) as error:
        probe.run_probe('signal_during_spawn', 'unused')
    assert error.value.code == 128 + signal.SIGTERM
    assert cleanup == [True]


@pytest.mark.parametrize('spawn_fails', [False, True])
def test_pending_termination_survives_spawn_error_and_cannot_interrupt_cleanup(monkeypatch, spawn_fails):
    events = []
    previous = signal.getsignal(signal.SIGTERM)
    class Process:
        pid = 700
        def wait(self, timeout):
            return 0
    def spawn(*args, **kwargs):
        if spawn_fails:
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            raise OSError('spawn failed after signal')
        return Process()
    def cleanup(*args):
        events.append('cleanup_start')
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        events.append('cleanup_complete')
    monkeypatch.setattr(probe, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    monkeypatch.setattr(probe, 'cleanup_child', cleanup)
    with pytest.raises(SystemExit) as error:
        probe.run_probe('signal_in_cleanup', 'unused')
    assert error.value.code == 128 + signal.SIGTERM
    assert events == ([] if spawn_fails else ['cleanup_start', 'cleanup_complete'])
    assert signal.getsignal(signal.SIGTERM) == previous


@pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'waitid'),
                   reason='Linux unreaped-leader cleanup integration')
@pytest.mark.parametrize('leader_exits', [True, False])
def test_real_fallback_descendant_cleanup_without_pidfd(leader_exits, monkeypatch):
    monkeypatch.delattr(probe.os, 'pidfd_open', raising=False)
    test_real_owned_descendant_is_cleaned_after_leader_exit_or_timeout(leader_exits)
