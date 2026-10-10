"""Freeze a Linux CPython-3.12 vLLM installation into an offline root-level ZIP.

Prepare uses same-filesystem hardlinks for immutable model/wheel assets. ZIP can
be streamed to stdout; the server need not have space for a second 40-GB copy.
No installation, model request, historical cache or benchmark data is included.
"""
from __future__ import annotations

import argparse
import base64
import hashlib
import importlib.metadata as md
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import sysconfig
import zipfile

REPOSITORY = 'Qwen/Qwen3.8-27B-FP8'
REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
ENGINE_VERSION = '0.19.1'
VERSION = 'guardian-vllm-offline-1'
MAX_ARCHIVE_BYTES = 40_000_000_000
DRIVER = re.compile(r'^(?:libcuda\.so(?:\..*)?|libnvidia[^/]*\.so(?:\..*)?)$')
EXPERIMENTS = (
    'research_records.py', 'guardian_addons/__init__.py',
    'guardian_addons/variants2.py', 'guardian_addons/evaluator.py',
    'guardian_semantic/__init__.py', 'guardian_semantic/variants.py',
    'guardian_semantic/neutral.py', 'guardian_semantic/sandbox.py',
)


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def relative_name(name):
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('UNSAFE_ASSET_PATH')
    parsed = PurePosixPath(name)
    if parsed.is_absolute() or '..' in parsed.parts or parsed.as_posix() != name:
        raise ValueError('UNSAFE_ASSET_PATH')
    return parsed


def write_json(path, value):
    Path(path).write_text(json.dumps(value, indent=2, sort_keys=True, allow_nan=False) + '\n',
                          encoding='utf-8', newline='\n')


def materialize(source, destination, *, allowed_root=None):
    """Resolve internal symlinks, refuse escape, and never chmod/write originals."""
    source, destination = Path(source).resolve(strict=True), Path(destination)
    if allowed_root is not None and not source.is_relative_to(Path(allowed_root).resolve()):
        raise ValueError('SOURCE_ESCAPES_ALLOWED_ROOT')
    if not source.is_file():
        raise ValueError('REGULAR_SOURCE_REQUIRED')
    destination.parent.mkdir(parents=True, exist_ok=True)
    if destination.exists():
        if destination.is_symlink():
            raise ValueError('STAGE_PATH_COLLISION:' + str(destination))
        if os.path.samefile(source, destination):
            return
        if digest(destination) != digest(source):
            raise ValueError('STAGE_PATH_COLLISION:' + str(destination))
        return
    if source.stat().st_dev != destination.parent.stat().st_dev:
        raise ValueError('SAME_FILESYSTEM_HARDLINK_REQUIRED:' + str(source))
    os.link(source, destination)


def copy_tree(source, destination, *, exclude=()):
    source = Path(source).resolve()
    for path in sorted(source.rglob('*')):
        rel = path.relative_to(source)
        if any(part in exclude for part in rel.parts) or path.suffix in ('.pyc', '.pyo'):
            continue
        if path.is_file():
            materialize(path, Path(destination) / rel, allowed_root=source)


def stage_files(stage):
    root = Path(stage)
    for path in sorted(root.rglob('*')):
        if path.is_symlink():
            raise ValueError('STAGE_SYMLINK_FORBIDDEN:' + path.relative_to(root).as_posix())
        if path.is_file():
            yield path
        elif not path.is_dir():
            raise ValueError('UNSUPPORTED_STAGE_ENTRY')


def inventory(stage):
    root = Path(stage)
    return {p.relative_to(root).as_posix():
            dict(bytes=p.stat().st_size, sha256=digest(p), mode=0o755 if p.stat().st_mode & 0o111 else 0o644)
            for p in stage_files(root) if p.name != 'MANIFEST.json' or p.parent != root}


