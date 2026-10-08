"""Integrity and cross-platform assembly boundaries, without pretending GPU use.

The minimal ELF-shaped files below are declared test fixtures only. No test
artifact is exported or accepted as a model, and build() is not invoked here.
"""
import hashlib
import importlib.util
import io
import json
from pathlib import Path
import struct
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
