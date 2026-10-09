"""Integrity and cross-platform assembly boundaries, without pretending GPU use.

The minimal ELF-shaped files below are declared test fixtures only. No test
artifact is exported or accepted as a model, and build() is not invoked here.
"""
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import struct
import subprocess
import tarfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location('runtime_rebuild', ROOT / 'scripts/rebuild_qwen_runtime.py')
runtime = importlib.util.module_from_spec(spec)
spec.loader.exec_module(runtime)


def freeze(stage, reference=None):
    manifest = dict(version='guardian-qwen-runtime-rebuild-1', runtime_only=True,
                    model_reference=reference or runtime.MODEL_REFERENCE,
                    commit='UNIT_TEST_FIXTURE', profile='B2', distributions={},
                    build=dict(python='UNIT_TEST_FIXTURE'), files=runtime.inventory(stage))
    (stage / 'MANIFEST.json').write_text(json.dumps(manifest), encoding='utf-8')


@pytest.fixture
def bundle(tmp_path):
    stage = tmp_path / 'runtime'
    stage.mkdir()
    header = b'\x7fELF\x02\x01' + b'\0' * 12 + struct.pack('<H', 62)
    for name in runtime.EXECUTABLES:
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(header + b'DECLARED_UNIT_TEST_NOT_A_COMPILED_BINARY')
        path.chmod(0o755)
    (stage / 'README.md').write_text('Declared runtime integrity unit fixture.', encoding='utf-8')
    freeze(stage)
    return stage


def test_inventory_rejects_tamper_and_unexpected_files(bundle):
    runtime.verify(bundle)
    (bundle / 'README.md').write_text('Changed', encoding='utf-8')
    with pytest.raises(ValueError, match='CONTENT_OR_FILE_SET_CHANGED'):
        runtime.verify(bundle)
    freeze(bundle)
    (bundle / 'unexpected.txt').write_text('unexpected', encoding='utf-8')
    with pytest.raises(ValueError, match='CONTENT_OR_FILE_SET_CHANGED'):
        runtime.verify(bundle)


@pytest.mark.parametrize('driver', ['libcuda.so.1', 'libnvidia-ptxjitcompiler.so.1'])
def test_bundled_host_driver_or_stub_cannot_be_certified(bundle, driver):
    (bundle / 'runtime/lib' / driver).write_bytes(b'FORBIDDEN_DRIVER_FIXTURE')
    freeze(bundle)
    with pytest.raises(ValueError, match='DRIVER_OR_STUB'):
        runtime.verify(bundle)


def test_weight_fixture_and_wrong_native_architecture_rejected(bundle):
    model_dir = bundle / 'model'
    model_dir.mkdir()
    (model_dir / 'placeholder').write_bytes(b'NO_PLACEHOLDER_WEIGHTS_ALLOWED')
    freeze(bundle)
    with pytest.raises(ValueError, match='MUST_NOT_CONTAIN_MODEL_OR_FIXTURE'):
        runtime.verify(bundle)
    (model_dir / 'placeholder').unlink()
    model_dir.rmdir()
    (bundle / 'runtime/llama/llama-server').write_bytes(b'#!/bin/sh\nexit 0\n')
    freeze(bundle)
    with pytest.raises(ValueError, match='ELF_EXECUTABLE_REQUIRED'):
        runtime.verify(bundle)


def test_runtime_archive_roundtrip_preserves_owned_permissions_and_hashes(bundle, tmp_path):
    artifact = tmp_path / 'runtime.tar.gz'
    runtime.archive(bundle, artifact)
    target = tmp_path / 'extracted'
    runtime.extract(artifact, target, runtime.digest(artifact))
    assert runtime.inventory(target) == runtime.inventory(bundle)
    assert not (target / 'model').exists()
    with tarfile.open(artifact) as tar:
        for name in runtime.EXECUTABLES:
            assert tar.getmember(name).mode == 0o755
    assert artifact.with_suffix('.gz.sha256').read_text(encoding='utf-8').startswith(runtime.digest(artifact))


