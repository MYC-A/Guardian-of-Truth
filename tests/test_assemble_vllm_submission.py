"""Public archive join boundary tests with explicit tiny non-model fixtures."""
import hashlib
import json
import os
from pathlib import Path
import stat
import subprocess
import sys
import zipfile

import pytest

from scripts import assemble_vllm_submission as assembler
from scripts import build_vllm_submission as builder


def encode(value):
    return (json.dumps(value, sort_keys=True) + '\n').encode()


def sha(raw):
    return hashlib.sha256(raw).hexdigest()


def zip_write(path, payloads, *, modes=None):
    with zipfile.ZipFile(path, 'w') as bundle:
        for name, raw in payloads.items():
            info = zipfile.ZipInfo(name)
            info.create_system = 3
            info.external_attr = (stat.S_IFREG | (modes or {}).get(name, 0o644)) << 16
            bundle.writestr(info, raw)


@pytest.fixture
def prepared(tmp_path):
    model = tmp_path / 'local-model'
    model.mkdir()
    assets = {
        'config.json': encode({'quantization_config': {'quant_method': 'fp8'}}),
        'tokenizer.json': encode({'fixture': 'not a real tokenizer'}),
        'tokenizer_config.json': encode({'fixture': True}),
        'model.safetensors.index.json': encode({'weight_map': {'fake.weight': 'fixture.safetensors'}}),
        'fixture.safetensors': b'EXPLICIT_SMALL_TEST_FIXTURE_NOT_REAL_MODEL',
    }
    for name, raw in assets.items():
        (model / name).write_bytes(raw)
    rows = [dict(path=name, size=len(raw), sha256=sha(raw)) for name, raw in sorted(assets.items())]
    model_manifest = encode(dict(repository=builder.REPOSITORY, revision=builder.REVISION, files=rows))
    runtime = {
        'MODEL_MANIFEST.json': model_manifest,
        'Dockerfile': b'FROM ubuntu:24.04\n',
        'pyproject.toml': b'[build-system]\n',
        'build_backend.py': b'# fixture\n',
        'scripts/predict.py': b'# fixture entrypoint\n',
        'runtime/python/run_python.sh': b'#!/bin/sh\nexit 0\n',
        'runtime/native.bin': b'EXPLICIT_RUNTIME_FIXTURE',
    }
    modes = {'runtime/python/run_python.sh': 0o755}
    manifest = dict(version=builder.VERSION, source_sha='a' * 40,
                    model_repository=builder.REPOSITORY, model_revision=builder.REVISION,
                    engine_version=builder.ENGINE_VERSION, max_archive_bytes=builder.MAX_ARCHIVE_BYTES,
                    model_mode='RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED', models_expected=rows,
                    model_manifest_sha256=sha(model_manifest), gpu_validation='NOT_EXECUTED_BY_BUILDER',
                    files={name: dict(bytes=len(raw), sha256=sha(raw), mode=modes.get(name, 0o644))
                           for name, raw in runtime.items()})
    runtime['MANIFEST.json'] = encode(manifest)
    source = tmp_path / 'runtime.zip'
    zip_write(source, runtime, modes=modes)
    return dict(root=tmp_path, model=model, source=source, runtime=runtime, modes=modes,
                manifest=manifest, assets=assets)


def run(prepared, **kwargs):
    return assembler.assemble(prepared['source'], prepared['model'], prepared['root'] / 'candidate.zip',
                              prepared['root'] / 'receipt.json', **kwargs)


def rezip(prepared):
    prepared['runtime']['MANIFEST.json'] = encode(prepared['manifest'])
    zip_write(prepared['source'], prepared['runtime'], modes=prepared['modes'])


