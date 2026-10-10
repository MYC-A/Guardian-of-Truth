"""Checked runtime contracts; local tests never import Torch or start vLLM."""
import io
import json
import os
from pathlib import Path
import signal
import subprocess
import sys
import time

import pytest

from submission import platform_startup_probe as probe


@pytest.fixture(autouse=True)
def fresh_budget(monkeypatch):
    monkeypatch.setattr(probe, 'STARTED', time.monotonic())


@pytest.fixture
def fake_server(tmp_path, monkeypatch):
    calls = []
    class Process:
        pid = 700
        args = ['fixture-server']
        def poll(self):
            return None
        def wait(self, timeout):
            return 0
    process = Process()
    monkeypatch.setattr(probe.base, 'require_cleanup_support', lambda: None)
    monkeypatch.setattr(probe.base, 'cleanup_child', lambda p, token: calls.append(('cleanup', p.pid)))
    monkeypatch.setattr(probe, 'wait_gpu_released', lambda *a: dict(released=True, used_mib=0))
    def spawn(argv, **kwargs):
        calls.append(('spawn', argv, kwargs['env']))
        kwargs['stdout'].write(b'fixture server log\n')
        return process
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    def http(url, payload=None, api_key=None, timeout=5):
        calls.append(('http', url, payload))
        if url.endswith('/v1/models'):
            return 200, json.dumps(dict(data=[dict(id=probe.MODEL, max_model_len=32768)]))
        if url.endswith('/v1/chat/completions'):
            return 200, json.dumps(dict(choices=[dict(message=dict(content='fixture response'))]))
        return 200, '{}'
    monkeypatch.setattr(probe, 'http', http)
    def run():
        return probe.run_server('fixture', ['fixture'], {}, tmp_path / 'server.log', 1234, 'local-key', 10)
    return run, calls, process


def test_server_profile_stays_graphs16_plus_dummy():
    command = probe.server_command('python', '/model', 1234, 'key')
    assert command[-2:] == ['--load-format', 'dummy']
    for key, value in (('--max-model-len', '32768'), ('--max-num-seqs', '16'),
                       ('--gpu-memory-utilization', '0.88'), ('--dtype', 'bfloat16'),
                       ('--kv-cache-dtype', 'auto')):
        assert command[command.index(key) + 1] == value
    assert '--enforce-eager' not in command
    assert '--enable-prefix-caching' in command and '--enable-chunked-prefill' in command


def test_ready_server_checks_identity_and_preserves_cleanup(fake_server):
    run, calls, _ = fake_server
    result = run()
    assert result['outcome'] == 'SERVER_READY_AND_COMPLETED'
    assert [call[0] for call in calls].count('cleanup') == 1
    posts = [call for call in calls if call[0] == 'http' and call[1].endswith('/v1/chat/completions')]
    assert posts[0][2]['chat_template_kwargs'] == dict(enable_thinking=False)
    assert result['log_capture'] == 'BOUNDED_HEAD_AND_TAIL'


@pytest.mark.parametrize('body', ['invalid json', '{}', '{"choices":[]}',
    '{"choices":[{"message":null}]}', '{"choices":[{"message":{"content":""}}]}'])
def test_http200_does_not_imply_valid_completion(fake_server, monkeypatch, body):
    run, calls, _ = fake_server
    original = probe.http
    def http(url, *args, **kwargs):
        if url.endswith('/v1/chat/completions'):
            return 200, body
        return original(url, *args, **kwargs)
    monkeypatch.setattr(probe, 'http', http)
    result = run()
    assert result['outcome'] == 'SERVER_READY_COMPLETION_FAILED'
    assert any(call[0] == 'cleanup' for call in calls)


@pytest.mark.parametrize('signal_point', ['spawn', 'cleanup'])
def test_parent_termination_is_deferred_through_owned_cleanup(fake_server, monkeypatch, signal_point):
    run, calls, process = fake_server
    original = {sig: signal.getsignal(sig) for sig in (signal.SIGTERM, signal.SIGINT)}
    if signal_point == 'spawn':
        def spawn(*args, **kwargs):
            signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
            return process
        monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    def cleanup(p, token):
        calls.append(('cleanup_begin', p.pid))
        # A second termination during cleanup must not abort before its end.
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        signal.getsignal(signal.SIGINT)(signal.SIGINT, None)
        calls.append(('cleanup_end', p.pid))
    monkeypatch.setattr(probe.base, 'cleanup_child', cleanup)
    with pytest.raises(SystemExit):
        run()
    assert ('cleanup_end', 700) in calls
    assert {sig: signal.getsignal(sig) for sig in original} == original


