"""Offline export/integrity boundaries, never substitutes fixtures for real weights."""
import base64
import hashlib
import io
import json
import os
from pathlib import Path
from types import SimpleNamespace
import zipfile

import pytest

from scripts import build_vllm_submission as builder


def freeze(stage):
    (stage / 'MODEL_MANIFEST.json').write_text('{}', encoding='utf-8')
    manifest = dict(version=builder.VERSION, max_archive_bytes=builder.MAX_ARCHIVE_BYTES,
                    model_manifest_sha256=builder.digest(stage / 'MODEL_MANIFEST.json'),
                    files=builder.inventory(stage))
    builder.write_json(stage / 'MANIFEST.json', manifest)
    return manifest


@pytest.fixture
def stage(tmp_path):
    target = tmp_path / 'stage'
    target.mkdir()
    for name, raw in {'scripts/predict.py': b'# No live inference in tests.\n',
                      'runtime/python/run_python.sh': b'#!/bin/sh\nexit 0\n',
                      'model/test.safetensors': b'EXPLICIT_TEST_FIXTURE_NOT_MODEL_WEIGHTS'}.items():
        path = target / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    freeze(target)
    return target


def test_zip_is_root_level_zip64_and_weights_stored_runtime_deflated(stage):
    output = io.BytesIO()
    receipt = builder.archive(stage, '-', stream=output)
    assert receipt['bytes'] == len(output.getvalue())
    assert receipt['sha256'] == hashlib.sha256(output.getvalue()).hexdigest()
    assert receipt['runtime_only'] is False
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert archive.testzip() is None
        assert 'scripts/predict.py' in archive.namelist()
        assert all(not name.startswith('stage/') for name in archive.namelist())
        assert archive.getinfo('model/test.safetensors').compress_type == zipfile.ZIP_STORED
        assert archive.getinfo('scripts/predict.py').compress_type == zipfile.ZIP_DEFLATED
        assert archive.read('MANIFEST.json') == (stage / 'MANIFEST.json').read_bytes()


def test_runtime_only_keeps_complete_final_manifest_for_local_weight_join(stage):
    output = io.BytesIO()
    receipt = builder.archive(stage, '-', stream=output, runtime_only=True)
    assert receipt['runtime_only'] is True
    with zipfile.ZipFile(io.BytesIO(output.getvalue())) as archive:
        assert not any(name.startswith('model/') for name in archive.namelist())
        manifest = json.loads(archive.read('MANIFEST.json'))
        assert 'model/test.safetensors' in manifest['files']


def test_archive_cap_counts_headers_and_central_directory(stage):
    output = io.BytesIO()
    with pytest.raises(ValueError, match='ARCHIVE_EXCEEDS_PLATFORM_CAP'):
        builder.archive(stage, '-', stream=output, cap=128)
    assert len(output.getvalue()) <= 128


def test_archive_cannot_write_back_into_frozen_stage_or_overwrite_receipt(stage, tmp_path):
    with pytest.raises(ValueError, match='DESTINATION_MUST_BE_OUTSIDE'):
        builder.archive(stage, stage / 'self.zip')
    assert not (stage / 'self.zip').exists()
    with pytest.raises(ValueError, match='REPORT_MUST_BE_OUTSIDE'):
        builder.archive(stage, '-', stream=io.BytesIO(), report=stage / 'report.json')
    previous = tmp_path / 'receipt.json'
    previous.write_text('historical receipt', encoding='utf-8')
    with pytest.raises(FileExistsError):
        builder.archive(stage, '-', stream=io.BytesIO(), report=previous)
    assert previous.read_text() == 'historical receipt'


def test_hardlinked_source_mutation_between_verify_and_stream_is_detected(stage, monkeypatch):
    original = builder.verify_stage
    def mutate_after_verify(root):
        manifest = original(root)
        model = root / 'model/test.safetensors'
        model.write_bytes(b'X' * model.stat().st_size)
        return manifest
    monkeypatch.setattr(builder, 'verify_stage', mutate_after_verify)
    with pytest.raises(ValueError, match='STAGE_CHANGED_DURING_ARCHIVE'):
        builder.archive(stage, '-', stream=io.BytesIO())