def model_declarations(manifest):
    """Validate pinned expected metadata without implying local model verification."""
    if manifest.get('repository') != REPOSITORY or manifest.get('revision') != REVISION:
        raise ValueError('MODEL_IDENTITY_MISMATCH')
    records, names = manifest.get('files'), set()
    if not isinstance(records, list) or not records:
        raise ValueError('MODEL_ASSET_INVENTORY_REQUIRED')
    result = []
    for entry in records:
        if not isinstance(entry, dict):
            raise ValueError('INVALID_MODEL_ASSET')
        name = entry.get('path')
        relative_name(name)
        if name in names:
            raise ValueError('DUPLICATE_MODEL_ASSET')
        names.add(name)
        size, checksum = entry.get('size'), entry.get('sha256')
        if (type(size) is not int or size < 1 or not isinstance(checksum, str)
                or re.fullmatch('[0-9a-f]{64}', checksum) is None):
            raise ValueError('INVALID_MODEL_ASSET')
        result.append(dict(path=name, size=size, sha256=checksum))
    required = {'config.json', 'tokenizer.json', 'tokenizer_config.json', 'model.safetensors.index.json'}
    if not required.issubset(names) or not any(name.endswith('.safetensors') for name in names):
        raise ValueError('MODEL_REQUIRED_ASSET_MISSING')
    return sorted(result, key=lambda entry: entry['path'])


def model_assets(model_dir, manifest):
    root = Path(model_dir).resolve()
    result = []
    declared = model_declarations(manifest)
    names = {entry['path'] for entry in declared}
    for entry in declared:
        name, size, checksum = entry['path'], entry['size'], entry['sha256']
        path = (root / name).resolve(strict=True)
        if not path.is_relative_to(root) or not path.is_file():
            raise ValueError('MODEL_ASSET_ESCAPE')
        if path.stat().st_size != size or digest(path) != checksum:
            raise ValueError('MODEL_ASSET_BYTES_CHANGED:' + name)
        result.append((name, path))
    index = json.loads((root / 'model.safetensors.index.json').read_text(encoding='utf-8'))
    weights = index.get('weight_map')
    if not isinstance(weights, dict) or not weights:
        raise ValueError('MODEL_INDEX_REQUIRED')
    if set(weights.values()) != {name for name in names if name.endswith('.safetensors')}:
        raise ValueError('MODEL_INDEX_ASSET_SET_MISMATCH')
    config = json.loads((root / 'config.json').read_text(encoding='utf-8'))
    if config.get('quantization_config', {}).get('quant_method') != 'fp8':
        raise ValueError('MODEL_FP8_REQUIRED')
    return result


def check_record(path, item):
    """Verify installed wheel RECORD before using its bytes in the frozen bundle."""
    expected_size = getattr(item, 'size', None)
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError('WHEEL_RECORD_SIZE_MISMATCH:' + str(item))
    expected = getattr(item, 'hash', None)
    if expected is not None:
        if expected.mode not in hashlib.algorithms_available:
            raise ValueError('UNSUPPORTED_WHEEL_RECORD_HASH')
        value = hashlib.new(expected.mode)
        with path.open('rb') as stream:
            for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b''):
                value.update(chunk)
        actual = base64.urlsafe_b64encode(value.digest()).rstrip(b'=').decode('ascii')
        if actual != expected.value:
            raise ValueError('WHEEL_RECORD_HASH_MISMATCH:' + str(item))


def shell_python_script(stage, name, source):
    if Path(name).name != name or not re.fullmatch('[A-Za-z0-9_.+-]+', name):
        raise ValueError('UNSAFE_WHEEL_EXECUTABLE_NAME')
    target = Path(stage) / 'runtime/bin' / name
    target.parent.mkdir(parents=True, exist_ok=True)
    materialize(source, Path(stage) / 'runtime/wheel-scripts' / name)
    wrapper = ('#!/bin/sh\nset -eu\n'
               'HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
               f'exec "$HERE/../python/run_python.sh" "$HERE/../wheel-scripts/{name}" "$@"\n')
    if target.exists():
        if target.read_text(encoding='utf-8') != wrapper:
            raise ValueError('WHEEL_EXECUTABLE_COLLISION')
    else:
        target.write_text(wrapper, encoding='utf-8', newline='\n')
        target.chmod(0o755)