@pytest.mark.parametrize('unsafe,kind', [('../outside', 'file'), ('C:/outside', 'file'),
                                      ('runtime/link', 'link'), ('runtime/hardlink', 'hardlink')])
def test_untrusted_archive_cannot_escape_or_supply_links(tmp_path, unsafe, kind):
    artifact = tmp_path / 'malicious.tar.gz'
    with tarfile.open(artifact, 'w:gz') as tar:
        entry = tarfile.TarInfo(unsafe)
        if kind in ('link', 'hardlink'):
            entry.type = tarfile.SYMTYPE if kind == 'link' else tarfile.LNKTYPE
            entry.linkname = '../outside'
            tar.addfile(entry)
        else:
            entry.size = 4
            tar.addfile(entry, io.BytesIO(b'evil'))
    target = tmp_path / 'extracted'
    with pytest.raises(ValueError, match='UNSAFE_OR_DUPLICATE'):
        runtime.extract(artifact, target, runtime.digest(artifact))
    assert not target.exists()
    assert not (tmp_path / 'outside').exists()


def test_wrong_model_is_refused_before_creating_final_stage(bundle, tmp_path):
    model = tmp_path / 'wrong.gguf'
    model.write_bytes(b'NOT_THE_EXPECTED_MODEL')
    target = tmp_path / 'final'
    with pytest.raises(ValueError, match='COMPLETE_ORIGINAL_MODEL'):
        runtime.assemble(bundle, model, target)
    assert not target.exists()


def test_full_manifest_assembly_uses_verified_source_and_posix_paths(bundle, tmp_path, monkeypatch):
    # Reduce the expected model only inside this unit test. Production reference
    # constants remain the authenticated28.6GB file; no fixture leaves pytest.
    model = tmp_path / 'declared-test-model'
    model.write_bytes(b'DECLARED_UNIT_TEST_FIXTURE_NOT_MODEL_WEIGHTS')
    reference = dict(runtime.MODEL_REFERENCE, bytes=model.stat().st_size,
                     sha256=hashlib.sha256(model.read_bytes()).hexdigest())
    monkeypatch.setattr(runtime, 'MODEL_REFERENCE', reference)
    freeze(bundle, reference)
    target = tmp_path / 'final'
    runtime.assemble(bundle, model, target)
    manifest = json.loads((target / 'MANIFEST.json').read_text(encoding='utf-8'))
    assert manifest['runtime_only'] is False
    assert manifest['model_sha256'] == reference['sha256']
    assert all('\\' not in name for name in manifest['files'])
    assert all(not name.startswith('model/') for name in manifest['files'])
    assert (target / 'model' / reference['filename']).read_bytes() == model.read_bytes()


def test_only_cuda_driver_gaps_are_exempt_from_dependency_closure():
    text = '  libcuda.so.1 => not found\n  libfoo.so.2 => not found\n'
    assert runtime.ldd_missing(text) == ['libcuda.so.1', 'libfoo.so.2']
    assert runtime.NVIDIA_DRIVER.fullmatch('libcuda.so.1')
    assert not runtime.NVIDIA_DRIVER.fullmatch('libcublas.so.12')


def test_official_notice_is_checked_by_exact_bytes_and_corruption_is_rejected(tmp_path):
    assert runtime.verify_cuda_notice(ROOT).name == 'NVIDIA_CUDA_12.8.1_EULA.pdf'
    with pytest.raises(RuntimeError, match='PINNED_CUDA_NOTICE_MISSING'):
        runtime.verify_cuda_notice(tmp_path)
    notice = tmp_path / runtime.CUDA_EULA['relative_path']
    notice.parent.mkdir(parents=True)
    notice.write_bytes(b'%PDF- DECLARED_CORRUPTED_UNIT_FIXTURE_NOT_AN_OFFICIAL_NOTICE')
    with pytest.raises(RuntimeError, match='PINNED_CUDA_NOTICE_CHANGED'):
        runtime.verify_cuda_notice(tmp_path)