def test_joins_partial_runtime_without_extracting_and_preserves_gpu_boundary(prepared):
    result = run(prepared)
    archive = prepared['root'] / 'candidate.zip'
    assert result['sha256'] == sha(archive.read_bytes())
    assert result['bytes'] == archive.stat().st_size
    assert result['status'] == 'COMPLETE_CANDIDATE'
    assert result['gpu_validation'] == 'NOT_EXECUTED_BY_BUILDER'
    assert json.loads((prepared['root'] / 'receipt.json').read_text()) == result
    with zipfile.ZipFile(archive) as bundle:
        assert bundle.testzip() is None
        assert 'scripts/predict.py' in bundle.namelist()
        assert not any(name.startswith('candidate/') for name in bundle.namelist())
        assert (bundle.getinfo('runtime/python/run_python.sh').external_attr >> 16) & 0o777 == 0o755
        for name, raw in prepared['assets'].items():
            address = 'model/' + builder.REVISION + '/' + name
            assert bundle.read(address) == raw
            if name.endswith('.safetensors'):
                assert bundle.getinfo(address).compress_type == zipfile.ZIP_STORED
        manifest = json.loads(bundle.read('MANIFEST.json'))
        assert set(bundle.namelist()) == set(manifest['files']) | {'MANIFEST.json'}
        assert manifest['assembly_mode'] == 'COMPLETE_CANDIDATE'
        assert manifest['source_manifest_sha256'] == sha(prepared['runtime']['MANIFEST.json'])
    assert not (prepared['root'] / 'candidate.zip.partial').exists()


def test_accepts_runtime_export_from_full_stage_inventory(prepared):
    prepared['manifest']['model_mode'] = 'FULL_MODELS_SHA256_VERIFIED'
    for name, raw in prepared['assets'].items():
        prepared['manifest']['files']['model/' + builder.REVISION + '/' + name] = dict(bytes=len(raw), sha256=sha(raw), mode=0o644)
    rezip(prepared)
    assert run(prepared)['status'] == 'COMPLETE_CANDIDATE'


def test_rejects_same_size_runtime_tampering_before_output_creation(prepared):
    prepared['runtime']['runtime/native.bin'] = b'x' * len(prepared['runtime']['runtime/native.bin'])
    rezip(prepared)
    with pytest.raises(ValueError, match='RUNTIME_SHA256_MISMATCH'):
        run(prepared)
    assert not (prepared['root'] / 'candidate.zip').exists()
    assert not (prepared['root'] / 'candidate.zip.partial').exists()


@pytest.mark.parametrize('name', ['../secret', '/tmp/secret', 'C:/secret', 'a\\b', './predict.py'])
def test_zip_path_escape_rejected(prepared, name):
    prepared['runtime'][name] = b'BAD_ENTRY'
    rezip(prepared)
    with pytest.raises(ValueError, match='UNSAFE_ASSET_PATH|RUNTIME_FILE_SET_MISMATCH'):
        run(prepared)


def test_duplicate_zip_member_rejected(prepared):
    with zipfile.ZipFile(prepared['source'], 'a') as bundle:
        with pytest.warns(UserWarning):
            bundle.writestr('Dockerfile', b'changed')
    with pytest.raises(ValueError, match='DUPLICATE_ZIP_ENTRY'):
        run(prepared)


def test_symlink_in_runtime_rejected(prepared):
    with zipfile.ZipFile(prepared['source'], 'a') as bundle:
        info = zipfile.ZipInfo('link')
        info.external_attr = (stat.S_IFLNK | 0o777) << 16
        bundle.writestr(info, b'/etc/passwd')
    with pytest.raises(ValueError, match='UNSAFE_OR_DUPLICATE'):
        run(prepared)


def test_runtime_executable_permission_tamper_rejected(prepared):
    prepared['modes']['runtime/python/run_python.sh'] = 0o644
    rezip(prepared)
    with pytest.raises(ValueError, match='RUNTIME_SIZE_OR_MODE'):
        run(prepared)


def test_wrong_engine_identity_rejected(prepared):
    prepared['manifest']['engine_version'] = 'different'
    rezip(prepared)
    with pytest.raises(ValueError, match='IDENTITY_MISMATCH'):
        run(prepared)