def collect_wheels(stage, distributions=None, *, prefix=None, overlays=None):
    distributions = list(md.distributions()) if distributions is None else list(distributions)
    prefix = Path(sys.prefix if prefix is None else prefix).resolve()
    versions, ownership = {}, {}
    record_owners = {}
    for dist in distributions:
        for item in dist.files or []:
            resolved = Path(dist.locate_file(item)).resolve()
            record_owners.setdefault(resolved, []).append((dist.metadata['Name'], item))
    for dist in sorted(distributions, key=lambda d: d.metadata['Name'].lower()):
        name = dist.metadata['Name']
        if name in versions:
            raise ValueError('DUPLICATE_INSTALLED_DISTRIBUTION')
        versions[name] = dist.version
        files = dist.files
        if not files:
            raise ValueError('WHEEL_RECORD_REQUIRED:' + name)
        base = Path(dist.locate_file('')).resolve()
        if not base.is_relative_to(prefix):
            raise ValueError('DISTRIBUTION_OUTSIDE_VENV:' + name)
        for item in sorted(files, key=str):
            item_text = str(item)
            if '__pycache__' in PurePosixPath(item_text).parts or item_text.endswith(('.pyc', '.pyo')):
                continue
            source = Path(dist.locate_file(item)).resolve(strict=True)
            if not source.is_file() or not source.is_relative_to(prefix):
                raise ValueError('WHEEL_RECORD_OUTSIDE_VENV:' + item_text)
            if DRIVER.fullmatch(source.name):
                raise ValueError('HOST_DRIVER_OR_STUB_FORBIDDEN')
            try:
                check_record(source, item)
            except ValueError as original:
                # pip may install two wheels declaring the same path. Preserve
                # the actual validated environment only when its final bytes
                # match another authenticated RECORD; never accept arbitrary
                # tampering or guess an owner from installation order.
                winners = []
                for owner, other in record_owners[source]:
                    if getattr(other, 'hash', None) is None or getattr(other, 'size', None) is None:
                        continue
                    try:
                        check_record(source, other)
                    except ValueError:
                        continue
                    winners.append(owner)
                if not winners:
                    raise original
                if overlays is not None:
                    overlays.append(dict(path=item_text, shadowed_distribution=name,
                                         actual_record_owners=sorted(set(winners)), sha256=digest(source)))
            if source.is_relative_to(base):
                relative = source.relative_to(base)
                if source.suffix == '.pth':
                    for line in source.read_text(encoding='utf-8').splitlines():
                        line = line.strip()
                        if not line or line.startswith('#'):
                            continue
                        if line.startswith(('import ', 'import\t')):
                            # Vendor hooks (including CUDA's bindings redirector)
                            # are part of the pinned wheel, not host customization.
                            # They must have an authenticated installed RECORD.
                            if getattr(item, 'hash', None) is None or getattr(item, 'size', None) is None:
                                raise ValueError('UNVERIFIED_PTH_HOOK:' + item_text)
                        elif PurePosixPath(line).is_absolute() or Path(line).is_absolute() or '..' in Path(line).parts:
                            raise ValueError('EXTERNAL_PTH_PATH_FORBIDDEN:' + item_text)
                destination = Path(stage) / 'runtime/site-packages' / relative
                materialize(source, destination, allowed_root=base)
            elif source.parent == prefix / 'bin':
                with source.open('rb') as stream:
                    first = stream.read(256)
                if first.startswith(b'#!') and b'python' in first.split(b'\n', 1)[0]:
                    shell_python_script(stage, source.name, source)
                    destination = Path(stage) / 'runtime/wheel-scripts' / source.name
                else:
                    # Native/ordinary shell executables keep their original bytes.
                    destination = Path(stage) / 'runtime/bin' / source.name
                    materialize(source, destination, allowed_root=prefix)
            else:
                # Wheel-installed headers/data inside the venv are retained too.
                destination = Path(stage) / 'runtime/python' / source.relative_to(prefix)
                materialize(source, destination, allowed_root=prefix)
            key = destination.relative_to(stage).as_posix()
            ownership.setdefault(key, []).append(name)
    return versions, ownership


def elf(path):
    with Path(path).open('rb') as stream:
        return stream.read(4) == b'\x7fELF'


def library_directories(stage):
    root = Path(stage)
    dirs = {p.parent for p in stage_files(root) if '.so' in p.name}
    return [root / 'runtime/lib', *sorted(dirs - {root / 'runtime/lib'})]