def test_missing_notice_aborts_before_git_network_or_compiler(tmp_path, monkeypatch):
    from types import SimpleNamespace
    seen = []
    monkeypatch.setattr(runtime.sys, 'platform', 'linux')
    monkeypatch.setattr(runtime.sys, 'version_info', (3, 12))
    monkeypatch.setattr(runtime.os, 'uname', lambda: SimpleNamespace(machine='x86_64'), raising=False)
    monkeypatch.setattr(runtime, 'command', lambda *args, **kwargs: seen.append(args))
    monkeypatch.setattr(runtime, 'output', lambda *args: seen.append(args))
    with pytest.raises(RuntimeError, match='PINNED_CUDA_NOTICE_MISSING'):
        runtime.build(tmp_path, tmp_path / 'stage', tmp_path / 'llama.cpp', 2, 'DECLARED_UNIT_IMAGE')
    assert seen == []
    assert not (tmp_path / 'stage').exists() and not (tmp_path / 'llama.cpp').exists()


def test_link_only_driver_requires_toolkit_stub_and_fresh_external_directory(tmp_path, monkeypatch):
    stage = tmp_path / 'stage'
    source = tmp_path / 'llama.cpp'
    toolkit = tmp_path / 'cuda'
    with pytest.raises(RuntimeError, match='LINK_ONLY_DRIVER_STUB_REQUIRED'):
        runtime.prepare_cuda_driver_link(stage, source, toolkit)
    stub = toolkit / 'targets/x86_64-linux/lib/stubs/libcuda.so'
    stub.parent.mkdir(parents=True)
    stub.write_bytes(b'DECLARED_UNIT_LINK_STUB_NOT_A_DRIVER')
    monkeypatch.setattr(runtime, 'output', lambda args: '(SONAME) Library soname: [wrong.so]')
    with pytest.raises(RuntimeError, match='SONAME_MISMATCH'):
        runtime.prepare_cuda_driver_link(stage, source, toolkit)
    # Refuse placing the link-only area under runtime, even with a valid stub.
    monkeypatch.setattr(runtime, 'output', lambda args: '(SONAME) Library soname: [libcuda.so.1]')
    with pytest.raises(ValueError, match='OUTSIDE_RUNTIME'):
        runtime.prepare_cuda_driver_link(tmp_path, source, toolkit)


@pytest.mark.skipif(os.name != 'posix', reason='Actual linker and symlink behavior require POSIX')
def test_link_only_soname_search_resolves_transitive_driver_without_runtime_rpath(tmp_path):
    import shutil
    if not shutil.which('gcc') or not shutil.which('readelf'):
        pytest.skip('gcc/readelf unavailable on this POSIX host')
    toolkit = tmp_path / 'cuda'
    stub = toolkit / 'targets/x86_64-linux/lib/stubs/libcuda.so'
    stub.parent.mkdir(parents=True)
    driver = tmp_path / 'driver.c'
    driver.write_text('int private_test_driver_symbol(void) { return 0; }', encoding='utf-8')
    subprocess.run(['gcc', '-shared', '-fPIC', str(driver), '-Wl,-soname,libcuda.so.1', '-o', str(stub)], check=True)
    backend_source = tmp_path / 'backend.c'
    backend_source.write_text('extern int private_test_driver_symbol(void); int backend(void) { '
                              'return private_test_driver_symbol(); }', encoding='utf-8')
    backend = tmp_path / 'libbackend.so'
    subprocess.run(['gcc', '-shared', '-fPIC', str(backend_source), str(stub), '-o', str(backend)], check=True)
    program = tmp_path / 'main.c'
    program.write_text('extern int backend(void); int main(void) { return backend(); }', encoding='utf-8')
    destination = tmp_path / 'linked'
    without = subprocess.run(['gcc', str(program), str(backend), '-o', str(destination)], capture_output=True)
    assert without.returncode != 0 and b'libcuda.so.1' in without.stderr
    link_dir, info = runtime.prepare_cuda_driver_link(tmp_path / 'stage', tmp_path / 'llama.cpp', toolkit)
    subprocess.run(['gcc', str(program), str(backend), info['linker_flag'], '-o', str(destination)], check=True)
    dynamic = subprocess.run(['readelf', '-d', str(destination)], check=True, text=True, capture_output=True).stdout
    assert str(link_dir) not in dynamic  # rpath-link is not runtime RPATH/RUNPATH.
    assert (link_dir / 'libcuda.so.1').is_symlink()
    assert info['VMM'] == 'UNCHANGED'
    assert not (tmp_path / 'stage').exists()
    # This toy linkage test does not load the fake stub or execute GPU inference.