@pytest.mark.parametrize('change', ['same_size_model', 'extra_file', 'missing_runtime'])
def test_verified_stage_rejects_model_tamper_and_inventory_drift(stage, change):
    if change == 'same_size_model':
        path = stage / 'model/test.safetensors'
        path.write_bytes(b'X' * path.stat().st_size)
    elif change == 'extra_file':
        (stage / 'accidental-secret.env').write_text('DO_NOT_EXPORT', encoding='utf-8')
    else:
        (stage / 'runtime/python/run_python.sh').unlink()
    with pytest.raises(ValueError, match='STAGE_FILE_SET_OR_BYTES_CHANGED'):
        builder.archive(stage, '-', stream=io.BytesIO())


@pytest.mark.parametrize('driver', ['libcuda.so.1', 'libnvidia-ml.so.1'])
def test_host_driver_cannot_pass_even_a_refrozen_local_manifest(stage, driver):
    (stage / driver).write_bytes(b'EXPLICIT_FORBIDDEN_DRIVER_FIXTURE')
    freeze(stage)
    with pytest.raises(ValueError, match='HOST_DRIVER_OR_STUB_FORBIDDEN'):
        builder.verify_stage(stage)


def test_hardlink_does_not_duplicate_or_modify_source_bytes(tmp_path):
    source = tmp_path / 'source'
    source.write_bytes(b'unchanged source bytes')
    target = tmp_path / 'stage/copy'
    builder.materialize(source, target, allowed_root=tmp_path)
    assert os.path.samefile(source, target)
    assert source.read_bytes() == b'unchanged source bytes'
    assert not target.is_symlink()


def test_hardlink_collisions_do_not_overwrite_history(tmp_path):
    source, target = tmp_path / 'source', tmp_path / 'target'
    source.write_bytes(b'one')
    target.write_bytes(b'two')
    with pytest.raises(ValueError, match='STAGE_PATH_COLLISION'):
        builder.materialize(source, target)
    assert target.read_bytes() == b'two'


@pytest.mark.parametrize('name', ['../escape', '/escape', 'C:/escape', 'folder\\escape', 'a//b'])
def test_manifest_paths_are_portable_and_bounded(name):
    with pytest.raises(ValueError, match='UNSAFE_ASSET_PATH'):
        builder.relative_name(name)


def model_fixture(root):
    root.mkdir()
    values = {'config.json': json.dumps(dict(quantization_config=dict(quant_method='fp8'))).encode(),
              'tokenizer.json': b'{}', 'tokenizer_config.json': b'{}',
              'model.safetensors.index.json': json.dumps(dict(weight_map=dict(weight='one.safetensors'))).encode(),
              'one.safetensors': b'DECLARED_TEST_FIXTURE_ONLY'}
    for name, raw in values.items():
        (root / name).write_bytes(raw)
    return dict(repository=builder.REPOSITORY, revision=builder.REVISION,
                files=[dict(path=name, size=len(raw), sha256=hashlib.sha256(raw).hexdigest())
                       for name, raw in values.items()])


def test_model_full_bytes_are_rechecked_and_not_only_stat_size(tmp_path):
    root = tmp_path / 'model'
    manifest = model_fixture(root)
    assert len(builder.model_assets(root, manifest)) == 5
    path = root / 'one.safetensors'
    path.write_bytes(b'X' * path.stat().st_size)
    with pytest.raises(ValueError, match='MODEL_ASSET_BYTES_CHANGED'):
        builder.model_assets(root, manifest)


def test_model_index_shards_must_equal_certified_asset_set(tmp_path):
    root = tmp_path / 'model'
    manifest = model_fixture(root)
    extra = root / 'other.safetensors'
    extra.write_bytes(b'NOT_REAL_WEIGHTS')
    manifest['files'].append(dict(path=extra.name, size=extra.stat().st_size, sha256=builder.digest(extra)))
    with pytest.raises(ValueError, match='MODEL_INDEX_ASSET_SET_MISMATCH'):
        builder.model_assets(root, manifest)