def collect_native(stage, *, run=subprocess.run):
    """Resolve every ELF's ldd closure; a missing non-driver dependency is fatal."""
    root = Path(stage).resolve()
    libraries = root / 'runtime/lib'
    libraries.mkdir(parents=True, exist_ok=True)
    queue = [p for p in stage_files(root) if elf(p)]
    seen, dependencies, unresolved = set(), {}, set()
    search_dirs = library_directories(root)
    env = dict(os.environ, LD_LIBRARY_PATH=os.pathsep.join(map(str, search_dirs)))
    for variable in ('LD_PRELOAD', 'PYTHONHOME', 'PYTHONPATH'):
        env.pop(variable, None)
    while queue:
        path = queue.pop()
        if path in seen:
            continue
        seen.add(path)
        reply = run(['ldd', str(path)], text=True, capture_output=True, env=env, timeout=30)
        text = reply.stdout + '\n' + reply.stderr
        if reply.returncode and not any(s in text for s in ('statically linked', 'not a dynamic executable')):
            raise RuntimeError('LDD_FAILED:' + path.relative_to(root).as_posix())
        found = []
        for line in text.splitlines():
            missing = re.match(r'\s*(\S+)\s+=>\s+not found', line)
            if missing:
                if DRIVER.fullmatch(missing.group(1)):
                    continue
                unresolved.add(missing.group(1))
                continue
            for value in re.findall(r'(?:=>\s*)?((?:[A-Za-z]:)?/[^\s()]+)', line):
                source = Path(value).resolve(strict=True)
                if DRIVER.fullmatch(source.name):
                    continue
                if source.is_relative_to(root):
                    found.append(source.relative_to(root).as_posix())
                    continue
                destination = libraries / source.name
                materialize(source, destination)
                # ldd reports the actual file; preserve required SONAME spelling.
                original_name = Path(value).name
                if original_name != source.name:
                    materialize(source, libraries / original_name)
                found.append(destination.relative_to(root).as_posix())
                queue.append(destination)
        dependencies[path.relative_to(root).as_posix()] = sorted(set(found))
    if unresolved:
        raise RuntimeError('UNRESOLVED_NATIVE_DEPENDENCY:' + ','.join(sorted(unresolved)))
    if not (libraries / 'ld-linux-x86-64.so.2').is_file():
        raise RuntimeError('PRIVATE_GLIBC_LOADER_REQUIRED')
    return dependencies


def write_launcher(stage):
    root = Path(stage)
    from scripts.vllm_bundle_toolchain import environment_shell
    compiler_environment = environment_shell(root).replace('$root', '$ROOT')
    native_dirs = [p.relative_to(root).as_posix() for p in library_directories(root)]
    expressions = ':'.join('$ROOT/' + directory for directory in native_dirs)
    launcher = '''#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
ROOT=$(CDPATH= cd -- "$HERE/../.." && pwd)
unset LD_PRELOAD LD_LIBRARY_PATH PYTHONSTARTUP PYTHONUSERBASE
export PYTHONHOME="$ROOT/runtime/python"
export PYTHONPATH="$ROOT/runtime/site-packages:$ROOT/src:$ROOT"
export PYTHONNOUSERSITE=1 PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1
export GUARDIAN_BUNDLED_PYTHON=1 HF_HUB_OFFLINE=1 TRANSFORMERS_OFFLINE=1
export HF_DATASETS_OFFLINE=1 VLLM_NO_USAGE_STATS=1 DO_NOT_TRACK=1
export HF_HOME="${HF_HOME:-${TMPDIR:-/tmp}/guardian-vllm-hf-state}"
export TRITON_CACHE_DIR="${TRITON_CACHE_DIR:-${TMPDIR:-/tmp}/guardian-vllm-triton}"
export VLLM_CACHE_ROOT="${VLLM_CACHE_ROOT:-${TMPDIR:-/tmp}/guardian-vllm-cache}"
__COMPILER_ENVIRONMENT__
export PATH="$ROOT/runtime/bin:$PATH"
LIBRARY_PATHS="__LIBRARY_PATHS__"
# Children start this same wrapper via sys.executable. The private loader's
# --library-path avoids poisoning unrelated host commands with bundled glibc.
exec "$ROOT/runtime/lib/ld-linux-x86-64.so.2" --library-path "$LIBRARY_PATHS" \\
    --argv0 "$ROOT/runtime/python/bin/python3.12" "$ROOT/runtime/python/bin/python3.12.real" "$@"
'''.replace('__LIBRARY_PATHS__', expressions).replace('__COMPILER_ENVIRONMENT__', compiler_environment.rstrip())
    path = root / 'runtime/python/run_python.sh'
    path.write_text(launcher, encoding='utf-8', newline='\n')
    path.chmod(0o755)
    shim = root / 'runtime/python/bin/python3.12'
    shim.write_text('#!/bin/sh\nset -eu\nHERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)\n'
                    'exec "$HERE/../run_python.sh" "$@"\n', encoding='utf-8', newline='\n')
    shim.chmod(0o755)
    # PYTHONPATH alone does not execute vendor .pth files. Activate the frozen
    # wheel directory through Python's standard site initialization, just as
    # the validated venv does. No host /etc/sitecustomize is included.
    vendor_site = root / 'runtime/python/lib/python3.12/site-packages'
    vendor_site.mkdir(parents=True, exist_ok=True)
    (vendor_site / 'guardian-vendor.pth').write_text(
        'import site, sys, os; site.addsitedir(os.path.join(os.path.dirname(sys.prefix), "site-packages"))\n',
        encoding='utf-8', newline='\n')


