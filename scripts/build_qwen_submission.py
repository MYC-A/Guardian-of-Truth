"""Prepare a Linux offline source archive without duplicating the 29GB weights.

Run with the validated server venv. The stage contains no research data/caches.
ZIP creation is separate: stream stdout to a disk with sufficient free space.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import sysconfig
import zipfile

EXPERIMENTS = ['research_records.py', 'guardian_addons/__init__.py',
               'guardian_addons/variants2.py', 'guardian_addons/evaluator.py',
               'guardian_semantic/__init__.py', 'guardian_semantic/variants.py',
               'guardian_semantic/neutral.py', 'guardian_semantic/sandbox.py']
DISTRIBUTIONS = ['pydantic', 'pydantic-core', 'annotated-types', 'typing-extensions',
                 'typing-inspection', 'jsonschema', 'attrs', 'referencing',
                 'rpds-py', 'jsonschema-specifications', 'pandas', 'numpy',
                 'pyarrow', 'python-dateutil', 'six', 'pytz', 'tzdata']


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as f:
        for block in iter(lambda: f.read(8 * 1024 * 1024), b''):
            h.update(block)
    return h.hexdigest()


def copy_file(source, dest):
    source, dest = Path(source), Path(dest)
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(source, dest)


def prepare(repo, stage, model, llama_bin):
    repo, stage, model, llama_bin = map(Path, (repo, stage, model, llama_bin))
    if stage.exists():
        raise ValueError('STAGE_ALREADY_EXISTS')
    if sys.version_info[:2] != (3, 12) or sys.platform != 'linux':
        raise RuntimeError('BUILD_REQUIRES_VALIDATED_LINUX_CPYTHON312_VENV')
    stage.mkdir(parents=True)
    shutil.copytree(repo / 'src', stage / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative in EXPERIMENTS:
        p = repo / 'experiments' / relative
        if not p.is_file():
            raise ValueError('MISSING_RUNTIME_SOURCE: ' + relative)
        copy_file(p, stage / 'experiments' / relative)
    for directory in ('experiments', 'experiments/guardian_addons', 'experiments/guardian_semantic'):
        (stage / directory / '__init__.py').touch(exist_ok=True)
    for source, dest in [('submission/predict.py', 'scripts/predict.py'),
                         ('submission/Dockerfile', 'Dockerfile'),
                         ('submission/pyproject.toml', 'pyproject.toml'),
                         ('submission/build_backend.py', 'build_backend.py'),
                         ('docs/qwen_submission_20261008/RUNBOOK.md', 'README.md')]:
        copy_file(repo / source, stage / dest)
    (stage / 'model').mkdir()
    # Same-filesystem hardlink: do not allocate another full weight file.
    os.link(model.resolve(), stage / 'model/Qwen3.8-27B-Q8_0.gguf')
    binary_dir = stage / 'runtime/llama'
    binary_dir.mkdir(parents=True)
    copy_file(llama_bin / 'llama-server', binary_dir / 'llama-server')
    for p in llama_bin.glob('*.so*'):
        if p.is_file():
            copy_file(p.resolve(), binary_dir / p.name)
    python = Path(sys._base_executable).resolve()
    copy_file(python, stage / 'runtime/python/bin/python3.12')
    stdlib = Path(sysconfig.get_path('stdlib'))
    shutil.copytree(stdlib, stage / 'runtime/python/lib/python3.12',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'site-packages', 'dist-packages', 'test', 'tests'))
    installed = {}
    for name in DISTRIBUTIONS:
        try:
            dist = md.distribution(name)
        except md.PackageNotFoundError:
            # Version-specific optional dependencies are validated by import smoke.
            continue
        installed[dist.metadata['Name']] = dist.version
        base = Path(dist.locate_file('')).resolve()
        for item in dist.files or []:
            source = Path(dist.locate_file(item)).resolve()
            if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
                continue
            try:
                relative = source.relative_to(base)
            except ValueError:
                continue
            copy_file(source, stage / 'runtime/site-packages' / relative)
    # Copy transitive native libraries into a private runtime; the NVIDIA driver
    # remains supplied by the host/container runtime, never redistributed.
    library_dir = stage / 'runtime/lib'
    library_dir.mkdir()
    queue = [python, *binary_dir.iterdir(),
             *(stage / 'runtime/python/lib/python3.12/lib-dynload').glob('*.so'),
             *(stage / 'runtime/site-packages').rglob('*.so')]
    visited = set()
    while queue:
        path = queue.pop()
        if str(path) in visited:
            continue
        visited.add(str(path))
        completed = subprocess.run(['ldd', str(path)], text=True, capture_output=True)
        for name in re.findall(r'(?:=>\s*)?(/[^\s()]+)', completed.stdout):
            source = Path(name)
            if not source.is_file() or source.name.startswith(('libcuda.so', 'libnvidia')):
                continue
            if source.is_relative_to(stage):
                continue
            target = library_dir / source.name
            if target.exists():
                if target.stat().st_size != source.stat().st_size or digest(target) != digest(source):
                    raise RuntimeError('NATIVE_LIBRARY_COLLISION: ' + source.name)
                continue
            copy_file(source.resolve(), target)
            queue.append(source.resolve())
    (stage / '.dockerignore').write_text('__pycache__\n*.pyc\n', encoding='utf-8')
    manifest = dict(version='guardian-qwen-offline-1',
                    commit=subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip(),
                    model_sha256=digest(model), model_bytes=model.stat().st_size,
                    profile='B2', python=sys.version, distributions=installed,
                    files={str(p.relative_to(stage)): dict(bytes=p.stat().st_size, sha256=digest(p))
                           for p in stage.rglob('*') if p.is_file() and 'model' not in p.relative_to(stage).parts})
    (stage / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(dict(stage=str(stage), model_bytes=manifest['model_bytes'],
                          other_bytes=sum(x['bytes'] for x in manifest['files'].values())), indent=2), flush=True)


def archive(stage, destination):
    # A stdout stream can go straight from SSH onto another disk. ZIP64 and UNIX
    # permissions are required; files are at archive root (no wrapper directory).
    stage = Path(stage)
    output = sys.stdout.buffer if destination == '-' else open(destination, 'xb')
    try:
        with zipfile.ZipFile(output, 'w', allowZip64=True, compression=zipfile.ZIP_STORED) as z:
            for path in sorted(stage.rglob('*')):
                name = path.relative_to(stage).as_posix()
                if path.is_dir():
                    info = zipfile.ZipInfo(name + '/')
                    info.create_system = 3
                    info.external_attr = (0o40755 << 16) | 0x10
                    z.writestr(info, b'')
                    continue
                if not path.is_file():
                    raise ValueError('UNSUPPORTED_ARCHIVE_ENTRY: ' + name)
                info = zipfile.ZipInfo(name)
                info.create_system = 3
                executable = name in ('runtime/llama/llama-server', 'runtime/python/bin/python3.12',
                                      'runtime/lib/ld-linux-x86-64.so.2')
                info.external_attr = (0o100755 if executable else 0o100644) << 16
                with z.open(info, 'w', force_zip64=True) as target, path.open('rb') as source:
                    shutil.copyfileobj(source, target, 8 * 1024 * 1024)
    finally:
        if destination != '-':
            output.close()


if __name__ == '__main__':
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest='command', required=True)
    p = sub.add_parser('prepare')
    p.add_argument('--repo', required=True)
    p.add_argument('--stage', required=True)
    p.add_argument('--model', required=True)
    p.add_argument('--llama-bin', required=True)
    p = sub.add_parser('zip')
    p.add_argument('--stage', required=True)
    p.add_argument('--destination', required=True)
    a = ap.parse_args()
    if a.command == 'prepare':
        prepare(a.repo, a.stage, a.model, a.llama_bin)
    else:
        archive(a.stage, a.destination)