class Item(str):
    def __new__(cls, text, raw):
        value = super().__new__(cls, text)
        value.size = len(raw)
        value.hash = SimpleNamespace(mode='sha256', value=base64.urlsafe_b64encode(
            hashlib.sha256(raw).digest()).rstrip(b'=').decode())
        return value


class Distribution:
    def __init__(self, base, contents, name='fixture-wheel'):
        self.base, self.metadata, self.version = base, {'Name': name}, '1.0'
        self.files = []
        for relative, raw in contents.items():
            path = base / relative
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_bytes(raw)
            self.files.append(Item(relative, raw))
    def locate_file(self, item):
        return self.base / str(item)


def test_installed_record_preserves_data_native_and_license_files_and_relocates_entrypoint(tmp_path):
    venv = tmp_path / 'venv'
    base = venv / 'lib/python3.12/site-packages'
    dist = Distribution(base, {'package/__init__.py': b'', 'package/kernel.so': b'fixture',
        'package/data/vocabulary.txt': b'data', 'fixture.dist-info/licenses/LICENSE': b'license',
        '../../../bin/fixture-cli': b'#!/some/server/venv/bin/python\nprint("ok")\n'})
    stage = tmp_path / 'stage'
    stage.mkdir()
    versions, owner = builder.collect_wheels(stage, [dist], prefix=venv)
    assert versions == {'fixture-wheel': '1.0'}
    assert (stage / 'runtime/site-packages/fixture.dist-info/licenses/LICENSE').read_bytes() == b'license'
    assert (stage / 'runtime/site-packages/package/data/vocabulary.txt').read_bytes() == b'data'
    assert (stage / 'runtime/bin/fixture-cli').read_text().startswith('#!/bin/sh\n')
    assert '/some/server' not in (stage / 'runtime/bin/fixture-cli').read_text()
    assert (stage / 'runtime/wheel-scripts/fixture-cli').read_bytes().startswith(b'#!/some/server/')
    assert owner['runtime/wheel-scripts/fixture-cli'] == ['fixture-wheel']


def test_wheel_record_detects_same_size_corruption_before_export(tmp_path):
    venv = tmp_path / 'venv'
    base = venv / 'lib/python3.12/site-packages'
    dist = Distribution(base, {'package.py': b'first'})
    (base / 'package.py').write_bytes(b'other')
    with pytest.raises(ValueError, match='WHEEL_RECORD_HASH_MISMATCH'):
        builder.collect_wheels(tmp_path / 'stage', [dist], prefix=venv)


@pytest.mark.parametrize('relative,raw,error', [
    ('../../../../outside/secret', b'secret', 'OUTSIDE_VENV'),
    ('bad.pth', b'/root/private\n', 'EXTERNAL_PTH_PATH'),
    ('vendor/stubs/libcuda.so', b'driver', 'HOST_DRIVER_OR_STUB'),
])
def test_package_escape_hooks_and_driver_stubs_fail_explicitly(tmp_path, relative, raw, error):
    venv = tmp_path / 'venv'
    base = venv / 'lib/python3.12/site-packages'
    dist = Distribution(base, {relative: raw})
    with pytest.raises(ValueError, match=error):
        builder.collect_wheels(tmp_path / 'stage', [dist], prefix=venv)


def test_authenticated_vendor_hook_is_preserved_without_package_name_routing(tmp_path):
    venv = tmp_path / 'venv'
    base = venv / 'lib/python3.12/site-packages'
    raw = b'import fixture_redirector\n'
    dist = Distribution(base, {'vendor.pth': raw, 'fixture_redirector.py': b'# vendor module\n'})
    versions, owner = builder.collect_wheels(tmp_path / 'stage', [dist], prefix=venv)
    assert (tmp_path / 'stage/runtime/site-packages/vendor.pth').read_bytes() == raw
    assert owner['runtime/site-packages/vendor.pth'] == ['fixture-wheel']
    dist.files[0].hash = None
    with pytest.raises(ValueError, match='UNVERIFIED_PTH_HOOK'):
        builder.collect_wheels(tmp_path / 'unverified', [dist], prefix=venv)


