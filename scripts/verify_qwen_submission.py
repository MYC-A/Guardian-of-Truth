"""Strict final ZIP acceptance for the pinned offline Qwen B2 submission.

Packaging validation is distinct from model/GPU inference. This operator script
does not contact the server, execute bundled code, or manufacture a quality score.
"""
from __future__ import annotations

import argparse
import hashlib
import importlib.util
import json
from pathlib import Path, PurePosixPath
import re
import struct
import zipfile


ROOT = Path(__file__).resolve().parents[1]


def _module(name, filename):
    spec = importlib.util.spec_from_file_location(name, ROOT / 'scripts' / filename)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


runtime = _module('submission_runtime_reference', 'rebuild_qwen_runtime.py')
archive_reader = _module('submission_archive_reader', 'download_qwen_submission.py')
MODEL_REFERENCE = dict(runtime.MODEL_REFERENCE)
MAX_ARCHIVE_BYTES = 40_000_000_000
ROOT_DIRECTORIES = {'model', 'runtime', 'src', 'scripts', 'experiments', 'licenses'}
ROOT_FILES = {'MANIFEST.json', 'RUNTIME_MANIFEST.json', 'BUILD_PROVENANCE.json',
              'Dockerfile', 'README.md', 'pyproject.toml', 'build_backend.py', '.dockerignore'}
SECRET_NAMES = {'id_rsa', 'id_ed25519', 'id_ecdsa', 'credentials', 'credentials.json',
                'api_keys.json', 'api_keys.env', 'mistral.env', '.netrc', '.git-credentials'}
KEY_MARKERS = (b'-----BEGIN PRIVATE KEY-----', b'-----BEGIN RSA PRIVATE KEY-----',
               b'-----BEGIN EC PRIVATE KEY-----', b'-----BEGIN OPENSSH PRIVATE KEY-----')
LITERAL_SECRET = re.compile(rb'(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key|password)'
                            rb'\s*[\"\']?\s*[:=]\s*[\"\']([^\"\'\r\n]{12,})[\"\']')
VENDOR_REGISTRY = ROOT / 'docs/qwen_submission_20261008/PINNED_VENDOR_FILES.json'


def load_vendor_registry():
    registry = json.loads(VENDOR_REGISTRY.read_text(encoding='utf-8'))
    requirements = ROOT / 'submission/requirements-runtime.txt'
    if (registry.get('version') != 'guardian-official-vendor-wheel-registry-1'
            or registry.get('coverage') != 'ALL_PINNED_DISTRIBUTIONS'
            or registry.get('requirements_sha256') != sha256(requirements)):
        raise ValueError('COMPLETE_PINNED_VENDOR_PROVENANCE_REGISTRY_REQUIRED')
    return registry


def authenticated_vendor_files(archive, registry):
    """Public vendor docs/fixtures are admitted only as exact official bytes.

    The registry belongs to the operator's reviewed repository, not to the ZIP's
    self-reported manifest. A changed/unregistered vendor module is rejected,
    even when no credential heuristic fires. No library-name exception exists.
    """
    trusted = set()
    dist_info = {name.split('/')[2] for name in registry['files']
                 if len(name.split('/')) > 3 and name.split('/')[2].endswith('.dist-info')}
    for entry in archive.infolist():
        if entry.is_dir() or not entry.filename.startswith('runtime/site-packages/'):
            continue
        expected = registry['files'].get(entry.filename)
        if expected is None:
            pieces = PurePosixPath(entry.filename).parts
            generated = (len(pieces) == 4 and pieces[2] in dist_info
                         and pieces[3] in {'RECORD', 'INSTALLER', 'REQUESTED'})
            if not generated:
                raise ValueError('UNREGISTERED_VENDOR_FILE: ' + entry.filename)
            data = archive.read(entry)
            if ((pieces[3] == 'INSTALLER' and data != b'pip\n')
                    or (pieces[3] == 'REQUESTED' and data != b'')
                    or any(marker in data for marker in KEY_MARKERS) or LITERAL_SECRET.search(data)):
                raise ValueError('UNAPPROVED_OR_PRIVATE_INSTALLER_METADATA: ' + entry.filename)
            continue  # Generated metadata receives no public-example exemption.
        if entry.file_size != expected['bytes']:
            raise ValueError('OFFICIAL_VENDOR_FILE_CHANGED: ' + entry.filename)
        value = hashlib.sha256()
        with archive.open(entry) as source:
            for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                value.update(chunk)
        if value.hexdigest() != expected['sha256']:
            raise ValueError('OFFICIAL_VENDOR_FILE_CHANGED: ' + entry.filename)
        trusted.add(entry.filename)
    return trusted