def test_pending_termination_survives_spawn_failure(fake_server, monkeypatch):
    run, _, _ = fake_server
    def spawn(*args, **kwargs):
        signal.getsignal(signal.SIGTERM)(signal.SIGTERM, None)
        raise OSError('fixture launch failure')
    monkeypatch.setattr(probe.subprocess, 'Popen', spawn)
    with pytest.raises(SystemExit) as error:
        run()
    assert error.value.code == 128 + signal.SIGTERM


def test_startup_cause_survives_cleanup_and_log_failure(fake_server, monkeypatch):
    run, _, process = fake_server
    monkeypatch.setattr(process, 'poll', lambda: 3)
    def cleanup(*args):
        raise OSError('cleanup failed')
    monkeypatch.setattr(probe.base, 'cleanup_child', cleanup)
    monkeypatch.setattr(probe, 'log_excerpt', lambda *a: dict(log_read_error='PermissionError'))
    result = run()
    assert result['outcome'] == 'SERVER_EXITED' and result['returncode'] == 3
    assert result['cleanup_error']['error'] == 'OSError'
    assert result['log_read_error'] == 'PermissionError'


@pytest.mark.skipif(not hasattr(signal, 'SIGALRM'), reason='POSIX alarm handler')
def test_budget_alarm_does_not_abort_teardown(fake_server, monkeypatch):
    run, calls, _ = fake_server
    def cleanup(*args):
        signal.getsignal(signal.SIGALRM)(signal.SIGALRM, None)
        calls.append(('cleanup_end', 700))
    monkeypatch.setattr(probe.base, 'cleanup_child', cleanup)
    result = run()
    assert ('cleanup_end', 700) in calls
    assert result['budget_expired_during_teardown']


def test_global_budget_caps_every_phase_and_stops_before_spawn(fake_server, monkeypatch):
    run, calls, _ = fake_server
    monkeypatch.setattr(probe, 'remaining', lambda: probe.TEARDOWN_RESERVE_SECONDS + 0.5)
    assert probe.phase_timeout(180) == 0.5
    monkeypatch.setattr(probe, 'remaining', lambda: probe.TEARDOWN_RESERVE_SECONDS)
    with pytest.raises(probe.BudgetExpired):
        probe.phase_timeout(180)
    result = run()
    assert result['outcome'] == 'PROBE_ERROR'
    assert not any(call[0] == 'spawn' for call in calls)


def test_http_timeout_uses_remaining_budget_and_reads_bounded_body(monkeypatch):
    calls = []
    class Reply:
        status = 200
        def __enter__(self): return self
        def __exit__(self, *args): pass
        def read(self, size):
            assert size == 4096
            return b'{}'
    class Opener:
        def open(self, request, timeout):
            calls.append(timeout)
            return Reply()
    monkeypatch.setattr(probe, 'remaining', lambda: probe.TEARDOWN_RESERVE_SECONDS + 0.25)
    monkeypatch.setattr(probe.urllib.request, 'build_opener', lambda *a: Opener())
    assert probe.http('http://127.0.0.1:1234/health', timeout=120) == (200, '{}')
    assert calls == [0.25]


def test_log_head_tail_reads_are_bounded_and_secrets_are_redacted():
    secret = 'LOCAL_TOKEN_48_CHARS_FIXTURE'
    payload = (b'begin ' + secret.encode() + b'\n' + b'\xff' * 200000 + secret.encode() + b'\nend')
    reads = []
    class Stream(io.BytesIO):
        def read(self, size=-1):
            reads.append(size)
            return super().read(size)
    class Log:
        def open(self, mode):
            assert mode == 'rb'
            return Stream(payload)
    result = probe.log_excerpt(Log(), [secret])
    assert reads == [probe.LOG_TAIL_BYTES, 8192]
    assert result['log_bytes'] == len(payload)
    assert secret not in json.dumps(result)
    assert len(json.dumps(result['tail'], ensure_ascii=True)) <= probe.LOG_TAIL_BYTES
    assert len(json.dumps(result['head'], ensure_ascii=True)) <= 8192