def collect_sources(repo, stage):
    repo, stage = Path(repo).resolve(), Path(stage)
    copy_tree(repo / 'src', stage / 'src', exclude=('__pycache__', 'tests', 'test'))
    for name in EXPERIMENTS:
        materialize(repo / 'experiments' / name, stage / 'experiments' / name, allowed_root=repo)
    (stage / 'experiments/__init__.py').write_text('"""Whitelisted Guardian runtime adapters."""\n', encoding='utf-8')
    for source, destination in (
        ('submission/predict_vllm.py', 'scripts/predict.py'),
        ('scripts/qwen_vllm_adapter.py', 'scripts/qwen_vllm_adapter.py'),
        ('submission/pyproject.toml', 'pyproject.toml'),
        ('submission/build_backend.py', 'build_backend.py'),
        ('docs/qwen_vllm_submission_20261010/RUNBOOK.md', 'README.md'),
    ):
        materialize(repo / source, stage / destination, allowed_root=repo)
    (stage / 'scripts/__init__.py').write_text('"""Offline local inference transport."""\n', encoding='utf-8')
    copy_tree(repo / 'submission/licenses', stage / 'licenses', exclude=('__pycache__',))
    for path in stage_files(stage):
        if path.suffix in ('.parquet', '.jsonl', '.log', '.env') or path.name in ('valid.parquet', 'api_keys.env'):
            raise ValueError('RESEARCH_DATA_OR_SECRET_IN_SOURCE_STAGE')


