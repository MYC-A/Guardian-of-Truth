"""Operator-only streaming join of frozen Linux runtime and verified local FP8 assets.

Does not extract, install, run inference, or claim GPU validation. Inputs remain
immutable; final ZIP publication uses an exclusive same-filesystem hard link.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import sys
import zipfile

if __package__ in (None, ''):
    # Operator command also works without a preconfigured PYTHONPATH.
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.build_vllm_submission import (
    CappedStream, ENGINE_VERSION, MAX_ARCHIVE_BYTES, REPOSITORY, REVISION,
    VERSION, model_declarations, relative_name,
)

CHUNK = 8 * 1024 * 1024
JSON_CAP = 16 * 1024 * 1024


def json_bytes(value):
    return (json.dumps(value, sort_keys=True, indent=2, allow_nan=False) + '\n').encode('utf-8')


def json_read(raw):
    def unique(pairs):
        result = {}
        for name, value in pairs:
            if name in result:
                raise ValueError('DUPLICATE_JSON_KEY')
            result[name] = value
        return result
    return json.loads(raw.decode('utf-8'), object_pairs_hook=unique,
                      parse_constant=lambda value: (_ for _ in ()).throw(ValueError('NONFINITE_JSON')))


def hash_stream(stream):
    checksum, size = hashlib.sha256(), 0
    for chunk in iter(lambda: stream.read(CHUNK), b''):
        checksum.update(chunk)
        size += len(chunk)
    return size, checksum.hexdigest()


def record_valid(entry):
    if not isinstance(entry, dict):
        raise ValueError('INVALID_FILE_RECORD')
    if (type(entry.get('bytes')) is not int or entry['bytes'] < 0
            or not isinstance(entry.get('sha256'), str)
            or re.fullmatch('[0-9a-f]{64}', entry['sha256']) is None
            or type(entry.get('mode')) is not int or not 0 <= entry['mode'] <= 0o777):
        raise ValueError('INVALID_FILE_RECORD')


def forbidden(name):
    parts = relative_name(name).parts
    return (any(part in ('outputs', 'benchmarks', '__pycache__', '.git', 'secrets') for part in parts)
            or name.endswith(('.parquet', '.jsonl', '.log', '.env', '.pyc'))
            or Path(name).name in ('api_keys.env', 'valid.parquet'))


def zip_entries(bundle):
    entries = {}
    for info in bundle.infolist():
        if info.orig_filename != info.filename:
            raise ValueError('UNSAFE_ASSET_PATH')
        relative_name(info.filename)
        kind = stat.S_IFMT(info.external_attr >> 16)
        if (info.filename in entries or info.is_dir() or kind not in (0, stat.S_IFREG)
                or info.flag_bits & 1 or forbidden(info.filename)):
            raise ValueError('UNSAFE_OR_DUPLICATE_ZIP_ENTRY:' + info.filename)
        entries[info.filename] = info
    return entries


def small_json(bundle, entries, name):
    if name not in entries or entries[name].file_size > JSON_CAP:
        raise ValueError('MISSING_OR_OVERSIZE_METADATA:' + name)
    raw = bundle.read(entries[name])
    return raw, json_read(raw)


def validate_runtime(bundle):
    entries = zip_entries(bundle)
    raw, manifest = small_json(bundle, entries, 'MANIFEST.json')
    if not isinstance(manifest, dict):
        raise ValueError('INVALID_RUNTIME_MANIFEST')
    identity = {'version': VERSION, 'model_repository': REPOSITORY,
                'model_revision': REVISION, 'engine_version': ENGINE_VERSION,
                'max_archive_bytes': MAX_ARCHIVE_BYTES}
    if any(manifest.get(key) != value for key, value in identity.items()):
        raise ValueError('RUNTIME_IDENTITY_MISMATCH')
    if re.fullmatch('[0-9a-f]{40}', str(manifest.get('source_sha', ''))) is None:
        raise ValueError('SOURCE_SHA_REQUIRED')
    files = manifest.get('files')
    if not isinstance(files, dict):
        raise ValueError('RUNTIME_FILES_REQUIRED')
    for name, record in files.items():
        relative_name(name)
        if name == 'MANIFEST.json' or forbidden(name):
            raise ValueError('INVALID_RUNTIME_INVENTORY')
        record_valid(record)
    available = set(entries) - {'MANIFEST.json'}
    runtime = {name for name in files if not name.startswith('model/')}
    if available not in (set(files), runtime):
        raise ValueError('RUNTIME_FILE_SET_MISMATCH')
    required = {'MODEL_MANIFEST.json', 'Dockerfile', 'pyproject.toml', 'build_backend.py',
                'scripts/predict.py', 'runtime/python/run_python.sh'}
    if not required.issubset(runtime):
        raise ValueError('PUBLIC_ROOT_LAYOUT_REQUIRED')
    for name in available:
        record, info = files[name], entries[name]
        if (info.file_size != record['bytes']
                or ((info.external_attr >> 16) & 0o777) != record['mode']):
            raise ValueError('RUNTIME_SIZE_OR_MODE_MISMATCH:' + name)
        with bundle.open(info) as stream:
            if hash_stream(stream) != (record['bytes'], record['sha256']):
                raise ValueError('RUNTIME_SHA256_MISMATCH:' + name)
    model_raw, model_manifest = small_json(bundle, entries, 'MODEL_MANIFEST.json')
    if hashlib.sha256(model_raw).hexdigest() != manifest.get('model_manifest_sha256'):
        raise ValueError('MODEL_METADATA_SHA256_MISMATCH')
    declarations = model_declarations(model_manifest)
    if manifest.get('models_expected') != declarations:
        raise ValueError('MODEL_DECLARATIONS_MISMATCH')
    model_mode = manifest.get('model_mode')
    if model_mode not in ('RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED', 'FULL_MODELS_SHA256_VERIFIED'):
        raise ValueError('MODEL_MODE_REQUIRED')
    expected_weights = {'model/' + REVISION + '/' + row['path']: row for row in declarations}
    if model_mode == 'RUNTIME_ONLY_MODELS_NOT_LOCALLY_VERIFIED' and any(name.startswith('model/') for name in files):
        raise ValueError('PARTIAL_MANIFEST_CLAIMS_LOCAL_WEIGHTS')
    if model_mode == 'FULL_MODELS_SHA256_VERIFIED':
        if set(files) - runtime != set(expected_weights):
            raise ValueError('MODEL_SOURCE_FILE_SET_MISMATCH')
        for name, row in expected_weights.items():
            if files[name]['bytes'] != row['size'] or files[name]['sha256'] != row['sha256']:
                raise ValueError('MODEL_SOURCE_BYTES_MISMATCH')
    return entries, manifest, declarations, hashlib.sha256(raw).hexdigest()


def model_paths(model_dir, declarations):
    def linked(path):
        return path.is_symlink() or getattr(path, 'is_junction', lambda: False)()
    requested_root = Path(model_dir).absolute()
    if linked(requested_root):
        raise ValueError('MODEL_SYMLINK_FORBIDDEN')
    root = requested_root.resolve(strict=True)
    paths = {}
    for row in declarations:
        relative_name(row['path'])
        target = root / row['path']
        for parent in (target, *target.parents):
            if parent == root:
                break
            if linked(parent):
                raise ValueError('MODEL_SYMLINK_FORBIDDEN')
        if not target.resolve(strict=True).is_relative_to(root) or not target.is_file():
            raise ValueError('MODEL_PATH_ESCAPE')
        with target.open('rb') as stream:
            if hash_stream(stream) != (row['size'], row['sha256']):
                raise ValueError('LOCAL_MODEL_BYTES_MISMATCH:' + row['path'])
        paths[row['path']] = target
    def metadata(name):
        if paths[name].stat().st_size > JSON_CAP:
            raise ValueError('OVERSIZE_MODEL_METADATA')
        return json_read(paths[name].read_bytes())
    index = metadata('model.safetensors.index.json')
    weight_map = index.get('weight_map')
    if (not isinstance(weight_map, dict) or not weight_map
            or not all(isinstance(value, str) for value in weight_map.values())
            or set(weight_map.values()) != {name for name in paths if name.endswith('.safetensors')}):
        raise ValueError('MODEL_INDEX_SET_MISMATCH')
    config = metadata('config.json')
    if config.get('quantization_config', {}).get('quant_method') != 'fp8':
        raise ValueError('FP8_MODEL_REQUIRED')
    return paths


def write_entry(bundle, name, mode, source, expected):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_STORED if name.endswith('.safetensors') else zipfile.ZIP_DEFLATED
    info._compresslevel = 1
    checksum, size = hashlib.sha256(), 0
    with bundle.open(info, 'w', force_zip64=True) as target:
        for chunk in iter(lambda: source.read(CHUNK), b''):
            target.write(chunk)
            checksum.update(chunk)
            size += len(chunk)
    if (size, checksum.hexdigest()) != (expected['bytes'], expected['sha256']):
        raise ValueError('INPUT_CHANGED_DURING_ASSEMBLY:' + name)


def validate_final(path, expected):
    with zipfile.ZipFile(path) as bundle:
        entries = zip_entries(bundle)
        if set(entries) != set(expected):
            raise ValueError('FINAL_FILE_SET_MISMATCH')
        for name, row in expected.items():
            if ((entries[name].external_attr >> 16) & 0o777) != row['mode']:
                raise ValueError('FINAL_MODE_MISMATCH')
            with bundle.open(entries[name]) as stream:
                if hash_stream(stream) != (row['bytes'], row['sha256']):
                    raise ValueError('FINAL_BYTES_MISMATCH:' + name)


def assemble(runtime_archive, model_dir, output, receipt, *, cap=MAX_ARCHIVE_BYTES):
    output, receipt = Path(output).absolute(), Path(receipt).absolute()
    partial = output.with_name(output.name + '.partial')
    receipt_partial = receipt.with_name(receipt.name + '.partial')
    targets = (output, receipt, partial, receipt_partial)
    if len(set(targets)) != len(targets):
        raise ValueError('OUTPUT_PATH_COLLISION')
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError('OUTPUT_OR_RECEIPT_ALREADY_EXISTS')
    if any(path.is_relative_to(Path(model_dir).resolve()) for path in targets):
        raise ValueError('OUTPUT_MUST_BE_OUTSIDE_MODEL')
    if Path(runtime_archive).resolve() in (path.resolve() for path in targets):
        raise ValueError('OUTPUT_MUST_DIFFER_FROM_RUNTIME')
    if type(cap) is not int or not 0 < cap <= MAX_ARCHIVE_BYTES:
        raise ValueError('INVALID_ARCHIVE_CAP')
    output.parent.mkdir(parents=True, exist_ok=True)
    receipt.parent.mkdir(parents=True, exist_ok=True)
    created = []
    try:
        with zipfile.ZipFile(runtime_archive) as source:
            entries, original, declarations, source_hash = validate_runtime(source)
            paths = model_paths(model_dir, declarations)
            files = {name: dict(row) for name, row in original['files'].items() if not name.startswith('model/')}
            for row in declarations:
                files['model/' + REVISION + '/' + row['path']] = dict(bytes=row['size'], sha256=row['sha256'], mode=0o644)
            final = dict(original, files=files, model_mode='FULL_MODELS_SHA256_VERIFIED',
                         assembly_mode='COMPLETE_CANDIDATE', source_manifest_sha256=source_hash,
                         integrity_contract='All runtime and local model bytes SHA256 verified; no GPU validation implied')
            raw_manifest = json_bytes(final)
            expected = dict(files, **{'MANIFEST.json': dict(bytes=len(raw_manifest), sha256=hashlib.sha256(raw_manifest).hexdigest(), mode=0o644)})
            with partial.open('xb') as raw:
                created.append(partial)
                capped = CappedStream(raw, cap)
                with zipfile.ZipFile(capped, 'w', allowZip64=True) as target:
                    import io
                    for name in sorted(expected):
                        row = expected[name]
                        if name == 'MANIFEST.json':
                            with io.BytesIO(raw_manifest) as stream:
                                write_entry(target, name, row['mode'], stream, row)
                        elif name.startswith('model/'):
                            with paths[name.removeprefix('model/' + REVISION + '/')].open('rb') as stream:
                                write_entry(target, name, row['mode'], stream, row)
                        else:
                            with source.open(entries[name]) as stream:
                                write_entry(target, name, row['mode'], stream, row)
                raw.flush()
                os.fsync(raw.fileno())
                size, checksum = capped.count, capped.hash.hexdigest()
        validate_final(partial, expected)
        result = dict(status='COMPLETE_CANDIDATE', bytes=size, sha256=checksum, cap_bytes=cap,
                      source_manifest_sha256=source_hash, source_sha=original['source_sha'],
                      model_repository=REPOSITORY, model_revision=REVISION, engine_version=ENGINE_VERSION,
                      gpu_validation=original.get('gpu_validation', 'UNSPECIFIED_IN_SOURCE'),
                      files=len(expected), output=str(output))
        with receipt_partial.open('xb') as raw:
            created.append(receipt_partial)
            raw.write(json_bytes(result))
            raw.flush()
            os.fsync(raw.fileno())
        os.link(partial, output)  # Exclusive atomic publication, never replace another archive.
        try:
            os.link(receipt_partial, receipt)
        except BaseException:
            # Archive is valid and published; leave it intact if receipt publication races.
            raise
        return result
    finally:
        for path in created:
            path.unlink(missing_ok=True)


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('runtime-archive', 'model-dir', 'output', 'receipt'):
        parser.add_argument('--' + name, type=Path, required=True)
    args = parser.parse_args(argv)
    result = assemble(args.runtime_archive, args.model_dir, args.output, args.receipt)
    print(json.dumps(result, sort_keys=True))


if __name__ == '__main__':
    main()