def test_main_runs_only_exact_and_host_with_fresh_cache_scopes(tmp_path, monkeypatch):
    script = tmp_path / 'scripts/predict.py'
    script.parent.mkdir()
    monkeypatch.setattr(probe, '__file__', str(script))
    (tmp_path / 'runtime/python').mkdir(parents=True)
    (tmp_path / 'runtime/python/run_python.sh').write_text('fixture')
    model = tmp_path / 'model' / probe.REVISION
    model.mkdir(parents=True)
    (model / 'config.json').write_text('{}')
    monkeypatch.setattr(probe, 'host_facts', lambda root: dict(bundled_runtime=True))
    calls = []
    def variant(name, python, environment, work, model_dir, **kwargs):
        calls.append((name, environment, kwargs))
        return None, dict(gpu_after_cleanup=dict(released=True))
    monkeypatch.setattr(probe, 'run_variant', variant)
    monkeypatch.setattr(probe.base, 'run_probe', lambda *a, **k: pytest.fail('no duplicate host checks'))
    assert probe.main(['--input', 'does-not-exist', '--output', str(tmp_path / 'predictions')]) == 2
    assert [row[0] for row in calls] == ['bundled_exact', 'host_vllm']
    assert calls[0][1]['TRITON_CACHE_DIR'] != calls[1][1]['TRITON_CACHE_DIR']
    assert calls[1][2]['checks'] is False
    assert not (tmp_path / 'predictions').exists()


def test_dependency_checks_do_not_warm_server_cache(tmp_path, monkeypatch):
    environment = probe.submission_environment(tmp_path / 'server-cache', bundled=True)
    calls = []
    monkeypatch.setattr(probe.base, 'run_probe', lambda *a, **k: calls.append(k['environment']) or {})
    monkeypatch.setattr(probe, 'run_server', lambda *a: {})
    probe.run_variant('exact', 'fixture-python', environment, tmp_path, tmp_path)
    assert calls[0]['TRITON_CACHE_DIR'] != environment['TRITON_CACHE_DIR']


@pytest.mark.parametrize('failed_stage', ['checks', 'server'])
def test_failed_cleanup_prevents_next_gpu_server(tmp_path, monkeypatch, capsys, failed_stage):
    script = tmp_path / 'scripts/predict.py'
    script.parent.mkdir()
    monkeypatch.setattr(probe, '__file__', str(script))
    model = tmp_path / 'model' / probe.REVISION
    model.mkdir(parents=True)
    (model / 'config.json').write_text('{}')
    monkeypatch.setattr(probe, 'host_facts', lambda root: dict(bundled_runtime=True))
    calls = []
    def variant(name, *args, **kwargs):
        calls.append(name)
        failure = dict(cleanup_error=dict(error='OSError'))
        return (failure, None) if failed_stage == 'checks' else (None, failure)
    monkeypatch.setattr(probe, 'run_variant', variant)
    assert probe.main(['--input', 'none', '--output', 'none']) == 2
    assert calls == ['bundled_exact']
    assert 'SKIPPED_AFTER_PREVIOUS_CLEANUP_FAILURE' in capsys.readouterr().out


@pytest.mark.skipif(not sys.platform.startswith('linux') or not hasattr(os, 'waitid'),
                   reason='Linux owned server descendant integration')
def test_linux_server_timeout_cleans_descendant(tmp_path, monkeypatch):
    # Standalone CPU Python children only, with no model/GPU imports.
    worker = 'import signal,time; signal.signal(signal.SIGTERM,signal.SIG_IGN); time.sleep(30)'
    code = ('import subprocess,sys,time; '
            f'child=subprocess.Popen([sys.executable,"-c",{worker!r}]); '
            'print("DESCENDANT_PID:"+str(child.pid),flush=True); time.sleep(30)')
    monkeypatch.setattr(probe.base, 'require_cleanup_support', lambda: 'unreaped_leader')
    monkeypatch.setattr(probe, 'http', lambda *a, **k: (_ for _ in ()).throw(OSError('not ready')))
    monkeypatch.setattr(probe, 'wait_gpu_released', lambda *a: dict(released=True))
    result = probe.run_server('cpu', [sys.executable, '-u', '-c', code], dict(os.environ),
                              tmp_path / 'log', 1234, 'fixture-key', 0.5)
    assert result['outcome'] == 'STARTUP_TIMEOUT' and 'cleanup_error' not in result
    pid = int(result['head'].split('DESCENDANT_PID:')[1].split()[0])
    try:
        state = (Path('/proc') / str(pid) / 'stat').read_text().rsplit(')', 1)[1].split()[0]
    except FileNotFoundError:
        state = None
    assert state in (None, 'Z')
