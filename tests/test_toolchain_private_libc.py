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