def prepare(repo, stage, model_dir, asset_manifest, *, runtime_only=False):
    if type(runtime_only) is not bool:
        raise ValueError('RUNTIME_ONLY_MUST_BE_BOOL')
    if not runtime_only and model_dir is None:
        raise ValueError('FULL_BUILD_REQUIRES_MODEL_DIR')
    if sys.platform != 'linux' or sys.version_info[:2] != (3, 12) or sys.prefix == sys.base_prefix:
        raise RuntimeError('VALIDATED_LINUX_CPYTHON312_VENV_REQUIRED')
    repo, stage = map(lambda p: Path(p).resolve(), (repo, stage))
    model_dir = None if model_dir is None else Path(model_dir).resolve()
    if stage.exists():
        raise FileExistsError(stage)
    for source in (repo, Path(sys.prefix).resolve(), *(() if model_dir is None else (model_dir,))):
        if stage.is_relative_to(source):
            raise ValueError('STAGE_MUST_BE_SEPARATE_FROM_INPUTS')
    source_sha = subprocess.check_output(['git', '-C', str(repo), 'rev-parse', 'HEAD'], text=True).strip()
    if subprocess.check_output(['git', '-C', str(repo), 'status', '--porcelain'], text=True).strip():
        raise ValueError('CLEAN_REVIEWED_SOURCE_REQUIRED')
    if md.version('vllm') != ENGINE_VERSION or md.version('transformers') != '5.8.0':
        raise ValueError('VALIDATED_ENGINE_AND_TRANSFORMERS_REQUIRED')
    supplied = json.loads(Path(asset_manifest).read_text(encoding='utf-8'))
    declarations = model_declarations(supplied)
    models = [] if runtime_only else model_assets(model_dir, supplied)
    stage.mkdir(parents=True)
    collect_sources(repo, stage)
    python = Path(sys._base_executable).resolve()
    materialize(python, stage / 'runtime/python/bin/python3.12.real')
    copy_tree(sysconfig.get_path('stdlib'), stage / 'runtime/python/lib/python3.12',
              exclude=('__pycache__', 'site-packages', 'dist-packages', 'tests', 'test', 'idlelib', 'tkinter',
                       'ensurepip', 'sitecustomize.py', 'libpython3.12.so'))
    # Debian's stdlib contains links to host customization and its shared
    # interpreter outside the stdlib tree. Never import /etc/sitecustomize;
    # include the declared interpreter library explicitly instead.
    library = Path(sysconfig.get_config_var('LIBDIR')) / sysconfig.get_config_var('LDLIBRARY')
    if library.is_file():
        materialize(library, stage / 'runtime/lib' / library.name)
        if library.resolve().name != library.name:
            materialize(library.resolve(), stage / 'runtime/lib' / library.resolve().name)
    for include in set(filter(None, (sysconfig.get_path('include'), sysconfig.get_path('platinclude')))):
        copy_tree(include, stage / 'runtime/python/include/python3.12', exclude=('__pycache__',))
    overlays = []
    versions, ownership = collect_wheels(stage, overlays=overlays)
    for name, source in models:
        materialize(source, stage / 'model' / REVISION / name, allowed_root=model_dir)
    materialize(asset_manifest, stage / 'MODEL_MANIFEST.json')
    # GCC/header/sysroot relocation is assembled separately and reviewed.
    from scripts.vllm_bundle_toolchain import prepare as prepare_toolchain
    toolchain = prepare_toolchain(stage)
    native = collect_native(stage)
    write_launcher(stage)
    (stage / '.dockerignore').write_text('__pycache__\n*.pyc\n', encoding='utf-8')
    (stage / 'Dockerfile').write_text('FROM ubuntu:24.04\nWORKDIR /app\nCOPY . /app\n'
        'ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUTF8=1 GUARDIAN_BUNDLED_PYTHON=1\n'
        'USER 65534:65534\nENTRYPOINT ["/app/runtime/python/run_python.sh", "-X", "utf8", "/app/scripts/predict.py"]\n',
        encoding='utf-8', newline='\n')
    manifest = dict(version=VERSION, source_sha=source_sha, model_repository=REPOSITORY,
        model_revision=REVISION, engine_version=ENGINE_VERSION, python=sys.version,
        profile='B2_FP8_VLLM_GRAPHS16', max_archive_bytes=MAX_ARCHIVE_BYTES,
        model_mode='RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED' if runtime_only else 'FULL_MODELS_SHA256_VERIFIED',
        models_expected=declarations,
        model_manifest_sha256=digest(stage / 'MODEL_MANIFEST.json'), distributions=versions,
        wheel_ownership=ownership, wheel_record_overlays=overlays, native_dependencies=native, toolchain=toolchain,
        integrity_contract=('Every staged runtime file SHA256; model metadata only, local bytes NOT_VERIFIED'
                            if runtime_only else 'Every staged file SHA256; model upstream manifest independently rechecked'),
        gpu_validation='NOT_EXECUTED_BY_BUILDER', files=inventory(stage))
    write_json(stage / 'MANIFEST.json', manifest)
    return manifest


