"""Rebuild a weight-free Linux CUDA runtime on an ordinary CPU Docker host.

The compiler targets A100 SM80 explicitly: no GPU/SSH/model download is used.
Runtime provenance is distinct from the previous server binary. GPU inference
is NOT_EXECUTED until a real GPU evaluates the assembled archive.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import importlib.metadata as md
import importlib.util
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import struct
import subprocess
import sys
import sysconfig
import tarfile
import tempfile

LLAMA_REVISION = 'f498f864fbc0472004ee1c3616c1188c68eb157f'
CUDA_EULA = dict(
    relative_path='submission/licenses/NVIDIA_CUDA_12.8.1_EULA.pdf',
    source_url='https://docs.nvidia.com/cuda/archive/12.8.1/pdf/EULA.pdf',
    bytes=228502,
    sha256='94736434ff4409100167951f4a76c0a6ab9ba98cf75b41bb74fae53610d9940b')
MODEL_REFERENCE = dict(
    filename='Qwen3.8-27B-Q8_0.gguf', bytes=28595763648,
    sha256='aab65c67ef0dad127960efef9247f1832bca105faa1c7a052cc039b223cf86a1',
    repository='ggml-org/Qwen3.8-27B-GGUF',
    revision='71bc7b627595dc8a91039addd9c791ae548d6747')
ROOT = Path(__file__).resolve().parents[1]
NVIDIA_DRIVER = re.compile(r'^(?:libcuda\.so(?:\..*)?|libnvidia[^/]*\.so(?:\..*)?)$')
EXECUTABLES = {'runtime/llama/llama-server', 'runtime/python/bin/python3.12',
               'runtime/lib/ld-linux-x86-64.so.2'}


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def verify_cuda_notice(repo):
    """Fail before compilation if the pinned official notice is unavailable."""
    path = Path(repo) / CUDA_EULA['relative_path']
    if path.is_symlink() or not path.is_file():
        raise RuntimeError('PINNED_CUDA_NOTICE_MISSING')
    if path.stat().st_size != CUDA_EULA['bytes'] or digest(path) != CUDA_EULA['sha256']:
        raise RuntimeError('PINNED_CUDA_NOTICE_CHANGED')
    with path.open('rb') as source:
        if source.read(5) != b'%PDF-':
            raise RuntimeError('OFFICIAL_CUDA_NOTICE_PDF_REQUIRED')
    return path


def command(args, **kwargs):
    return subprocess.run(list(map(str, args)), check=True, text=True, **kwargs)


def output(args):
    return command(args, stdout=subprocess.PIPE, stderr=subprocess.STDOUT).stdout.strip()


def source_files(stage):
    for path in sorted(Path(stage).rglob('*')):
        if '__pycache__' in path.parts or path.suffix == '.pyc':
            continue
        if path.is_symlink():
            raise ValueError('RUNTIME_SYMLINK_FORBIDDEN: ' + str(path))
        if path.is_file() and path != Path(stage) / 'MANIFEST.json':
            yield path


def inventory(stage):
    return {path.relative_to(stage).as_posix(): dict(bytes=path.stat().st_size, sha256=digest(path))
            for path in source_files(stage)}


def verify(stage):
    stage = Path(stage)
    manifest = json.loads((stage / 'MANIFEST.json').read_text(encoding='utf-8'))
    if manifest.get('version') != 'guardian-qwen-runtime-rebuild-1' or manifest.get('runtime_only') is not True:
        raise ValueError('RUNTIME_ONLY_MANIFEST_REQUIRED')
    if manifest.get('model_reference') != MODEL_REFERENCE:
        raise ValueError('MODEL_REFERENCE_CHANGED')
    if (stage / 'model').exists():
        raise ValueError('RUNTIME_BUNDLE_MUST_NOT_CONTAIN_MODEL_OR_FIXTURE')
    if manifest['files'] != inventory(stage):
        raise ValueError('RUNTIME_CONTENT_OR_FILE_SET_CHANGED')
    for name in EXECUTABLES:
        if name not in manifest['files']:
            raise ValueError('MISSING_NATIVE_EXECUTABLE: ' + name)
        if os.name == 'posix' and not os.access(stage / name, os.X_OK):
            raise ValueError('NATIVE_EXECUTABLE_PERMISSION_MISSING: ' + name)
        with (stage / name).open('rb') as native:
            header = native.read(20)
        if len(header) != 20 or header[:6] != b'\x7fELF\x02\x01' or struct.unpack('<H', header[18:20])[0] != 62:
            raise ValueError('LINUX_X86_64_ELF_EXECUTABLE_REQUIRED: ' + name)
    for name in manifest['files']:
        if NVIDIA_DRIVER.fullmatch(Path(name).name) or '/stubs/' in name:
            raise ValueError('HOST_NVIDIA_DRIVER_OR_STUB_MUST_NOT_BE_BUNDLED')
    return manifest


def copy_file(source, destination):
    destination = Path(destination)
    destination.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(Path(source).resolve(), destination)


def builder_module(repo):
    spec = importlib.util.spec_from_file_location('submission_builder', Path(repo) / 'scripts/build_qwen_submission.py')
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def collect_sources(repo, stage):
    builder = builder_module(repo)
    shutil.copytree(repo / 'src', stage / 'src', ignore=shutil.ignore_patterns('__pycache__', '*.pyc'))
    for relative in builder.EXPERIMENTS:
        source = repo / 'experiments' / relative
        if not source.is_file():
            raise ValueError('MISSING_RUNTIME_SOURCE: ' + relative)
        copy_file(source, stage / 'experiments' / relative)
    (stage / 'experiments/__init__.py').touch(exist_ok=True)
    for source, destination in [('submission/predict.py', 'scripts/predict.py'),
                                ('submission/Dockerfile', 'Dockerfile'),
                                ('submission/pyproject.toml', 'pyproject.toml'),
                                ('submission/build_backend.py', 'build_backend.py'),
                                ('docs/qwen_submission_20261008/RUNBOOK.md', 'README.md')]:
        copy_file(repo / source, stage / destination)
    shutil.copytree(repo / 'submission/licenses', stage / 'licenses')
    (stage / '.dockerignore').write_text('__pycache__\n*.pyc\n', encoding='utf-8')


def collect_python(repo, stage):
    builder = builder_module(repo)
    python = Path(sys._base_executable).resolve()
    copy_file(python, stage / 'runtime/python/bin/python3.12')
    shutil.copytree(Path(sysconfig.get_path('stdlib')), stage / 'runtime/python/lib/python3.12',
                    ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'site-packages', 'dist-packages', 'test', 'tests'))
    installed = {}
    for name in builder.DISTRIBUTIONS:
        dist = md.distribution(name)  # Every pinned runtime dependency is required.
        installed[dist.metadata['Name']] = dist.version
        base = Path(dist.locate_file('')).resolve()
        for item in dist.files or []:
            source = Path(dist.locate_file(item)).resolve()
            if not source.is_file() or '__pycache__' in source.parts or source.suffix == '.pyc':
                continue
            if not source.is_relative_to(base):
                continue
            copy_file(source, stage / 'runtime/site-packages' / source.relative_to(base))
    return python, installed


def ldd_missing(text):
    return re.findall(r'^\s*(\S+)\s+=>\s+not found\s*$', text, re.MULTILINE)


def collect_libraries(stage, python):
    library_dir = stage / 'runtime/lib'
    library_dir.mkdir(parents=True)
    queue = [python, *(stage / 'runtime/llama').iterdir(),
             *(stage / 'runtime/python/lib/python3.12/lib-dynload').glob('*.so'),
             *(stage / 'runtime/site-packages').rglob('*.so')]
    visited, host_driver_gaps = set(), set()
    env = dict(os.environ, LD_LIBRARY_PATH=os.pathsep.join([
        str(library_dir), str(stage / 'runtime/llama'),
        '/usr/local/cuda/lib64', '/usr/local/cuda/targets/x86_64-linux/lib']))
    while queue:
        path = queue.pop()
        if str(path) in visited:
            continue
        visited.add(str(path))
        completed = subprocess.run(['ldd', str(path)], env=env, text=True, capture_output=True)
        text = completed.stdout + completed.stderr
        for name in ldd_missing(text):
            if NVIDIA_DRIVER.fullmatch(name):
                host_driver_gaps.add(name)
            else:
                raise RuntimeError('UNRESOLVED_USERSPACE_LIBRARY: ' + name + ' needed by ' + str(path))
        # ldd status1 is normal for a non-dynamic file; other errors are real.
        if completed.returncode and 'not a dynamic executable' not in text and not ldd_missing(text):
            raise RuntimeError('LDD_FAILED: ' + str(path) + ': ' + text)
        for name in re.findall(r'(?:=>\s*)?(/[^\s()]+)', completed.stdout):
            source = Path(name)
            if not source.is_file():
                continue
            if NVIDIA_DRIVER.fullmatch(source.name) or 'stubs' in source.parts:
                if not NVIDIA_DRIVER.fullmatch(source.name):
                    raise RuntimeError('STUB_USERSPACE_LIBRARY_FORBIDDEN: ' + str(source))
                continue
            if source.is_relative_to(stage):
                continue
            target = library_dir / source.name
            if target.exists():
                if digest(target) != digest(source):
                    raise RuntimeError('NATIVE_LIBRARY_COLLISION: ' + source.name)
                continue
            copy_file(source, target)
            queue.append(source.resolve())
    return sorted(host_driver_gaps)


def prepare_cuda_driver_link(stage, llama_source, toolkit=Path('/usr/local/cuda')):
    """Expose the toolkit driver's SONAME to the linker, outside the archive.

    CUDA's libcuda.so is a link-only stub whose ELF SONAME is libcuda.so.1.
    GNU ld resolving dependencies of libggml-cuda needs that SONAME as a file.
    -rpath-link searches only during linking; it does not add a runtime search
    path or replace the real driver furnished by the target GPU host.
    """
    stage, llama_source, toolkit = map(lambda p: Path(p).resolve(), (stage, llama_source, toolkit))
    link_dir = llama_source.parent / 'cuda-driver-link'
    if link_dir.is_relative_to(stage) or link_dir.exists():
        raise ValueError('CUDA_DRIVER_LINK_DIR_MUST_BE_FRESH_AND_OUTSIDE_RUNTIME')
    candidates = [toolkit / 'targets/x86_64-linux/lib/stubs/libcuda.so',
                  toolkit / 'lib64/stubs/libcuda.so']
    stub = next((p.resolve() for p in candidates if p.is_file()), None)
    if stub is None or 'stubs' not in stub.parts:
        raise RuntimeError('CUDA_TOOLKIT_LINK_ONLY_DRIVER_STUB_REQUIRED')
    soname = output(['readelf', '-d', stub])
    if not re.search(r'\(SONAME\).*\[libcuda\.so\.1\]', soname):
        raise RuntimeError('CUDA_DRIVER_STUB_SONAME_MISMATCH')
    link_dir.mkdir()
    (link_dir / 'libcuda.so.1').symlink_to(stub)
    return link_dir, dict(scope='link-only; never shipped or used for runtime execution',
                          stub_sha256=digest(stub), stub_soname='libcuda.so.1',
                          linker_flag='-Wl,-rpath-link,' + str(link_dir),
                          runtime_driver='supplied by GPU host; NOT_BUNDLED', VMM='UNCHANGED')


def check_native_version(stage, output_dir, environment):
    """Run the packaged engine if loadable; a missing real GPU driver is explicit."""
    library_path = str(stage / 'runtime/llama') + os.pathsep + str(stage / 'runtime/lib')
    command_line = [str(stage / 'runtime/lib/ld-linux-x86-64.so.2'), '--library-path',
                    library_path, str(stage / 'runtime/llama/llama-server'), '--version']
    result = subprocess.run(command_line, env=dict(environment, LD_LIBRARY_PATH=library_path),
                            text=True, capture_output=True, timeout=180)
    text = result.stdout + result.stderr
    (output_dir / 'rebuilt_llama_version.log').write_text(text, encoding='utf-8')
    if result.returncode:
        # A GPU-free builder intentionally contains no real NVIDIA host driver.
        # Only an exact loader failure for that omitted dependency is skippable;
        # unresolved userspace libraries, symbols, crashes and other errors fail.
        missing = re.search(r'error while loading shared libraries: (\S+): cannot open shared object file: '
                            r'No such file or directory', text)
        if missing and NVIDIA_DRIVER.fullmatch(missing.group(1)):
            return None, dict(status='NOT_EXECUTED_MISSING_HOST_DRIVER',
                              missing_dependency=missing.group(1), loader_exit_code=result.returncode,
                              link_only_stub_used_for_execution=False)
        print(text, file=sys.stderr, flush=True)
        raise RuntimeError('CPU_RUNTIME_SMOKE_FAILED: rebuilt_llama_version')
    if LLAMA_REVISION[:7] not in text:
        raise RuntimeError('REBUILT_LLAMA_VERSION_REVISION_MISMATCH')
    return text.strip(), dict(status='CPU_VERSION_EXECUTED_NO_GPU_INFERENCE',
                             loader_exit_code=0, link_only_stub_used_for_execution=False)


def check_built_runtime_rpaths(native):
    """No developer toolkit/stub directory may become runtime loader authority."""
    result = {}
    for path in sorted(Path(native).iterdir()):
        if not path.is_file():
            continue
        dynamic = output(['readelf', '-d', path])
        paths = re.findall(r'\((?:RPATH|RUNPATH)\).*\[([^\]]*)\]', dynamic)
        for group in paths:
            if any(entry not in {'$ORIGIN', '${ORIGIN}'} for entry in group.split(':') if entry):
                raise RuntimeError('BUILT_RUNTIME_UNAPPROVED_RPATH: ' + path.name + ': ' + group)
        result[path.name] = paths
    return result


def build(repo, stage, llama_source, jobs, image_identity):
    repo, stage, llama_source = map(lambda p: Path(p).resolve(), (repo, stage, llama_source))
    if sys.platform != 'linux' or sys.version_info[:2] != (3, 12) or os.uname().machine != 'x86_64':
        raise RuntimeError('REBUILD_REQUIRES_LINUX_X86_64_CPYTHON312')
    if stage.exists() or llama_source.exists():
        raise ValueError('REBUILD_REQUIRES_FRESH_STAGE_AND_LLAMA_SOURCE')
    if jobs < 1 or jobs > 4:
        raise ValueError('BUILD_JOBS_MUST_BE_1_TO_4')
    cuda_notice = verify_cuda_notice(repo)
    # The read-only CI checkout belongs to the host runner UID, while the build
    # container runs as root. Trust only this exact supplied checkout, per call;
    # do not modify global Git settings or permit every directory.
    source_commit = output(['git', '-c', 'safe.directory=' + str(repo), '-C', repo, 'rev-parse', 'HEAD'])
    # Partial checkout keeps the source transfer small while pinning the exact commit.
    command(['git', 'clone', '--filter=blob:none', '--no-checkout', 'https://github.com/ggml-org/llama.cpp.git', llama_source])
    command(['git', '-C', llama_source, 'checkout', '--detach', LLAMA_REVISION])
    if output(['git', '-C', llama_source, 'rev-parse', 'HEAD']) != LLAMA_REVISION:
        raise ValueError('LLAMA_SOURCE_REVISION_MISMATCH')
    driver_link_dir, driver_link_info = prepare_cuda_driver_link(stage, llama_source)
    cmake_flags = ['-DCMAKE_BUILD_TYPE=Release', '-DGGML_CUDA=ON', '-DGGML_NATIVE=OFF',
                   '-DCMAKE_CUDA_ARCHITECTURES=80', '-DLLAMA_OPENSSL=OFF',
                   '-DLLAMA_BUILD_TESTS=OFF', '-DLLAMA_BUILD_EXAMPLES=OFF', '-DLLAMA_BUILD_SERVER=ON',
                   '-DCMAKE_BUILD_RPATH_USE_ORIGIN=ON',
                   '-DCMAKE_BUILD_WITH_INSTALL_RPATH=ON', '-DCMAKE_INSTALL_RPATH=$ORIGIN',
                   '-DCMAKE_EXE_LINKER_FLAGS=-Wl,-rpath-link,' + str(driver_link_dir)]
    build_dir = llama_source / 'build'
    command(['cmake', '-S', llama_source, '-B', build_dir, *cmake_flags])
    command(['cmake', '--build', build_dir, '--target', 'llama-server', '--parallel', str(jobs)])
    # Preserve the expensive completed engine if a later packaging gate fails.
    # This snapshot is explicitly incomplete and is never a ready runtime.
    engine_snapshot = dict(status='COMPILED_ENGINE_ONLY_NOT_SUBMITTABLE',
                           source_commit=source_commit, llama_revision=LLAMA_REVISION,
                           image_identity=image_identity, cmake_flags=cmake_flags,
                           files={p.name: dict(bytes=p.stat().st_size, sha256=digest(p))
                                  for p in sorted((build_dir / 'bin').iterdir()) if p.is_file()})
    (llama_source.parent / 'ENGINE_COMPILE_RECEIPT.json').write_text(
        json.dumps(engine_snapshot, indent=2, sort_keys=True), encoding='utf-8')
    stage.mkdir(parents=True)
    collect_sources(repo, stage)
    native = stage / 'runtime/llama'
    copy_file(build_dir / 'bin/llama-server', native / 'llama-server')
    for library in (build_dir / 'bin').glob('*.so*'):
        if library.is_file():
            copy_file(library, native / library.name)
    native_rpaths = check_built_runtime_rpaths(native)
    python, distributions = collect_python(repo, stage)
    gaps = collect_libraries(stage, python)
    for name in EXECUTABLES:
        (stage / name).chmod(0o755)
    copy_file(repo / 'submission/requirements-runtime.txt', stage / 'licenses/PYTHON_RUNTIME_REQUIREMENTS.txt')
    # Include vendor/system legal notices; package .dist-info licences were copied above.
    # collect_sources already copied this exact repository-owned official PDF.
    if digest(stage / 'licenses' / cuda_notice.name) != CUDA_EULA['sha256']:
        raise RuntimeError('STAGED_CUDA_NOTICE_CHANGED')
    doc_root = Path('/usr/share/doc')
    for notice in sorted(doc_root.glob('*/copyright')):
        if notice.is_file():
            copy_file(notice, stage / 'licenses/system-packages' / notice.relative_to(doc_root))
    # Retain toolchain evidence without the source or CUDA developer toolkit.
    cuda_binary = native / 'libggml-cuda.so'
    if not cuda_binary.is_file():
        raise RuntimeError('CUDA_BACKEND_LIBRARY_MISSING')
    embedded_architectures = sorted(set(re.findall(r'\.sm_(\d+)\.', output(['cuobjdump', '--list-elf', cuda_binary]))))
    if embedded_architectures != ['80']:
        raise RuntimeError('CUDA_BINARY_ARCHITECTURES_MISMATCH: ' + repr(embedded_architectures))
    build_info = dict(source_commit=source_commit, llama_revision=LLAMA_REVISION,
                      image_identity=image_identity, cuda_architectures=['80'], cmake_flags=cmake_flags,
                      cuda_driver_link=driver_link_info,
                      built_native_rpaths=native_rpaths,
                      cuda_notice=CUDA_EULA,
                      cuda_binary_architectures=embedded_architectures,
                      c_compiler=output(['gcc', '--version']), cxx_compiler=output(['g++', '--version']),
                      cmake=output(['cmake', '--version']), nvcc=output(['nvcc', '--version']),
                      python=sys.version, dpkg_packages=output(['dpkg-query', '-W']),
                      build_time_utc=datetime.now(timezone.utc).isoformat(),
                      GPU_INFERENCE='NOT_EXECUTED', prior_server_binary_identity='NOT_REPRODUCED')
    (stage / 'BUILD_PROVENANCE.json').write_text(json.dumps(build_info, indent=2, sort_keys=True), encoding='utf-8')
    manifest = dict(version='guardian-qwen-runtime-rebuild-1', runtime_only=True, commit=source_commit,
                    profile='B2', model_reference=MODEL_REFERENCE, distributions=distributions,
                    host_driver_dependencies=gaps, build=build_info, files=inventory(stage))
    (stage / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    verify(stage)
    print(json.dumps(dict(stage=str(stage), runtime_only=True, bytes=sum(v['bytes'] for v in manifest['files'].values()),
                          GPU_INFERENCE='NOT_EXECUTED')), flush=True)


def archive(stage, destination):
    stage, destination = Path(stage), Path(destination)
    manifest = verify(stage)
    if destination.exists():
        raise ValueError('RUNTIME_ARCHIVE_ALREADY_EXISTS')
    destination.parent.mkdir(parents=True, exist_ok=True)
    # No wrapper directory; all permissions survive Linux extraction.
    with destination.open('xb') as raw:
        with tarfile.open(fileobj=raw, mode='w:gz', compresslevel=1) as tar:
            for path in sorted(stage.rglob('*')):
                if '__pycache__' in path.parts or path.suffix == '.pyc':
                    continue
                info = tar.gettarinfo(str(path), arcname=path.relative_to(stage).as_posix())
                info.uid = info.gid = 0
                info.uname = info.gname = ''
                info.mode = 0o755 if path.is_dir() or info.name in EXECUTABLES else 0o644
                if path.is_file():
                    with path.open('rb') as source:
                        tar.addfile(info, source)
                else:
                    tar.addfile(info)
    checksum = digest(destination)
    destination.with_suffix(destination.suffix + '.sha256').write_text(checksum + '  ' + destination.name + '\n', encoding='utf-8')
    print(json.dumps(dict(archive=str(destination), bytes=destination.stat().st_size, sha256=checksum,
                          runtime_only=manifest['runtime_only'])), flush=True)


def smoke(stage, output_dir):
    """Exercise the real bundled CPython and offline platform entry point on CPU."""
    stage, output_dir = Path(stage).resolve(), Path(output_dir).resolve()
    manifest = verify(stage)
    output_dir.mkdir(parents=True, exist_ok=False)
    env = dict(os.environ, PYTHONUTF8='1', PYTHONDONTWRITEBYTECODE='1', PIP_NO_INDEX='1', PIP_NO_CACHE_DIR='1')
    logs = {}

    def run(name, args, environment=env):
        result = subprocess.run(list(map(str, args)), env=environment, text=True, capture_output=True, timeout=180)
        (output_dir / (name + '.log')).write_text(result.stdout + result.stderr, encoding='utf-8')
        logs[name] = result.returncode
        if result.returncode:
            print(result.stdout + result.stderr, file=sys.stderr, flush=True)
            raise RuntimeError('CPU_RUNTIME_SMOKE_FAILED: ' + name)

    run('offline_pip_install', [sys.executable, '-m', 'pip', 'install', '--no-index', '--no-deps',
                               '--target', output_dir / 'installed', stage])
    source = output_dir / 'empty.csv'
    source.write_text('id,prompt,response\n', encoding='utf-8')
    prediction = output_dir / 'predictions.parquet'
    run('public_empty_entrypoint', [sys.executable, stage / 'scripts/predict.py', '--input', source, '--output', prediction])
    native_env = dict(env, PYTHONHOME=str(stage / 'runtime/python'), GUARDIAN_BUNDLED_PYTHON='1',
                      LD_LIBRARY_PATH=str(stage / 'runtime/lib'))
    code = ('import sys; from pathlib import Path; p=Path(sys.argv[1]); '
            'sys.path[:0]=[str(p/"src"),str(p),str(p/"runtime/site-packages")]; '
            'import pandas, pyarrow, pydantic, jsonschema; '
            'from guardian_truth.repair.v5 import run_v5; '
            'from guardian_truth.v6fix.pipeline import Layers; '
            'from experiments.guardian_addons.variants2 import Hook2; '
            'f=pandas.read_parquet(sys.argv[2]); '
            'assert list(f.columns)==["id","label"] and len(f)==0 and str(f.label.dtype)=="int64"; '
            'print("BUNDLED_NATIVE_IMPORTS_AND_PARQUET_OK",sys.version)')
    run('bundled_native_imports', [stage / 'runtime/lib/ld-linux-x86-64.so.2', '--library-path',
                                 stage / 'runtime/lib', stage / 'runtime/python/bin/python3.12',
                                 '-X', 'utf8', '-c', code, stage, prediction], native_env)
    llama_version, version_check = check_native_version(stage, output_dir, native_env)
    if prediction.read_bytes()[:4] != b'PAR1':
        raise RuntimeError('DEFAULT_OUTPUT_NOT_PARQUET')
    report = dict(scope='CPU-only rebuilt native runtime and offline platform entrypoint',
                  runtime_manifest_sha256=digest(stage / 'MANIFEST.json'),
                  model_present=False, inference_calls=0, GPU_INFERENCE='NOT_EXECUTED', logs=logs,
                  source_commit=manifest['commit'], llama_revision=manifest['build']['llama_revision'],
                  rebuilt_llama_version=llama_version, native_version_check=version_check)
    (output_dir / 'report.json').write_text(json.dumps(report, indent=2), encoding='utf-8')
    print(json.dumps(report), flush=True)


def extract(archive_path, destination, expected_sha256):
    """Checked cross-platform extraction: never permit links, traversal or ADS."""
    archive_path, destination = Path(archive_path).resolve(), Path(destination).resolve()
    if not re.fullmatch('[0-9a-f]{64}', expected_sha256) or digest(archive_path) != expected_sha256:
        raise ValueError('RUNTIME_ARCHIVE_SHA256_MISMATCH')
    if destination.exists():
        raise ValueError('RUNTIME_EXTRACTION_DESTINATION_ALREADY_EXISTS')
    destination.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=destination.name + '.partial-', dir=destination.parent)).resolve()
    try:
        total, seen = 0, set()
        with tarfile.open(archive_path, mode='r:gz') as tar:
            for member in tar:
                path = PurePosixPath(member.name)
                if (path.is_absolute() or not path.parts or '..' in path.parts or '\\' in member.name
                        or ':' in member.name or member.name in seen or not (member.isfile() or member.isdir())):
                    raise ValueError('UNSAFE_OR_DUPLICATE_RUNTIME_ARCHIVE_ENTRY: ' + member.name)
                seen.add(member.name)
                total += member.size
                if total > 4_000_000_000 or len(seen) > 100_000:
                    raise ValueError('RUNTIME_ARCHIVE_EXTRACTION_BOUND_EXCEEDED')
                target = temporary.joinpath(*path.parts)
                if not target.resolve().is_relative_to(temporary):
                    raise ValueError('RUNTIME_ARCHIVE_PATH_ESCAPES_DESTINATION')
                if member.isdir():
                    target.mkdir(parents=True, exist_ok=True)
                    target.chmod(0o755)
                else:
                    target.parent.mkdir(parents=True, exist_ok=True)
                    source = tar.extractfile(member)
                    with source, target.open('xb') as stream:
                        shutil.copyfileobj(source, stream, 8 * 1024 * 1024)
                    if target.stat().st_size != member.size:
                        raise ValueError('TRUNCATED_RUNTIME_ARCHIVE_ENTRY: ' + member.name)
                    target.chmod(0o755 if member.name in EXECUTABLES else 0o644)
        verify(temporary)
        os.replace(temporary, destination)
    except BaseException:
        # Only remove the fresh directory allocated above; never a supplied path.
        if temporary.exists() and temporary.parent == destination.parent:
            shutil.rmtree(temporary)
        raise
    print(json.dumps(dict(stage=str(destination), runtime_only=True, archive_sha256=expected_sha256,
                          verified=True)), flush=True)


def assemble(runtime, model, destination):
    runtime, model, destination = map(lambda p: Path(p).resolve(), (runtime, model, destination))
    previous = verify(runtime)
    if destination.exists():
        raise ValueError('ASSEMBLY_STAGE_ALREADY_EXISTS')
    if destination.is_relative_to(runtime):
        raise ValueError('ASSEMBLY_DESTINATION_MUST_NOT_BE_INSIDE_RUNTIME')
    if model.is_symlink() or not model.is_file() or model.stat().st_size != MODEL_REFERENCE['bytes']:
        raise ValueError('COMPLETE_ORIGINAL_MODEL_FILE_REQUIRED')
    if digest(model) != MODEL_REFERENCE['sha256']:
        raise ValueError('ORIGINAL_MODEL_SHA256_MISMATCH')
    shutil.copytree(runtime, destination, ignore=shutil.ignore_patterns('__pycache__', '*.pyc', 'MANIFEST.json'))
    (destination / 'model').mkdir()
    target = destination / 'model' / MODEL_REFERENCE['filename']
    try:
        os.link(model, target)
    except OSError:
        # Explicit error instead of silently allocating a second 28.6GB copy.
        raise RuntimeError('ASSEMBLY_MODEL_AND_STAGE_MUST_SHARE_FILESYSTEM_FOR_HARDLINK')
    (destination / 'RUNTIME_MANIFEST.json').write_text(json.dumps(previous, indent=2, sort_keys=True), encoding='utf-8')
    files = inventory(destination)
    del files['model/' + MODEL_REFERENCE['filename']]
    manifest = dict(version='guardian-qwen-offline-1', runtime_only=False, commit=previous['commit'], profile='B2',
                    model_sha256=MODEL_REFERENCE['sha256'], model_bytes=MODEL_REFERENCE['bytes'],
                    model_reference=MODEL_REFERENCE, runtime_build=previous['build'],
                    python=previous['build']['python'], distributions=previous['distributions'], files=files)
    (destination / 'MANIFEST.json').write_text(json.dumps(manifest, indent=2, sort_keys=True), encoding='utf-8')
    print(json.dumps(dict(stage=str(destination), runtime_only=False, model_sha256=manifest['model_sha256'],
                          GPU_INFERENCE='NOT_EXECUTED_FOR_REBUILT_BINARY')), flush=True)


def main():
    parser = argparse.ArgumentParser()
    sub = parser.add_subparsers(dest='command', required=True)
    preflight_parser = sub.add_parser('preflight')
    preflight_parser.add_argument('--repo', type=Path, default=ROOT)
    build_parser = sub.add_parser('build')
    build_parser.add_argument('--repo', type=Path, default=ROOT)
    build_parser.add_argument('--stage', type=Path, required=True)
    build_parser.add_argument('--llama-source', type=Path, required=True)
    build_parser.add_argument('--jobs', type=int, default=2)
    build_parser.add_argument('--image-identity', required=True)
    verify_parser = sub.add_parser('verify')
    verify_parser.add_argument('--stage', type=Path, required=True)
    zip_parser = sub.add_parser('archive')
    zip_parser.add_argument('--stage', type=Path, required=True)
    zip_parser.add_argument('--destination', type=Path, required=True)
    smoke_parser = sub.add_parser('smoke')
    smoke_parser.add_argument('--stage', type=Path, required=True)
    smoke_parser.add_argument('--output-dir', type=Path, required=True)
    assemble_parser = sub.add_parser('assemble')
    assemble_parser.add_argument('--runtime', type=Path, required=True)
    assemble_parser.add_argument('--model', type=Path, required=True)
    assemble_parser.add_argument('--destination', type=Path, required=True)
    extract_parser = sub.add_parser('extract')
    extract_parser.add_argument('--archive', type=Path, required=True)
    extract_parser.add_argument('--destination', type=Path, required=True)
    extract_parser.add_argument('--expected-sha256', required=True)
    args = parser.parse_args()
    if args.command == 'preflight':
        verify_cuda_notice(args.repo)
        print(json.dumps(dict(status='PINNED_CUDA_NOTICE_VERIFIED', **CUDA_EULA)), flush=True)
    elif args.command == 'build':
        build(args.repo, args.stage, args.llama_source, args.jobs, args.image_identity)
    elif args.command == 'verify':
        manifest = verify(args.stage)
        print(json.dumps(dict(runtime_only=True, files=len(manifest['files']),
                              manifest_sha256=digest(args.stage / 'MANIFEST.json'))), flush=True)
    elif args.command == 'archive':
        archive(args.stage, args.destination)
    elif args.command == 'smoke':
        smoke(args.stage, args.output_dir)
    elif args.command == 'extract':
        extract(args.archive, args.destination, args.expected_sha256)
    else:
        assemble(args.runtime, args.model, args.destination)


if __name__ == '__main__':
    main()