def test_python_launcher_uses_private_loader_and_reentrant_sys_executable(tmp_path):
    stage = tmp_path / 'stage'
    (stage / 'runtime/python/bin').mkdir(parents=True)
    (stage / 'runtime/lib').mkdir()
    (stage / 'runtime/lib/libc.so.6').write_bytes(b'fixture')
    builder.write_launcher(stage)
    launcher = (stage / 'runtime/python/run_python.sh').read_text()
    assert '--argv0 "$ROOT/runtime/python/bin/python3.12"' in launcher
    assert 'python3.12.real' in launcher
    assert 'GUARDIAN_BUNDLED_PYTHON=1' in launcher
    assert 'export LD_LIBRARY_PATH=' not in launcher
    assert 'runtime/toolchain/usr/bin/gcc' in launcher
    assert 'unset GUARDIAN_VLLM_OWNER_TOKEN' not in launcher


def native_fixture(tmp_path):
    stage, host = tmp_path / 'stage', tmp_path / 'host'
    (stage / 'runtime/python/bin').mkdir(parents=True)
    host.mkdir()
    binary = stage / 'runtime/python/bin/python3.12.real'
    binary.write_bytes(b'\x7fELF' + b'EXPLICIT_NATIVE_FIXTURE')
    loader = host / 'ld-linux-x86-64.so.2'
    loader.write_bytes(b'\x7fELF' + b'EXPLICIT_LOADER_FIXTURE')
    return stage, binary, loader


def test_native_closure_bundles_loader_and_ignores_host_driver_only(tmp_path):
    stage, binary, loader = native_fixture(tmp_path)
    def run(command, **kwargs):
        if command[-1] == str(binary):
            return SimpleNamespace(returncode=0, stdout=f'{loader.as_posix()} (0x1)\nlibcuda.so.1 => not found\n', stderr='')
        return SimpleNamespace(returncode=0, stdout='statically linked\n', stderr='')
    result = builder.collect_native(stage, run=run)
    assert (stage / 'runtime/lib/ld-linux-x86-64.so.2').read_bytes() == loader.read_bytes()
    assert 'runtime/python/bin/python3.12.real' in result
    assert not any(path.name == 'libcuda.so.1' for path in stage.rglob('*'))


def test_missing_non_driver_library_never_becomes_a_portable_runtime(tmp_path):
    stage, _, _ = native_fixture(tmp_path)
    with pytest.raises(RuntimeError, match='UNRESOLVED_NATIVE_DEPENDENCY:libtorch.so'):
        builder.collect_native(stage, run=lambda *a, **k:
            SimpleNamespace(returncode=0, stdout='libtorch.so => not found\n', stderr=''))


def test_source_whitelist_does_not_copy_gold_caches_or_other_experiments(tmp_path):
    repo, stage = tmp_path / 'repo', tmp_path / 'stage'
    sources = ['src/guardian_truth/__init__.py', *['experiments/' + n for n in builder.EXPERIMENTS],
        'submission/predict_vllm.py', 'scripts/qwen_vllm_adapter.py', 'submission/pyproject.toml',
        'submission/build_backend.py', 'submission/licenses/LICENSE',
        'docs/qwen_vllm_submission_20261010/RUNBOOK.md']
    for name in sources:
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text('# Runtime fixture\n', encoding='utf-8')
    for name in ('valid.parquet', 'outputs/cache.jsonl', 'experiments/other.py', 'secrets/api.env'):
        path = repo / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'NEVER_EXPORTED')
    builder.collect_sources(repo, stage)
    assert (stage / 'scripts/predict.py').is_file()
    assert not any(path.read_bytes() == b'NEVER_EXPORTED' for path in stage.rglob('*') if path.is_file())