def test_local_model_tampering_rejected_before_output_creation(prepared):
    path = prepared['model'] / 'fixture.safetensors'
    path.write_bytes(b'x' * path.stat().st_size)
    with pytest.raises(ValueError, match='LOCAL_MODEL_BYTES_MISMATCH'):
        run(prepared)
    assert not (prepared['root'] / 'candidate.zip.partial').exists()


def test_model_metadata_swap_not_accepted_by_updating_runtime_file_hash(prepared):
    model = json.loads(prepared['runtime']['MODEL_MANIFEST.json'])
    model['revision'] = 'b' * 40
    raw = encode(model)
    prepared['runtime']['MODEL_MANIFEST.json'] = raw
    prepared['manifest']['files']['MODEL_MANIFEST.json'].update(bytes=len(raw), sha256=sha(raw))
    rezip(prepared)
    with pytest.raises(ValueError, match='MODEL_METADATA_SHA256_MISMATCH'):
        run(prepared)


def test_model_index_associations_checked_even_when_bytes_match_manifest(prepared):
    name = 'model.safetensors.index.json'
    raw = encode({'weight_map': {'fake.weight': 'missing.safetensors'}})
    (prepared['model'] / name).write_bytes(raw)
    metadata = json.loads(prepared['runtime']['MODEL_MANIFEST.json'])
    for row in metadata['files']:
        if row['path'] == name:
            row.update(size=len(raw), sha256=sha(raw))
    raw_metadata = encode(metadata)
    prepared['runtime']['MODEL_MANIFEST.json'] = raw_metadata
    prepared['manifest'].update(models_expected=metadata['files'], model_manifest_sha256=sha(raw_metadata))
    prepared['manifest']['files']['MODEL_MANIFEST.json'].update(bytes=len(raw_metadata), sha256=sha(raw_metadata))
    rezip(prepared)
    with pytest.raises(ValueError, match='MODEL_INDEX_SET_MISMATCH'):
        run(prepared)


def test_cap_includes_zip_overhead_and_failure_leaves_no_final(prepared):
    with pytest.raises(ValueError, match='ARCHIVE_EXCEEDS_PLATFORM_CAP'):
        run(prepared, cap=64)
    assert not (prepared['root'] / 'candidate.zip').exists()
    assert not (prepared['root'] / 'candidate.zip.partial').exists()


def test_existing_archive_and_receipt_never_overwritten(prepared):
    path = prepared['root'] / 'candidate.zip'
    path.write_bytes(b'OTHER_OPERATORS_ARCHIVE')
    with pytest.raises(FileExistsError):
        run(prepared)
    assert path.read_bytes() == b'OTHER_OPERATORS_ARCHIVE'


def test_source_runtime_must_have_public_entrypoint(prepared):
    del prepared['manifest']['files']['scripts/predict.py']
    del prepared['runtime']['scripts/predict.py']
    rezip(prepared)
    with pytest.raises(ValueError, match='PUBLIC_ROOT_LAYOUT'):
        run(prepared)


def test_operator_cli_can_run_without_pythonpath(tmp_path):
    env = dict(os.environ)
    env.pop('PYTHONPATH', None)
    reply = subprocess.run([sys.executable, str(Path(assembler.__file__)), '--help'],
                           cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20)
    assert reply.returncode == 0, reply.stderr
    assert '--runtime-archive' in reply.stdout


def test_inputs_changed_after_validation_are_not_published(prepared, monkeypatch):
    original = assembler.model_paths
    def changed(*args):
        paths = original(*args)
        paths['fixture.safetensors'].write_bytes(b'CHANGED_DURING_ASSEMBLY')
        return paths
    monkeypatch.setattr(assembler, 'model_paths', changed)
    with pytest.raises(ValueError, match='INPUT_CHANGED_DURING_ASSEMBLY'):
        run(prepared)
    assert not (prepared['root'] / 'candidate.zip').exists()
    assert not (prepared['root'] / 'candidate.zip.partial').exists()
