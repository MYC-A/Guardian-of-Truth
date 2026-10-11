import hashlib
import json
import zipfile
from pathlib import Path

import pytest

from scripts import build_cascade_submission as bc
from scripts import cascade_submission as cs
from scripts.assemble_vllm_submission import json_bytes


def sha(data):
    return hashlib.sha256(data).hexdigest()


def make_source(tmp_path, *, repaired=True):
    files = {'runtime/python/run_python.sh': (b'#!/bin/sh\n', 0o755), 'src/x.py': (b'x = 1\n', 0o644),
             'scripts/predict.py': (b'old\n', 0o644), 'scripts/qwen_vllm_adapter.py': (b'old\n', 0o644),
             'README.md': (b'old\n', 0o644), 'MODEL_MANIFEST.json': (b'{}\n', 0o644),
             f'model/{bc.OLD_REVISION}/model.safetensors': (b'W' * 1000, 0o644)}
    manifest = dict(model_mode='FULL_MODELS_SHA256_VERIFIED',
                    files={n: dict(bytes=len(d), sha256=sha(d), mode=m) for n, (d, m) in files.items()})
    if repaired:
        manifest['operator_repair'] = {}
    path = tmp_path / 'source.zip'
    with zipfile.ZipFile(path, 'w') as z:
        for name, (data, mode) in files.items():
            z.writestr(bc.file_info(name, mode), data)
        z.writestr(bc.file_info('MANIFEST.json'), json_bytes(manifest))
    return path, sha(path.read_bytes())


def make_repo(tmp_path, granite, qwen):
    repo = tmp_path / 'repo'
    real = Path(__file__).resolve().parents[1]
    for name, source in bc.CODE.items():
        target = repo / source
        target.parent.mkdir(parents=True, exist_ok=True)
        if source.endswith('_MANIFEST.json'):
            continue
        target.write_bytes(b'doc\n' if source.endswith('.md') else (real / source).read_bytes())
    def manifest(directory, repository, revision):
        return dict(repository=repository, revision=revision, files=[
            dict(path=p.name, size=p.stat().st_size, sha256=sha(p.read_bytes())) for p in sorted(directory.iterdir())])
    (repo / bc.CODE[cs.QWEN_MANIFEST]).write_text(json.dumps(manifest(qwen, cs.QWEN_REPOSITORY, cs.QWEN_REVISION)))
    (repo / bc.CODE['GRANITE_MANIFEST.json']).write_text(json.dumps(manifest(granite, 'g', 'r')))
    return repo


def models(tmp_path):
    granite, qwen = tmp_path / 'g', tmp_path / 'q'
    for directory, size in ((granite, 3000), (qwen, 5000)):
        directory.mkdir()
        (directory / 'config.json').write_text('{}')
        (directory / 'model-00001.safetensors').write_bytes(b'S' * size)
    return granite, qwen


