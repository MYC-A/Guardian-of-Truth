"""Small, stdlib-only PEP 517 backend for the offline submission archive.

The archive builder copies this file and submission/pyproject.toml to the project
root.  No setuptools/build download is needed by ``pip install .``.  Only source
code used by the runtime is distributed; benchmark data and model weights are
deliberately outside the Python wheel.
"""
from __future__ import annotations

import base64
import csv
import gzip
import hashlib
import io
from pathlib import Path
import tarfile
import zipfile

NAME = "guardian_qwen_submission"
VERSION = "0.1.0"
DIST_INFO = f"{NAME}-{VERSION}.dist-info"
WHEEL_NAME = f"{NAME}-{VERSION}-py3-none-any.whl"
SDIST_NAME = f"{NAME}-{VERSION}.tar.gz"
# predict.py executes the separately bundled CPython and its pinned site-packages.
# Platform-side ``pip install .`` only installs this pure wheel; it must never
# resolve runtime dependencies or contact a package index.
DEPENDENCIES = ()
EXPERIMENT_FILES = (
    "experiments/research_records.py",
    "experiments/guardian_addons/__init__.py",
    "experiments/guardian_addons/variants2.py",
    "experiments/guardian_addons/evaluator.py",
    "experiments/guardian_semantic/__init__.py",
    "experiments/guardian_semantic/variants.py",
    "experiments/guardian_semantic/neutral.py",
    "experiments/guardian_semantic/sandbox.py",
)


def _root() -> Path:
    # PEP 517 invokes hooks with the source tree as the current directory.
    root = Path.cwd().resolve()
    if not (root / "src/guardian_truth/__init__.py").is_file():
        raise RuntimeError("SUBMISSION_SOURCE_TREE_REQUIRED")
    return root


def _bytes(root: Path, relative: str) -> bytes:
    path = root / relative
    if path.is_symlink() or not path.resolve().is_relative_to(root):
        raise RuntimeError(f"SUBMISSION_SOURCE_SYMLINK_FORBIDDEN: {relative}")
    if not path.is_file():
        raise RuntimeError(f"SUBMISSION_RUNTIME_FILE_MISSING: {relative}")
    return path.read_bytes()


def _sources(root: Path) -> dict[str, bytes]:
    sources = {}
    for path in sorted((root / "src/guardian_truth").rglob("*.py")):
        relative = path.relative_to(root).as_posix()
        sources[relative] = _bytes(root, relative)
    for relative in EXPERIMENT_FILES:
        sources[relative] = _bytes(root, relative)
    # The repository uses a namespace package; the isolated distribution owns a
    # regular package so an unrelated installed experiments package cannot win.
    sources["experiments/__init__.py"] = b'"""Whitelisted Guardian runtime adapters."""\n'
    return sources


def _metadata() -> dict[str, bytes]:
    text = (
        "Metadata-Version: 2.1\n"
        "Name: guardian-qwen-submission\n"
        f"Version: {VERSION}\n"
        "Summary: Offline Qwen B2 runtime for Guardian\n"
        "Requires-Python: >=3.10\n"
        + "".join(f"Requires-Dist: {value}\n" for value in DEPENDENCIES)
        + "\n"
    )
    return {
        f"{DIST_INFO}/METADATA": text.encode("utf-8"),
        f"{DIST_INFO}/WHEEL": (
            "Wheel-Version: 1.0\n"
            "Generator: guardian-stdlib-backend\n"
            "Root-Is-Purelib: true\n"
            "Tag: py3-none-any\n"
        ).encode("utf-8"),
        f"{DIST_INFO}/top_level.txt": b"guardian_truth\nexperiments\n",
    }


def get_requires_for_build_wheel(config_settings=None):
    return []


def get_requires_for_build_sdist(config_settings=None):
    return []


def prepare_metadata_for_build_wheel(metadata_directory, config_settings=None):
    directory = Path(metadata_directory)
    for name, data in _metadata().items():
        target = directory / name
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_bytes(data)
    return DIST_INFO


def build_wheel(wheel_directory, config_settings=None, metadata_directory=None):
    root = _root()
    files = {
        name.removeprefix("src/"): data
        for name, data in _sources(root).items()
    }
    metadata = _metadata()
    if metadata_directory is not None:
        supplied = Path(metadata_directory)
        if supplied.name != DIST_INFO:
            supplied = supplied / DIST_INFO
        for name, expected in metadata.items():
            actual = supplied / Path(name).name
            if not actual.is_file() or actual.read_bytes() != expected:
                raise RuntimeError("SUBMISSION_BUILD_METADATA_CHANGED")
    files.update(metadata)
    record_name = f"{DIST_INFO}/RECORD"
    record = io.StringIO(newline="")
    writer = csv.writer(record, lineterminator="\n")
    for name, data in sorted(files.items()):
        digest = base64.urlsafe_b64encode(hashlib.sha256(data).digest()).rstrip(b"=").decode("ascii")
        writer.writerow((name, "sha256=" + digest, str(len(data))))
    writer.writerow((record_name, "", ""))
    files[record_name] = record.getvalue().encode("utf-8")
    output = Path(wheel_directory)
    output.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(output / WHEEL_NAME, "w", compression=zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(files.items()):
            info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.create_system = 3
            info.external_attr = 0o100644 << 16
            archive.writestr(info, data)
    return WHEEL_NAME


def build_sdist(sdist_directory, config_settings=None):
    root = _root()
    files = _sources(root)
    for name in ("build_backend.py", "pyproject.toml"):
        files[name] = _bytes(root, name)
    files["PKG-INFO"] = _metadata()[f"{DIST_INFO}/METADATA"]
    output = Path(sdist_directory)
    output.mkdir(parents=True, exist_ok=True)
    with (output / SDIST_NAME).open("wb") as handle:
        with gzip.GzipFile(filename="", mode="wb", fileobj=handle, mtime=0) as compressed:
            with tarfile.open(fileobj=compressed, mode="w", format=tarfile.PAX_FORMAT) as archive:
                for name, data in sorted(files.items()):
                    info = tarfile.TarInfo(f"{NAME}-{VERSION}/{name}")
                    info.size = len(data)
                    info.mode = 0o644
                    info.mtime = 0
                    archive.addfile(info, io.BytesIO(data))
    return SDIST_NAME