def verify_stage(stage):
    root = Path(stage)
    manifest = json.loads((root / 'MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('version') != VERSION or manifest.get('max_archive_bytes') != MAX_ARCHIVE_BYTES:
        raise ValueError('BUNDLE_MANIFEST_CONTRACT_MISMATCH')
    if inventory(root) != manifest['files']:
        raise ValueError('STAGE_FILE_SET_OR_BYTES_CHANGED')
    for name in manifest['files']:
        relative_name(name)
        if DRIVER.fullmatch(Path(name).name):
            raise ValueError('HOST_DRIVER_OR_STUB_FORBIDDEN')
    if digest(root / 'MODEL_MANIFEST.json') != manifest['model_manifest_sha256']:
        raise ValueError('MODEL_MANIFEST_CHANGED')
    if manifest.get('model_mode') == 'RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED':
        declared = model_declarations(json.loads((root / 'MODEL_MANIFEST.json').read_text(encoding='utf-8')))
        if manifest.get('models_expected') != declared or (root / 'model').exists():
            raise ValueError('RUNTIME_ONLY_MODEL_CONTRACT_CHANGED')
    return manifest


def smoke(stage):
    """CPU relocation and child-process test, never starts a CUDA model."""
    root = Path(stage).resolve()
    verify_stage(root)
    script = '''import json, os, sys, subprocess, sysconfig
import torch, transformers, vllm, pandas, pyarrow, pydantic
from guardian_truth.submission.cli import predict_one
from scripts.qwen_vllm_adapter import MODEL
assert os.environ.get('GUARDIAN_BUNDLED_PYTHON') == '1'
assert os.path.isfile(sysconfig.get_path('include')+'/Python.h')
assert sys.executable.endswith('/runtime/python/bin/python3.12'), sys.executable
child = subprocess.check_output([sys.executable, '-c', 'import os,sys; assert os.environ.get("GUARDIAN_BUNDLED_PYTHON")=="1"; print(sys.executable)'],text=True).strip()
assert child == sys.executable, (child,sys.executable)
print(json.dumps(dict(status='COMPLETE', executable=sys.executable, child=child,
    vllm=vllm.__version__, torch=torch.__version__, transformers=transformers.__version__,
    gpu='NOT_EXECUTED')))
'''
    env = dict(os.environ)
    for key in ('PYTHONHOME', 'PYTHONPATH', 'LD_LIBRARY_PATH', 'LD_PRELOAD'):
        env.pop(key, None)
    reply = subprocess.run([str(root / 'runtime/python/run_python.sh'), '-X', 'utf8', '-c', script],
                           env=env, text=True, capture_output=True, timeout=180, cwd=root)
    if reply.returncode:
        raise RuntimeError('BUNDLED_CPU_SMOKE_FAILED:\n' + reply.stderr[-4000:])
    return json.loads(reply.stdout.splitlines()[-1])


class CappedStream:
    """Non-seekable byte counter/hash: cap includes ZIP headers and central index."""
    def __init__(self, stream, cap):
        if type(cap) is not int or not 0 < cap <= MAX_ARCHIVE_BYTES:
            raise ValueError('INVALID_ARCHIVE_CAP')
        self.stream, self.cap, self.count = stream, cap, 0
        self.hash = hashlib.sha256()

    def write(self, raw):
        if self.count + len(raw) > self.cap:
            raise ValueError('ARCHIVE_EXCEEDS_PLATFORM_CAP')
        count = self.stream.write(raw)
        if count is not None and count != len(raw):
            raise OSError('SHORT_ARCHIVE_WRITE')
        self.count += len(raw)
        self.hash.update(raw)
        return len(raw)

    def tell(self):
        return self.count

    def seek(self, *args):
        raise OSError('NONSEEKABLE_ARCHIVE_STREAM')

    def flush(self):
        self.stream.flush()


def archive(stage, destination, *, cap=MAX_ARCHIVE_BYTES, report=None, stream=None, runtime_only=False):
    root = Path(stage).resolve()
    if type(runtime_only) is not bool:
        raise ValueError('RUNTIME_ONLY_MUST_BE_BOOL')
    if report is not None:
        if Path(report).resolve().is_relative_to(root):
            raise ValueError('ARCHIVE_REPORT_MUST_BE_OUTSIDE_FROZEN_STAGE')
        if Path(report).exists():
            raise FileExistsError(report)
    if destination != '-' and Path(destination).resolve().is_relative_to(root):
        raise ValueError('ARCHIVE_DESTINATION_MUST_BE_OUTSIDE_FROZEN_STAGE')
    manifest = verify_stage(root)
    if manifest.get('model_mode') == 'RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED' and not runtime_only:
        raise ValueError('RUNTIME_ONLY_STAGE_REQUIRES_RUNTIME_EXPORT')
    frozen_manifest_sha256 = digest(root / 'MANIFEST.json')
    expected = dict(manifest['files'])
    expected['MANIFEST.json'] = dict(bytes=(root / 'MANIFEST.json').stat().st_size,
                                   sha256=frozen_manifest_sha256)
    own = stream is None and destination != '-'
    raw = stream if stream is not None else (open(destination, 'xb') if own else sys.stdout.buffer)
    output = CappedStream(raw, cap)
    try:
        with zipfile.ZipFile(output, 'w', allowZip64=True, compression=zipfile.ZIP_DEFLATED, compresslevel=1) as bundle:
            for path in stage_files(root):
                name = path.relative_to(root).as_posix()
                if runtime_only and name.startswith('model/'):
                    continue
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (0o100000 | (0o755 if path.stat().st_mode & 0o111 else 0o644)) << 16
                info.compress_type = zipfile.ZIP_STORED if name.endswith('.safetensors') else zipfile.ZIP_DEFLATED
                info._compresslevel = 1
                checksum, byte_count = hashlib.sha256(), 0
                with bundle.open(info, 'w', force_zip64=True) as target, path.open('rb') as source:
                    for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                        target.write(chunk)
                        checksum.update(chunk)
                        byte_count += len(chunk)
                if byte_count != expected[name]['bytes'] or checksum.hexdigest() != expected[name]['sha256']:
                    raise ValueError('STAGE_CHANGED_DURING_ARCHIVE:' + name)
        output.flush()
    finally:
        if own:
            raw.close()
    receipt = dict(status='PARTIAL_RUNTIME_TRANSPORT' if runtime_only else 'COMPLETE',
                   bytes=output.count, sha256=output.hash.hexdigest(),
                   cap_bytes=cap, compression='stored safetensors; deflate level1 all other files',
                   runtime_only=runtime_only,
                   model_assembly='Requires original MODEL_MANIFEST.json assets at model/<revision>' if runtime_only else 'COMPLETE',
                   source_manifest_sha256=frozen_manifest_sha256)
    if report is not None:
        write_json(report, receipt)
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    actions = parser.add_subparsers(dest='action', required=True)
    pre = actions.add_parser('prepare')
    for name in ('repo', 'stage', 'asset-manifest'):
        pre.add_argument('--' + name, type=Path, required=True)
    pre.add_argument('--model-dir', type=Path)
    pre.add_argument('--runtime-only', action='store_true',
                     help='Freeze only runtime using pinned expected metadata; no local model byte validation')
    for action in ('verify', 'smoke', 'zip'):
        current = actions.add_parser(action)
        current.add_argument('--stage', type=Path, required=True)
        if action == 'zip':
            current.add_argument('--destination', required=True)
            current.add_argument('--report', type=Path)
            current.add_argument('--runtime-only', action='store_true',
                                 help='Export runtime and final manifest; join verified weights locally before full archive')
    args = parser.parse_args(argv)
    if args.action == 'prepare':
        result = prepare(args.repo, args.stage, args.model_dir, args.asset_manifest, runtime_only=args.runtime_only)
        result = dict(status='PREPARED', files=len(result['files']),
                      bytes=sum(row['bytes'] for row in result['files'].values()), source_sha=result['source_sha'],
                      model_mode=result['model_mode'])
    elif args.action == 'verify':
        result = dict(status='VERIFIED', files=len(verify_stage(args.stage)['files']))
    elif args.action == 'smoke':
        result = smoke(args.stage)
    else:
        result = archive(args.stage, args.destination, report=args.report, runtime_only=args.runtime_only)
    print(json.dumps(result), file=sys.stderr if args.action == 'zip' and args.destination == '-' else sys.stdout)


if __name__ == '__main__':
    main()