def test_build_replaces_model_and_entrypoint(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    result = bc.build(source, digest, granite, qwen, tmp_path / 'out.zip', repo=repo)
    assert result['all_members_verified'] and result['under_cap']
    with zipfile.ZipFile(tmp_path / 'out.zip') as z:
        names = set(z.namelist())
        assert not any(n.startswith('model/' + bc.OLD_REVISION) for n in names)
        assert 'MODEL_MANIFEST.json' not in names
        assert f'{cs.GRANITE_MODEL}/model-00001.safetensors' in names
        assert f'model/{cs.QWEN_REVISION}/config.json' in names
        assert z.read('scripts/predict.py') == (repo / 'submission/predict_cascade.py').read_bytes()
        assert z.read('runtime/python/run_python.sh') == b'#!/bin/sh\n'
        assert (z.getinfo('runtime/python/run_python.sh').external_attr >> 16) & 0o777 == 0o755
        assert z.getinfo(f'{cs.GRANITE_MODEL}/model-00001.safetensors').compress_type == zipfile.ZIP_STORED
        manifest = json.loads(z.read('MANIFEST.json'))
        assert set(manifest['files']) == names - {'MANIFEST.json'}
    assert (tmp_path / 'out.zip.sha256').read_text().split()[0] == result['sha256']


def test_build_rejects_bad_inputs(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    with pytest.raises(ValueError, match='SOURCE_ZIP_SHA256_MISMATCH'):
        bc.build(source, '0' * 64, granite, qwen, tmp_path / 'a.zip', repo=repo)
    (qwen / 'model-00001.safetensors').write_bytes(b'T' * 5000)
    with pytest.raises(ValueError, match='MODEL_FILE_MISMATCH'):
        bc.build(source, digest, granite, qwen, tmp_path / 'b.zip', repo=repo)
    assert not list(tmp_path.glob('*.partial')) and not (tmp_path / 'b.zip').exists()


def test_build_requires_toolchain_fixed_source(tmp_path):
    (tmp_path / 's').mkdir()
    source, digest = make_source(tmp_path / 's', repaired=False)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    with pytest.raises(ValueError, match='TOOLCHAIN_FIXED_FULL_SOURCE_REQUIRED'):
        bc.build(source, digest, granite, qwen, tmp_path / 'c.zip', repo=repo)


def test_build_granite_only(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    result = bc.build(source, digest, granite, None, tmp_path / 'g.zip', repo=repo)
    assert result['cascade_build']['granite_only']
    with zipfile.ZipFile(tmp_path / 'g.zip') as z:
        names = set(z.namelist())
    assert not any(n.startswith('model/' + cs.QWEN_REVISION) for n in names)
    assert cs.QWEN_MANIFEST not in names and f'{cs.GRANITE_MODEL}/config.json' in names


def test_build_qwen_only(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    result = bc.build(source, digest, None, qwen, tmp_path / 'q.zip', repo=repo)
    assert result['cascade_build']['qwen_only'] and not result['cascade_build']['granite_only']
    with zipfile.ZipFile(tmp_path / 'q.zip') as z:
        names = set(z.namelist())
        assert z.testzip() is None
        assert json.loads(z.read('MANIFEST.json'))['profile'] == 'QWEN38_AWQ_B2_ONLY'
    assert not any(n.startswith(cs.GRANITE_MODEL) for n in names)
    assert 'GRANITE_MANIFEST.json' not in names and cs.QWEN_MANIFEST in names
    assert f'model/{cs.QWEN_REVISION}/model-00001.safetensors' in names


def test_build_requires_some_model(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    with pytest.raises(ValueError, match='NO_MODELS'):
        bc.build(source, digest, None, None, tmp_path / 'n.zip', repo=repo)


def test_build_qwen_only_fp8_keeps_source_model(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    result = bc.build(source, digest, None, None, tmp_path / 'f.zip', repo=repo, keep_source_qwen=True)
    assert result['cascade_build']['qwen_only'] and result['cascade_build']['qwen_variant'] == 'fp8'
    with zipfile.ZipFile(tmp_path / 'f.zip') as z:
        names = set(z.namelist())
        assert z.testzip() is None
        assert z.read(f'model/{bc.OLD_REVISION}/model.safetensors') == b'W' * 1000
        assert z.read('scripts/predict.py') != b'old\n'
        assert json.loads(z.read('MANIFEST.json'))['profile'] == 'QWEN38_FP8_B2_ONLY'
    assert 'MODEL_MANIFEST.json' in names and cs.QWEN_MANIFEST not in names
    assert not any(n.startswith(cs.GRANITE_MODEL) or n.startswith('model/' + cs.QWEN_REVISION) for n in names)
    assert bc.OLD_REVISION == cs.QWEN_PROFILES['fp8']['revision']


def test_keep_source_qwen_excludes_qwen_dir(tmp_path):
    source, digest = make_source(tmp_path)
    granite, qwen = models(tmp_path)
    repo = make_repo(tmp_path, granite, qwen)
    with pytest.raises(ValueError, match='KEEP_SOURCE_QWEN_EXCLUDES_QWEN_DIR'):
        bc.build(source, digest, None, qwen, tmp_path / 'x.zip', repo=repo, keep_source_qwen=True)
