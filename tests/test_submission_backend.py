"""Packaging boundaries, reproducible builds, and an actual offline pip build."""
import base64
import csv
import hashlib
import importlib.util
import io
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tarfile
import zipfile

import pytest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("submission_backend", ROOT / "submission/build_backend.py")
backend = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(backend)


def source_tree(tmp_path):
    root = tmp_path / "project"
    (root / "src/guardian_truth").mkdir(parents=True)
    (root / "src/guardian_truth/__init__.py").write_text("VALUE = 'isolated'\n", encoding="utf-8")
    (root / "src/guardian_truth/runtime.py").write_text("VALUE = 42\n", encoding="utf-8")
    for name in backend.EXPERIMENT_FILES:
        target = root / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text("# runtime adapter\n", encoding="utf-8")
    for name in ("build_backend.py", "pyproject.toml"):
        shutil.copyfile(ROOT / "submission" / name, root / name)
    for name in ("outputs/gold.json", "tests/test_secret.py", "models/weights.gguf",
                 "experiments/guardian_addons/outputs/gold.json", "experiments/evil.py",
                 "src/guardian_truth/__pycache__/runtime.pyc"):
        path = root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("DO NOT DISTRIBUTE", encoding="utf-8")
    return root


def test_wheel_whitelist_record_and_reproducibility(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    monkeypatch.chdir(root)
    first, second = tmp_path / "first", tmp_path / "second"
    name = backend.build_wheel(first)
    backend.build_wheel(second)
    assert (first / name).read_bytes() == (second / name).read_bytes()
    with zipfile.ZipFile(first / name) as archive:
        names = archive.namelist()
        assert "guardian_truth/runtime.py" in names
        assert "experiments/__init__.py" in names
        assert all(not name.startswith(("src/", "outputs/", "models/", "tests/")) for name in names)
        assert "experiments/evil.py" not in names
        assert not any("gold" in name or name.endswith(".pyc") for name in names)
        rows = list(csv.reader(io.StringIO(archive.read(f"{backend.DIST_INFO}/RECORD").decode())))
        assert {row[0] for row in rows} == set(names)
        for path, digest, size in rows:
            if path.endswith("/RECORD"):
                assert digest == size == ""
            else:
                data = archive.read(path)
                expected = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode()
                assert digest == "sha256=" + expected
                assert size == str(len(data))


def test_sdist_rebuild_and_metadata(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    monkeypatch.chdir(root)
    metadata = tmp_path / "metadata"
    name = backend.prepare_metadata_for_build_wheel(metadata)
    backend.build_wheel(tmp_path / "wheel", metadata_directory=metadata / name)
    sdist = backend.build_sdist(tmp_path / "sdist")
    with tarfile.open(tmp_path / "sdist" / sdist) as archive:
        names = archive.getnames()
        assert any(name.endswith("/build_backend.py") for name in names)
        assert any(name.endswith("/src/guardian_truth/runtime.py") for name in names)
        assert not any("gold" in name or "/models/" in name or "/tests/" in name for name in names)
        archive.extractall(tmp_path / "extracted", filter="data")
    monkeypatch.chdir(tmp_path / "extracted" / f"{backend.NAME}-{backend.VERSION}")
    rebuilt = backend.build_wheel(tmp_path / "rebuilt")
    assert (tmp_path / "rebuilt" / rebuilt).read_bytes() == (tmp_path / "wheel" / rebuilt).read_bytes()
    (metadata / name / "METADATA").write_text("changed", encoding="utf-8")
    with pytest.raises(RuntimeError, match="METADATA_CHANGED"):
        backend.build_wheel(tmp_path / "invalid", metadata_directory=metadata / name)


def test_missing_runtime_file_fails_build(tmp_path, monkeypatch):
    root = source_tree(tmp_path)
    (root / backend.EXPERIMENT_FILES[-1]).unlink()
    monkeypatch.chdir(root)
    with pytest.raises(RuntimeError, match="RUNTIME_FILE_MISSING"):
        backend.build_wheel(tmp_path / "wheel")


def test_actual_pip_install_no_index_with_build_isolation(tmp_path):
    root = source_tree(tmp_path)
    target = tmp_path / "installed"
    env = dict(os.environ, PIP_NO_INDEX="1", PIP_DISABLE_PIP_VERSION_CHECK="1", PYTHONDONTWRITEBYTECODE="1")
    completed = subprocess.run(
        [sys.executable, "-m", "pip", "install", "--no-index", "--no-deps", "--target", str(target), str(root)],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=120,
    )
    assert completed.returncode == 0, completed.stdout + completed.stderr
    env["PYTHONPATH"] = str(target)
    imported = subprocess.run(
        [sys.executable, "-c", "import guardian_truth.runtime, experiments.guardian_addons.variants2; "
         "assert guardian_truth.runtime.VALUE == 42; print(guardian_truth.runtime.__file__)"],
        cwd=tmp_path, env=env, capture_output=True, text=True, timeout=20,
    )
    assert imported.returncode == 0, imported.stdout + imported.stderr
    assert str(target) in imported.stdout
