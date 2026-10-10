import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import textwrap
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT / 'submission'), str(ROOT / 'scripts')]
import platform_startup_probe as probe  # noqa: E402
import build_platform_startup_probe as builder  # noqa: E402

REV = probe.REVISION


def fake_server_script(tmp_path, behaviour):
    """A stand-in for 'python -m vllm...': serves /health and one completion, or dies."""
    script = tmp_path / 'fake_python.sh'
    server = tmp_path / 'fake_server.py'
    server.write_text(textwrap.dedent(f'''
        import http.server, json, sys, time
        args = sys.argv[1:]
        port = int(args[args.index('--port') + 1]); key = args[args.index('--api-key') + 1]
        assert '--load-format' in args and args[args.index('--load-format') + 1] == 'dummy'
        print('starting with key ' + key, flush=True)
        if {behaviour!r} == 'die':
            print('Traceback (most recent call last):\\nRuntimeError: libcuda.so cannot found!', flush=True)
            sys.exit(3)
        if {behaviour!r} == 'hang':
            time.sleep(60)
        class H(http.server.BaseHTTPRequestHandler):
            def log_message(self, *a): pass
            def do_GET(self):
                self.send_response(200); self.end_headers(); self.wfile.write(b'ok')
            def do_POST(self):
                ok = self.headers.get('Authorization') == 'Bearer ' + key
                body = json.dumps(dict(choices=[dict(message=dict(content='da'))])).encode()
                self.send_response(200 if ok else 401); self.end_headers(); self.wfile.write(body)
        http.server.HTTPServer(('127.0.0.1', port), H).serve_forever()
    '''))
    script.write_text(f'#!/bin/sh\nshift 2\nexec {sys.executable} {server} "$@"\n')
    script.chmod(0o755)
    return str(script)


def run(tmp_path, behaviour, timeout=20):
    port, key = probe.free_port(), 'k' * 48
    command = probe.server_command(fake_server_script(tmp_path, behaviour), tmp_path, port, key)
    return probe.run_server('t', command, dict(os.environ), tmp_path / 'log.txt', port, key, timeout)


def test_server_ready_and_completion_and_key_redacted(tmp_path, capsys):
    report = run(tmp_path, 'ok')
    assert report['outcome'] == 'SERVER_READY_AND_COMPLETED' and report['completion_status'] == 200
    out = capsys.readouterr().out
    assert 'k' * 48 not in out and 'GUARDIAN_STARTUP_PROBE' in out
    assert 'cleanup_error' not in report


def test_early_exit_reports_returncode_and_traceback_tail(tmp_path):
    report = run(tmp_path, 'die')
    assert report['outcome'] == 'SERVER_EXITED' and report['returncode'] == 3
    assert 'libcuda.so cannot found' in report['tail'] and 'k' * 48 not in report['tail']


def test_startup_timeout_kills_group(tmp_path):
    report = run(tmp_path, 'hang', timeout=3)
    assert report['outcome'] == 'STARTUP_TIMEOUT' and report['seconds'] < 10


def test_environment_mirrors_failed_archive(tmp_path, monkeypatch):
    monkeypatch.setenv('LD_LIBRARY_PATH', '/usr/local/nvidia/lib64:/opt/hpcx/ompi/lib')
    monkeypatch.setenv('PYTHONPATH', '/x')
    exact = probe.submission_environment(tmp_path, bundled=True)
    assert 'LD_LIBRARY_PATH' not in exact and 'PYTHONPATH' not in exact
    assert exact['GUARDIAN_BUNDLED_PYTHON'] == '1' and exact['TRITON_CACHE_DIR'].startswith(str(tmp_path))
    host = probe.submission_environment(tmp_path, bundled=False)
    assert host['LD_LIBRARY_PATH'] == '/usr/local/nvidia/lib64:/opt/hpcx/ompi/lib'


def test_server_command_matches_adapter_flags_plus_dummy(tmp_path):
    sys.path[:0] = [str(ROOT), str(ROOT / 'src')]
    from scripts import qwen_vllm_adapter as adapter
    server = adapter.OwnedVllmServer('py', tmp_path, tmp_path, 32768, 16, deadline=0,
                                     asset_manifest=tmp_path / 'm.json')
    expected = server.command()
    ours = probe.server_command('py', tmp_path, server.port, server.api_key)
    assert ours[:-2] == expected and ours[-2:] == ['--load-format', 'dummy']
    assert probe.MODEL == adapter.MODEL


def test_main_without_runtime_or_model_never_reads_input(tmp_path, monkeypatch, capsys):
    monkeypatch.setattr(probe.base, 'run_probe', lambda *a, **k: {})
    assert probe.main(['--input', str(tmp_path / 'missing.parquet'), '--output', str(tmp_path / 'o.parquet')]) == 2
    out = capsys.readouterr().out
    assert 'SKIPPED_NO_MODEL_METADATA' in out and 'SKIPPED_NO_BUNDLED_RUNTIME' in out
    assert not (tmp_path / 'o.parquet').exists()


def make_source_zip(path):
    with zipfile.ZipFile(path, 'w') as archive:
        def add(name, data=b'x', mode=0o644, kind=stat.S_IFREG):
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (kind | mode) << 16
            archive.writestr(info, data)
        add('runtime/', b'', 0o755, stat.S_IFDIR)
        add('runtime/python/run_python.sh', b'#!/bin/sh\n', 0o755)
        add('runtime/lib/libz.so.1.3', b'elf')
        add('runtime/lib/libz.so.1', b'libz.so.1.3', 0o777, stat.S_IFLNK)
        add(f'model/{REV}/config.json', b'{}')
        add(f'model/{REV}/tokenizer.json', b'{}')
        add(f'model/{REV}/model-00001-of-00002.safetensors', b'W' * 100)
        add('src/guardian_truth/x.py', b'')
        add('MODEL_MANIFEST.json', b'{}')


