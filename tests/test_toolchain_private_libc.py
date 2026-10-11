import hashlib
import json
from pathlib import Path
import stat
import zipfile

import pytest

from scripts import build_platform_startup_probe as builder
from scripts.repair_vllm_toolchain import archive_patches
from scripts.vllm_bundle_toolchain import wrapper_text


def fixture_source(tmp_path):
    stage = Path('/fixture')
    base = 'runtime/toolchain/usr/libexec/gcc/x86_64-linux-gnu/13/'
    programs = ['runtime/toolchain/usr/bin/' + p for p in ('gcc', 'g++', 'as', 'ld')]
    programs += [base + p for p in ('cc1', 'cc1plus', 'collect2', 'lto1', 'lto-wrapper')]
    data = {name: wrapper_text(stage, stage / name, stage / (name + '.real'),
                driver=name.endswith(('/gcc', '/g++')), machine='x86_64-linux-gnu', version='13')
                .replace('--library-path "$tools/lib/x86_64-linux-gnu:$tools/usr/lib/x86_64-linux-gnu:$tools/usr/lib/gcc/x86_64-linux-gnu/13:$tools/lib64:$root/runtime/lib"',
                         '--library-path "$root/runtime/lib"').encode() for name in programs}
    data.update({name + '.real': b'\x7fELF-fixture-native' for name in programs})
    data[base + 'g++-mapper-server'] = b'\x7fELF-fixture-mapper'
    data.update({
        'runtime/lib/ld-linux-x86-64.so.2': b'fixture-loader',
        'runtime/toolchain/lib/x86_64-linux-gnu/libc.so.6': b'fixture-libc',
        'runtime/toolchain/usr/lib/x86_64-linux-gnu/libstdc++.so.6': b'fixture-cpp',
        'runtime/python/run_python.sh': b'#!/bin/sh\nexport CC="$ROOT/runtime/toolchain/usr/bin/gcc"\nexport CXX="$ROOT/runtime/toolchain/usr/bin/g++"\nexport PATH="$ROOT/runtime/toolchain/usr/bin:$ROOT/runtime/python/bin:/usr/bin:/bin"\nexec python "$@"\n',
        builder.MODEL_PREFIX + 'config.json': b'{}',
        builder.MODEL_PREFIX + 'weights.safetensors': b'NEVER COPY',
    })
    path = tmp_path / 'source.zip'
    records = {}
    with zipfile.ZipFile(path, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
        for name, raw in data.items():
            archive.writestr(builder.file_info(name, 0o755), raw)
            records[name] = dict(bytes=len(raw), sha256=hashlib.sha256(raw).hexdigest(), mode=0o755)
        archive.writestr('MANIFEST.json', json.dumps(dict(files=records)))
    return path, data


def test_repair_zip_keeps_all_native_bytes_and_changes_only_wrappers(tmp_path):
    source, original = fixture_source(tmp_path)
    target = tmp_path / 'repaired.zip'
    receipt = builder.build(target, source_zip=source, repair_toolchain=True)
    with zipfile.ZipFile(target) as archive:
        assert archive.testzip() is None
        changes = receipt['toolchain_wrapper_repairs']
        assert len(changes) == 11
        for name, raw in original.items():
            if name.endswith('.safetensors'):
                assert name not in archive.namelist()
            elif name not in changes:
                assert archive.read(name) == raw
        for name in changes:
            raw = archive.read(name)
            assert b'\r' not in raw
            assert stat.S_IMODE(archive.getinfo(name).external_attr >> 16) == 0o755
            if name.endswith('run_python.sh'):
                assert b'GUARDIAN_USE_SYSTEM_COMPILER' in raw
            else:
                assert b'--library-path "$tools/lib/x86_64-linux-gnu:' in raw
                assert b'export LD_LIBRARY_PATH' not in raw
        mapper = 'runtime/toolchain/usr/libexec/gcc/x86_64-linux-gnu/13/g++-mapper-server'
        assert archive.read(mapper + '.real') == original[mapper]
        assert len(archive.namelist()) == len(set(archive.namelist()))


def test_unknown_wrapper_is_rejected(tmp_path):
    source, _ = fixture_source(tmp_path)
    with zipfile.ZipFile(source) as archive:
        patches, _ = archive_patches(archive)
        assert len(patches) == 12
    # A repaired source is not silently repaired twice with a different contract.
    target = tmp_path / 'fixed.zip'
    builder.build(target, source_zip=source, repair_toolchain=True)
    with zipfile.ZipFile(target) as archive:
        with pytest.raises(ValueError, match='UNKNOWN_TOOLCHAIN_WRAPPER'):
            archive_patches(archive)


def test_production_repair_preserves_python_launcher(tmp_path):
    source, _ = fixture_source(tmp_path)
    with zipfile.ZipFile(source) as archive:
        patches, changes = archive_patches(archive, system_compiler_contrast=False)
    assert 'runtime/python/run_python.sh' not in patches
    assert len(changes) == 10
    lto = next(raw for name, (raw, _) in patches.items() if name.endswith('/lto-wrapper'))
    assert b'export COLLECT_GCC="$tools/usr/bin/g++"' in lto


@pytest.mark.parametrize('compiler', ['gcc', 'g++'])
def test_lto_reentry_uses_wrapper_and_preserves_arguments(tmp_path, compiler):
    import os
    import shutil
    import subprocess
    bash = shutil.which('bash') if os.name != 'nt' else 'C:/Program Files/Git/bin/bash.exe'
    if not bash or not Path(bash).exists():
        pytest.skip('POSIX shell required')
    stage = tmp_path / 'stage with spaces'
    path = stage / 'runtime/toolchain/usr/libexec/gcc/x86_64-linux-gnu/13/lto-wrapper'
    path.parent.mkdir(parents=True)
    path.write_text(wrapper_text(stage, path, path.with_name('lto-wrapper.real'),
                    machine='x86_64-linux-gnu', version='13'), newline='\n')
    loader = stage / 'runtime/lib/ld-linux-x86-64.so.2'
    loader.parent.mkdir(parents=True)
    loader.write_text('#!/bin/sh\nprintf "%s\\n" "$COLLECT_GCC" "$LD_LIBRARY_PATH" "$@"\n', newline='\n')
    loader.chmod(0o755)
    # Obtain the same POSIX spelling that the wrapper's pwd will return.
    root = subprocess.check_output([bash, '-c', 'cd -- "$1" && pwd', 'test', str(stage)], text=True).strip()
    for incoming, expected in [(f'{root}/runtime/toolchain/usr/bin/{compiler}.real',
                                f'{root}/runtime/toolchain/usr/bin/{compiler}'),
                               ('/foreign/compiler.real', '/foreign/compiler.real')]:
        env = dict(os.environ, COLLECT_GCC=incoming, LD_LIBRARY_PATH='host-marker',
                   MSYS_NO_PATHCONV='1', MSYS2_ENV_CONV_EXCL='*')
        result = subprocess.run([bash, str(path), 'object with spaces.o', '-o', 'result.so'],
                                env=env, capture_output=True, text=True, check=True)
        lines = result.stdout.splitlines()
        assert lines[0:2] == [expected, 'host-marker']
        assert lines[-3:] == ['object with spaces.o', '-o', 'result.so']
