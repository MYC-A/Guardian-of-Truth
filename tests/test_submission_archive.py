import importlib.util
from pathlib import Path
import zipfile
import hashlib
import json
import pytest


def test_archive_root_and_all_native_executables_have_linux_permissions(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/build_qwen_submission.py'
    spec = importlib.util.spec_from_file_location('submission_builder', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    stage = tmp_path / 'stage'
    paths = ['runtime/llama/llama-server', 'runtime/python/bin/python3.12',
             'runtime/lib/ld-linux-x86-64.so.2', 'scripts/predict.py', 'pyproject.toml',
             'model/Qwen3.8-27B-Q8_0.gguf']
    for name in paths:
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
    pyc = stage / 'runtime/site-packages/pkg/__pycache__/module.cpython-312.pyc'
    pyc.parent.mkdir(parents=True)
    pyc.write_bytes(b'must not be archived')
    metadata = dict(bytes=4, sha256=hashlib.sha256(b'test').hexdigest())
    (stage / 'MANIFEST.json').write_text(json.dumps(dict(
        files={name: metadata for name in paths if not name.startswith('model/')},
        model_bytes=4, model_sha256=metadata['sha256'])), encoding='utf-8')
    archive = tmp_path / 'submission.zip'
    builder.archive(stage, str(archive))
    with zipfile.ZipFile(archive) as z:
        assert 'pyproject.toml' in z.namelist()
        assert not any(name.startswith('stage/') for name in z.namelist())
        assert not any('__pycache__' in name or name.endswith('.pyc') for name in z.namelist())
        for name in paths[:3]:
            assert z.getinfo(name).external_attr >> 16 & 0o777 == 0o755
        assert z.getinfo('runtime/').external_attr >> 16 & 0o777 == 0o755
        assert z.getinfo('scripts/predict.py').external_attr >> 16 & 0o777 == 0o644
    (stage / 'scripts/predict.py').write_bytes(b'tampered')
    with pytest.raises(ValueError, match='STAGE_FILE_CHANGED'):
        builder.archive(stage, str(tmp_path / 'tampered.zip'))
    assert not (tmp_path / 'tampered.zip').exists()