def test_builder_keeps_runtime_modes_links_and_metadata_but_no_weights(tmp_path):
    source = tmp_path / 'competition.zip'
    make_source_zip(source)
    receipt = builder.build(tmp_path / 'probe.zip', source_zip=source)
    with zipfile.ZipFile(tmp_path / 'probe.zip') as archive:
        names = set(archive.namelist())
        assert f'model/{REV}/config.json' in names and 'scripts/predict.py' in names
        assert not any(n.endswith('.safetensors') for n in names) and 'src/guardian_truth/x.py' not in names
        mode = archive.getinfo('runtime/python/run_python.sh').external_attr >> 16
        assert mode & 0o111
        link = archive.getinfo('runtime/lib/libz.so.1').external_attr >> 16
        assert stat.S_ISLNK(link) and archive.read('runtime/lib/libz.so.1') == b'libz.so.1.3'
        assert stat.S_IMODE(archive.getinfo('runtime/').external_attr >> 16) == 0o755
        manifest = json.loads(archive.read('MANIFEST.json'))
    assert manifest['counts']['skipped_weights_or_other'] == 3 and receipt['load_format'] == 'dummy'


def test_builder_refuses_overwrite_and_missing_config(tmp_path):
    source = tmp_path / 'competition.zip'
    make_source_zip(source)
    builder.build(tmp_path / 'probe.zip', source_zip=source)
    with pytest.raises(FileExistsError):
        builder.build(tmp_path / 'probe.zip', source_zip=source)
    empty = tmp_path / 'empty.zip'
    with zipfile.ZipFile(empty, 'w') as archive:
        archive.writestr('runtime/python/run_python.sh', b'')
    with pytest.raises(ValueError, match='MODEL_CONFIG_MISSING'):
        builder.build(tmp_path / 'p2.zip', source_zip=empty)


def test_builder_from_stage_directory(tmp_path):
    stage = tmp_path / 'stage'
    (stage / 'runtime/python').mkdir(parents=True)
    (stage / 'runtime/python/run_python.sh').write_text('#!/bin/sh\n')
    (stage / 'runtime/python/run_python.sh').chmod(0o755)
    (stage / 'runtime/python/link').symlink_to('run_python.sh')
    (stage / f'model/{REV}').mkdir(parents=True)
    (stage / f'model/{REV}/config.json').write_text('{}')
    (stage / f'model/{REV}/w.safetensors').write_bytes(b'W')
    builder.build(tmp_path / 'probe.zip', source_root=stage)
    with zipfile.ZipFile(tmp_path / 'probe.zip') as archive:
        assert stat.S_ISLNK(archive.getinfo('runtime/python/link').external_attr >> 16)
        assert f'model/{REV}/w.safetensors' not in archive.namelist()


def test_unpacked_probe_runs_end_to_end_without_gpu(tmp_path):
    source = tmp_path / 'competition.zip'
    make_source_zip(source)
    builder.build(tmp_path / 'probe.zip', source_zip=source)
    target = tmp_path / 'unpacked'
    with zipfile.ZipFile(tmp_path / 'probe.zip') as archive:
        for name in ('scripts/predict.py', 'scripts/platform_environment_probe.py'):
            (target / name).parent.mkdir(parents=True, exist_ok=True)
            (target / name).write_bytes(archive.read(name))
    result = subprocess.run([sys.executable, str(target / 'scripts/predict.py'), '--input', 'x', '--output', 'y'],
                            capture_output=True, text=True, timeout=600, cwd=tmp_path)
    assert result.returncode == 2, result.stderr[-2000:]
    assert 'GUARDIAN_STARTUP_PROBE {"probe": "done"' in result.stdout


WRAPPER = """#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
export CC="$ROOT/runtime/toolchain/usr/bin/gcc"
export CXX="$ROOT/runtime/toolchain/usr/bin/g++"
export PATH="$ROOT/runtime/toolchain/usr/bin:$ROOT/runtime/python/bin:/usr/bin:/bin"
export PATH="$ROOT/runtime/bin:$PATH"
echo "ROOT=$ROOT CC=$CC CXX=$CXX PATH=$PATH"
"""


def test_host_compiler_wrapper_swaps_only_compiler_and_keeps_root(tmp_path):
    root = tmp_path / 'archive'
    (root / 'runtime/python').mkdir(parents=True)
    (root / 'runtime/python/run_python.sh').write_text(WRAPPER)
    work = tmp_path / 'work'
    work.mkdir()
    target, replaced = probe.host_compiler_wrapper(root, work)
    assert target is not None and set(replaced.values()) == {1}
    out = subprocess.run([str(target)], capture_output=True, text=True, check=True).stdout
    assert f'ROOT={root} ' in out and 'CC=/usr/bin/gcc CXX=/usr/bin/g++' in out
    assert 'toolchain' not in out and out.strip().endswith('/usr/bin:/bin:' + str(root) + '/runtime/python/bin')
    original = WRAPPER.splitlines()
    changed = target.read_text().splitlines()
    assert [a for a, b in zip(original, changed) if a != b] == [original[2], original[4], original[5], original[6]]


def test_host_compiler_wrapper_refuses_unexpected_layout(tmp_path):
    root = tmp_path / 'archive'
    (root / 'runtime/python').mkdir(parents=True)
    (root / 'runtime/python/run_python.sh').write_text(WRAPPER.replace('export CC=', 'export MYCC='))
    target, replaced = probe.host_compiler_wrapper(root, tmp_path)
    assert target is None and replaced['cc'] == 0