def sha256(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as source:
        for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
            value.update(chunk)
    return value.hexdigest()


def _json(archive, name):
    if archive.getinfo(name).file_size > 10_000_000:
        raise ValueError('OVERSIZED_SUBMISSION_MANIFEST')
    def unique(items):
        result = {}
        for key, value in items:
            if key in result:
                raise ValueError('DUPLICATE_MANIFEST_KEY')
            result[key] = value
        return result
    return json.loads(archive.read(name), object_pairs_hook=unique)


def _entry_scope(name, trusted_vendor=False):
    path = PurePosixPath(name)
    pieces = path.parts
    if (not pieces or path.is_absolute() or '..' in pieces or '\\' in name or ':' in name
            or 'metrics' in pieces):
        raise ValueError('UNSAFE_OR_PROHIBITED_SUBMISSION_PATH: ' + name)
    if pieces[0] not in ROOT_DIRECTORIES and name not in ROOT_FILES:
        raise ValueError('UNAPPROVED_SUBMISSION_ROOT_ENTRY: ' + name)
    if trusted_vendor:
        if pieces[:2] != ('runtime', 'site-packages'):
            raise ValueError('VENDOR_EXEMPTION_OUTSIDE_VENDOR_SOURCE')
        return  # Exact official bytes; benchmark/docs/key examples are public.
    # Source modules may implement caches; this excludes data archives rather
    # than legitimate runtime names such as src/guardian_truth/.../cache.py.
    if pieces[0] == 'model' and name.rstrip('/') not in {'model', 'model/' + MODEL_REFERENCE['filename']}:
        raise ValueError('UNAPPROVED_MODEL_OR_MODEL_CACHE_ENTRY: ' + name)
    if pieces[0] == 'scripts' and name.rstrip('/') not in {'scripts', 'scripts/predict.py'}:
        raise ValueError('OPERATOR_OR_BENCHMARK_SCRIPT_MUST_NOT_BE_SUBMITTED: ' + name)
    if pieces[0] == 'experiments' and name.lower().endswith(('.json', '.jsonl', '.parquet', '.csv', '.gguf')):
        raise ValueError('RESEARCH_DATA_MUST_NOT_BE_SUBMITTED: ' + name)
    if any(p.lower() in {'.git', '__pycache__', 'secrets', 'fixtures', 'outputs', 'benchmarks'} for p in pieces):
        raise ValueError('RESEARCH_CACHE_FIXTURE_OR_SECRET_PATH: ' + name)
    if (path.name.lower() in SECRET_NAMES or path.suffix.lower() in {'.pem', '.key', '.env', '.pyc'}
            or path.name.lower().startswith('.env')):
        raise ValueError('CREDENTIAL_OR_GENERATED_CACHE_FILE: ' + name)


def verify_submission(path, expected_zip_sha256=None):
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError('REGULAR_COMPLETE_SUBMISSION_ZIP_REQUIRED')
    path = path.resolve()
    initial_stat = path.stat()
    size = initial_stat.st_size
    if size <= 0 or size >= MAX_ARCHIVE_BYTES:
        raise ValueError('SUBMISSION_ARCHIVE_MUST_BE_BELOW_40GB')
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_ZIP_ENTRIES')
        registry = load_vendor_registry()
        trusted_vendor = authenticated_vendor_files(archive, registry)
        for entry in archive.infolist():
            if entry.is_dir() and entry.filename.startswith('runtime/site-packages/'):
                # Explicit ZIP directory metadata must correspond to at least
                # one authenticated file; empty unknown directories stay strict.
                vendor = any(name.startswith(entry.filename) for name in trusted_vendor)
            else:
                vendor = entry.filename in trusted_vendor
            _entry_scope(entry.filename, trusted_vendor=vendor)
        manifest = _json(archive, 'MANIFEST.json')
        if manifest.get('fixture_only') or manifest.get('runtime_only') is not False:
            raise ValueError('FULL_REAL_SUBMISSION_NOT_RUNTIME_OR_FIXTURE_REQUIRED')
        if manifest.get('version') != 'guardian-qwen-offline-1' or manifest.get('profile') != 'B2':
            raise ValueError('APPROVED_B2_SUBMISSION_PROFILE_REQUIRED')
        if (manifest.get('model_reference') != MODEL_REFERENCE
                or manifest.get('model_bytes') != MODEL_REFERENCE['bytes']
                or manifest.get('model_sha256') != MODEL_REFERENCE['sha256']):
            raise ValueError('PINNED_ORIGINAL_MODEL_IDENTITY_REQUIRED')
        model_name = 'model/' + MODEL_REFERENCE['filename']
        if archive.getinfo(model_name).file_size != MODEL_REFERENCE['bytes']:
            raise ValueError('COMPLETE_ORIGINAL_MODEL_SIZE_REQUIRED')
        build = manifest.get('runtime_build', {})
        if build.get('llama_revision') != runtime.LLAMA_REVISION:
            raise ValueError('PINNED_LLAMA_SOURCE_REVISION_REQUIRED')
        for name in names:
            if runtime.NVIDIA_DRIVER.fullmatch(PurePosixPath(name).name) or '/stubs/' in name:
                raise ValueError('HOST_NVIDIA_DRIVER_OR_STUB_FORBIDDEN')
        for name in runtime.EXECUTABLES:
            with archive.open(name) as source:
                header = source.read(20)
            if (len(header) != 20 or header[:6] != b'\x7fELF\x02\x01'
                    or struct.unpack('<H', header[18:20])[0] != 62):
                raise ValueError('LINUX_X86_64_NATIVE_EXECUTABLE_REQUIRED: ' + name)
        # Scan text/source/config members only; weights and native binaries are
        # inspected by exact hashes, not by an unreliable binary secret heuristic.
        for entry in archive.infolist():
            if entry.is_dir() or entry.file_size > 10_000_000 or entry.filename in trusted_vendor:
                continue
            if PurePosixPath(entry.filename).suffix.lower() in {'.py', '.json', '.toml', '.txt', '.md'}:
                data = archive.read(entry)
                if any(marker in data for marker in KEY_MARKERS) or LITERAL_SECRET.search(data):
                    raise ValueError('POSSIBLE_LITERAL_CREDENTIAL_MUST_BE_REVIEWED: ' + entry.filename)
    # Includes every model byte, member CRC, UNIX permissions and exact file set.
    archive_reader.verify_archive(path)
    checksum = sha256(path)
    final_stat = path.stat()
    if ((initial_stat.st_dev, initial_stat.st_ino, initial_stat.st_size, initial_stat.st_mtime_ns)
            != (final_stat.st_dev, final_stat.st_ino, final_stat.st_size, final_stat.st_mtime_ns)):
        raise ValueError('SUBMISSION_ARCHIVE_CHANGED_DURING_VERIFICATION')
    if expected_zip_sha256 is not None:
        if not re.fullmatch('[0-9a-f]{64}', expected_zip_sha256) or checksum != expected_zip_sha256:
            raise ValueError('EXPECTED_SUBMISSION_ZIP_SHA256_MISMATCH')
    return dict(version='guardian-qwen-final-packaging-verification-1',
                phase='server_independent_runtime_packaging',
                status='VERIFIED_OFFLINE_PACKAGING', path=str(path), bytes=size,
                zip_sha256=checksum, model_reference=MODEL_REFERENCE, profile='B2',
                source_commit=manifest.get('commit'), llama_revision=runtime.LLAMA_REVISION,
                primary_contract=manifest.get('primary_contract', 'reason-last-v1'),
                primary_recovery_enabled=manifest.get('primary_recovery_enabled', False),
                authenticated_vendor_files=len(trusted_vendor), vendor_registry_sha256=sha256(VENDOR_REGISTRY),
                vendor_scope='Exact official pinned wheel bytes; public examples distinguished from operator secrets',
                validation=['pinned_model_identity', 'complete_model_hash', 'all_member_crc_and_hashes',
                            'exact_manifest_file_set', 'root_layout_and_unix_permissions',
                            'native_elf_headers', 'host_driver_exclusion', 'known_secret_path_and_text_scan'],
                GPU_INFERENCE='NOT_EXECUTED_BY_THIS_VERIFIER',
                rebuilt_runtime_quality='NOT_EVALUATED_BY_PACKAGING_CHECK',
                contest_time_limit='NOT_VERIFIED_BY_PACKAGING_CHECK')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--archive', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--expected-zip-sha256')
    args = parser.parse_args()
    if args.receipt.exists():
        raise ValueError('SUBMISSION_VERIFICATION_RECEIPT_ALREADY_EXISTS')
    result = verify_submission(args.archive, args.expected_zip_sha256)
    args.receipt.parent.mkdir(parents=True, exist_ok=True)
    with args.receipt.open('x', encoding='utf-8') as output:
        output.write(json.dumps(result, indent=2, sort_keys=True) + '\n')
    print(json.dumps(result, indent=2))


if __name__ == '__main__':
    main()