@pytest.mark.parametrize('message,acceptable', [
    ('llama-server: error while loading shared libraries: libcuda.so.1: cannot open shared object file: '
     'No such file or directory\n', True),
    ('llama-server: error while loading shared libraries: libcublas.so.12: cannot open shared object file: '
     'No such file or directory\n', False),
    ('llama-server: undefined symbol: cuMemCreate\n', False),
    ('Segmentation fault\n', False),
])
def test_native_version_only_marks_exact_missing_host_driver_as_not_executed(tmp_path, monkeypatch, message, acceptable):
    seen = []
    def completed(args, **kwargs):
        seen.append((args, kwargs))
        return subprocess.CompletedProcess(args, 127, '', message)
    monkeypatch.setattr(runtime.subprocess, 'run', completed)
    if acceptable:
        version, status = runtime.check_native_version(tmp_path / 'stage', tmp_path, {})
        assert version is None and status['status'] == 'NOT_EXECUTED_MISSING_HOST_DRIVER'
        assert status['link_only_stub_used_for_execution'] is False
    else:
        with pytest.raises(RuntimeError, match='CPU_RUNTIME_SMOKE_FAILED'):
            runtime.check_native_version(tmp_path / 'stage', tmp_path, {})
    assert 'cuda-driver-link' not in seen[0][1]['env']['LD_LIBRARY_PATH']
    assert (tmp_path / 'rebuilt_llama_version.log').read_text(encoding='utf-8') == message


def test_native_version_still_requires_pinned_revision_when_executed(tmp_path, monkeypatch):
    monkeypatch.setattr(runtime.subprocess, 'run', lambda args, **kwargs:
                        subprocess.CompletedProcess(args, 0, 'version: unpinned\n', ''))
    with pytest.raises(RuntimeError, match='REVISION_MISMATCH'):
        runtime.check_native_version(tmp_path / 'stage', tmp_path, {})


@pytest.mark.parametrize('path,allowed', [('$ORIGIN', True), ('${ORIGIN}', True),
                                        ('/usr/local/cuda/lib64/stubs', False),
                                        ('/build/cuda-driver-link', False),
                                        ('$ORIGIN:/build/cuda-driver-link', False)])
def test_built_rpaths_cannot_embed_toolkit_stubs_or_link_only_directory(tmp_path, monkeypatch, path, allowed):
    (tmp_path / 'llama-server').write_bytes(b'DECLARED_PRIVATE_UNIT_NATIVE_FIXTURE')
    monkeypatch.setattr(runtime, 'output', lambda args: '(RUNPATH) Library runpath: [' + path + ']')
    if allowed:
        assert runtime.check_built_runtime_rpaths(tmp_path) == {'llama-server': [path]}
    else:
        with pytest.raises(RuntimeError, match='UNAPPROVED_RPATH'):
            runtime.check_built_runtime_rpaths(tmp_path)
