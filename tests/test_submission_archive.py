import importlib.util
from pathlib import Path
import zipfile


def test_archive_root_and_all_native_executables_have_linux_permissions(tmp_path):
    script = Path(__file__).resolve().parents[1] / 'scripts/build_qwen_submission.py'
    spec = importlib.util.spec_from_file_location('submission_builder', script)
    builder = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(builder)
    stage = tmp_path / 'stage'
    paths = ['runtime/llama/llama-server', 'runtime/python/bin/python3.12',
             'runtime/lib/ld-linux-x86-64.so.2', 'scripts/predict.py', 'pyproject.toml']
    for name in paths:
        path = stage / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(b'test')
    archive = tmp_path / 'submission.zip'
    builder.archive(stage, str(archive))
    with zipfile.ZipFile(archive) as z:
        assert 'pyproject.toml' in z.namelist()
        assert not any(name.startswith('stage/') for name in z.namelist())
        for name in paths[:3]:
            assert z.getinfo(name).external_attr >> 16 & 0o777 == 0o755
        assert z.getinfo('runtime/').external_attr >> 16 & 0o777 == 0o755
        assert z.getinfo('scripts/predict.py').external_attr >> 16 & 0o777 == 0o644