def test_builder_never_installs_or_runs_gpu_on_unsupported_host(tmp_path):
    with pytest.raises(RuntimeError, match='VALIDATED_LINUX_CPYTHON312_VENV_REQUIRED'):
        builder.prepare(tmp_path, tmp_path / 'stage', tmp_path / 'model', tmp_path / 'manifest')
    assert not (tmp_path / 'stage').exists()


def test_runtime_only_prepare_cli_does_not_require_a_model_directory(tmp_path, monkeypatch):
    seen = []
    def prepare(repo, stage, model_dir, manifest, *, runtime_only=False):
        seen.append((model_dir, runtime_only))
        return dict(source_sha='reviewed', files={}, model_mode='RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED')
    monkeypatch.setattr(builder, 'prepare', prepare)
    builder.main(['prepare', '--repo', str(tmp_path), '--stage', str(tmp_path / 'stage'),
                  '--asset-manifest', str(tmp_path / 'expected.json'), '--runtime-only'])
    assert seen == [(None, True)]
    with pytest.raises(ValueError, match='FULL_BUILD_REQUIRES_MODEL_DIR'):
        # Original production function is reached separately in the companion
        # declaration checks; full-mode requirements remain independent.
        monkeypatch.undo()
        builder.prepare(tmp_path, tmp_path / 'full', None, tmp_path / 'expected.json')


@pytest.mark.parametrize('change', ['none', 'wrong_revision', 'invalid_sha', 'unsafe_path', 'missing_required'])
def test_runtime_only_model_metadata_is_validated_without_opening_model_bytes(tmp_path, monkeypatch, change):
    manifest = model_fixture(tmp_path / 'original_metadata_fixture')
    if change == 'wrong_revision':
        manifest['revision'] = 'other'
    elif change == 'invalid_sha':
        manifest['files'][0]['sha256'] = 'not-a-digest'
    elif change == 'unsafe_path':
        manifest['files'][0]['path'] = '../escape'
    elif change == 'missing_required':
        manifest['files'] = [r for r in manifest['files'] if r['path'] != 'tokenizer.json']
    monkeypatch.setattr(builder, 'digest', lambda *a: pytest.fail('metadata-only must never hash model bytes'))
    if change == 'none':
        expected = builder.model_declarations(manifest)
        assert len(expected) == 5
        assert all(set(row) == {'path', 'size', 'sha256'} for row in expected)
    else:
        with pytest.raises(ValueError):
            builder.model_declarations(manifest)


def test_runtime_only_stage_cannot_be_advertised_as_complete_model_archive(stage, tmp_path):
    expected = model_fixture(tmp_path / 'expected_metadata')
    (stage / 'model/test.safetensors').unlink()
    (stage / 'model').rmdir()
    builder.write_json(stage / 'MODEL_MANIFEST.json', expected)
    manifest = dict(version=builder.VERSION, max_archive_bytes=builder.MAX_ARCHIVE_BYTES,
        model_manifest_sha256=builder.digest(stage / 'MODEL_MANIFEST.json'), files=builder.inventory(stage),
        model_mode='RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED', models_expected=builder.model_declarations(expected))
    builder.write_json(stage / 'MANIFEST.json', manifest)
    builder.verify_stage(stage)
    with pytest.raises(ValueError, match='RUNTIME_ONLY_STAGE_REQUIRES_RUNTIME_EXPORT'):
        builder.archive(stage, '-', stream=io.BytesIO())
    exported = io.BytesIO()
    receipt = builder.archive(stage, '-', stream=exported, runtime_only=True)
    assert receipt['status'] == 'PARTIAL_RUNTIME_TRANSPORT'
    with zipfile.ZipFile(io.BytesIO(exported.getvalue())) as archive:
        assert not any(name.startswith('model/') for name in archive.namelist())
        assert json.loads(archive.read('MANIFEST.json'))['models_expected'] == manifest['models_expected']
