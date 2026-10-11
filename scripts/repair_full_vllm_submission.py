"""Repair a frozen full ZIP without rebuilding its model or inference payload."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import sys
import time
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.assemble_vllm_submission import json_bytes, json_read, record_valid, zip_entries
from scripts.build_platform_startup_probe import file_info, raw_copy, stream_digest
from scripts.repair_vllm_toolchain import archive_patches

SOURCE_SHA256 = 'ce6fc68434d81375ec81f33139c70f5e14954e880fc8ba32bd22421b4876e336'
ADAPTER_SHA256 = 'ee7b747898958504d9a904d62452aeae6294dd86bbed27ce2a03d79c50b51bc7'
CAP = 40_000_000_000


def adapter_patch(original, reference):
    """Require an otherwise identical adapter; only startup diagnostics may differ."""
    old, new = ast.parse(original), ast.parse(reference)
    old_class = next(n for n in old.body if isinstance(n, ast.ClassDef) and n.name == 'OwnedVllmServer')
    new_class = next(n for n in new.body if isinstance(n, ast.ClassDef) and n.name == 'OwnedVllmServer')
    new.body = [n for n in new.body if not (
        isinstance(n, ast.Import) and len(n.names) == 1 and n.names[0].name == 'sys'
        or isinstance(n, ast.Assign) and any(isinstance(t, ast.Name) and t.id == 'STARTUP_LOG_TAIL_BYTES' for t in n.targets))]
    new_class.body = [n for n in new_class.body if not isinstance(n, ast.FunctionDef)
                      or n.name not in ('_redact_startup_text', '_report_startup_failure')]
    for name in ('__init__', '__enter__'):
        old_method = next(n for n in old_class.body if isinstance(n, ast.FunctionDef) and n.name == name)
        new_method = next(n for n in new_class.body if isinstance(n, ast.FunctionDef) and n.name == name)
        for node in ast.walk(new_method):
            if hasattr(node, 'body') and isinstance(node.body, list):
                node.body = [n for n in node.body if not (
                    isinstance(n, ast.Assign) and len(n.targets) == 1
                    and isinstance(n.targets[0], ast.Attribute)
                    and isinstance(n.targets[0].value, ast.Name) and n.targets[0].value.id == 'self'
                    and n.targets[0].attr == 'popen_started')]
        if name == '__enter__':
            old_try = next(n for n in old_method.body if isinstance(n, ast.Try))
            new_try = next(n for n in new_method.body if isinstance(n, ast.Try))
            new_try.handlers = old_try.handlers
    if ast.dump(old, include_attributes=False) != ast.dump(new, include_attributes=False):
        raise ValueError('NON_DIAGNOSTIC_ADAPTER_CHANGE')
    if b'_report_startup_failure' not in reference or b'GUARDIAN VLLM STARTUP FAILURE BEGIN' not in reference:
        raise ValueError('STARTUP_DIAGNOSTICS_MISSING')
    return reference


def progress(phase, **values):
    print(json.dumps(dict(phase=phase, **values)), flush=True)


def repair(source_path, output, *, adapter_path=None, source_sha256=SOURCE_SHA256,
           adapter_sha256=ADAPTER_SHA256):
    source_path, output = Path(source_path), Path(output)
    adapter_path = Path(adapter_path or Path(__file__).with_name('qwen_vllm_adapter.py'))
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    for path in (output, partial, receipt_path, checksum_path):
        if path.exists():
            raise FileExistsError(path)
    if output.resolve() == source_path.resolve():
        raise ValueError('OUTPUT_IS_SOURCE')
    output.parent.mkdir(parents=True, exist_ok=True)
    before = source_path.stat()
    if shutil.disk_usage(output.parent).free < before.st_size + (64 << 20):
        raise ValueError('INSUFFICIENT_FREE_SPACE')
    progress('verify_source_zip_sha256', bytes=before.st_size)
    with source_path.open('rb') as stream:
        _, source_digest = stream_digest(stream)
    if source_digest != source_sha256:
        raise ValueError('SOURCE_ZIP_SHA256_MISMATCH')
    with zipfile.ZipFile(source_path) as source:
        entries = zip_entries(source)
        original_raw = source.read('MANIFEST.json')
        manifest = json_read(original_raw)
        if manifest.get('model_mode') != 'FULL_MODELS_SHA256_VERIFIED':
            raise ValueError('FULL_MODEL_SOURCE_REQUIRED')
        files = manifest['files']
        if set(files) != set(entries) - {'MANIFEST.json'}:
            raise ValueError('SOURCE_FILE_SET_MISMATCH')
        for name, row in files.items():
            record_valid(row)
            info = entries[name]
            if row['bytes'] != info.file_size or row['mode'] != stat.S_IMODE(info.external_attr >> 16):
                raise ValueError('SOURCE_METADATA_MISMATCH:' + name)
        patches, changes = archive_patches(source, system_compiler_contrast=False)
        adapter_name = 'scripts/qwen_vllm_adapter.py'
        old_adapter = source.read(adapter_name)
        if hashlib.sha256(old_adapter).hexdigest() != adapter_sha256:
            raise ValueError('SOURCE_ADAPTER_SHA256_MISMATCH')
        reference = adapter_path.read_bytes().replace(b'\r\n', b'\n')
        patches[adapter_name] = (adapter_patch(old_adapter, reference), files[adapter_name]['mode'])
        changes[adapter_name] = dict(original_sha256=adapter_sha256,
            repaired_sha256=hashlib.sha256(reference).hexdigest(), purpose='Bounded redacted startup failure log')
        expected = {name: dict(row) for name, row in files.items()}
        for name, (data, mode) in patches.items():
            expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
        # Preserve the original build identity; record the operator repair separately.
        provenance = dict(source_zip_sha256=source_digest,
            source_manifest_sha256=hashlib.sha256(original_raw).hexdigest(),
            changes=changes, system_compiler_fallback=False,
            validation_scope='PLATFORM_DUMMY_STARTUP_CONFIRMED_REAL_WEIGHTS_QUALITY_AND_FULL_TIME_PENDING')
        final = dict(manifest, files=expected, operator_repair=provenance)
        final_raw = json_bytes(final)
        expected_with_manifest = dict(expected, **{'MANIFEST.json': dict(bytes=len(final_raw),
            sha256=hashlib.sha256(final_raw).hexdigest(), mode=0o644)})
        ordered = sorted(entries.values(), key=lambda i: i.header_offset)
        boundaries = {i.filename: ordered[k+1].header_offset if k+1 < len(ordered) else source.start_dir
                      for k, i in enumerate(ordered)}
        if len({i.header_offset for i in ordered}) != len(ordered):
            raise ValueError('DUPLICATE_SOURCE_OFFSETS')
        progress('copy_compressed_records', members=len(entries), patched=len(patches))
        last = time.monotonic()
        created_partial = False
        try:
            raw = partial.open('xb')
            created_partial = True
            with raw, zipfile.ZipFile(raw, 'w', allowZip64=True) as target:
                for number, info in enumerate(ordered, 1):
                    name = info.filename
                    if name == 'MANIFEST.json':
                        target.writestr(file_info(name), final_raw)
                    elif name in patches:
                        data, mode = patches[name]
                        target.writestr(file_info(name, mode), data)
                    else:
                        raw_copy(source, target, info, boundaries[name])
                    if target.start_dir > CAP:
                        raise ValueError('ARCHIVE_CAP_EXCEEDED')
                    if time.monotonic() - last > 25:
                        progress('copy_progress', members=number, bytes=target.start_dir)
                        last = time.monotonic()
                for name in sorted(set(patches) - set(entries)):
                    data, mode = patches[name]
                    target.writestr(file_info(name, mode), data)
            if partial.stat().st_size > CAP:
                raise ValueError('ARCHIVE_CAP_EXCEEDED')
            progress('verify_all_members_sha256_crc_modes', members=len(expected_with_manifest))
            with zipfile.ZipFile(partial) as check:
                actual = zip_entries(check)
                if set(actual) != set(expected_with_manifest):
                    raise ValueError('FINAL_FILE_SET_MISMATCH')
                last = time.monotonic()
                for number, (name, info) in enumerate(actual.items(), 1):
                    with check.open(info) as stream:
                        size, digest = stream_digest(stream)
                    row = expected_with_manifest[name]
                    if (size, digest, stat.S_IMODE(info.external_attr >> 16)) != (row['bytes'], row['sha256'], row['mode']):
                        raise ValueError('FINAL_MEMBER_MISMATCH:' + name)
                    if time.monotonic() - last > 25:
                        progress('verification_progress', members=number)
                        last = time.monotonic()
            after = source_path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('SOURCE_CHANGED_DURING_BUILD')
            progress('hash_final_zip')
            with partial.open('rb') as stream:
                size, digest = stream_digest(stream)
            result = dict(output=str(output), bytes=size, sha256=digest, files=len(expected_with_manifest),
                all_members_sha256_crc_modes_verified=True, model_and_b2_unchanged=True,
                original_source_sha=manifest.get('source_sha'), operator_repair=provenance)
            os.link(partial, output)
            partial.unlink()
            with receipt_path.open('x', encoding='utf-8') as stream:
                json.dump(result, stream, indent=2)
            with checksum_path.open('x', encoding='ascii') as stream:
                stream.write(digest + '  ' + output.name + '\n')
            progress('ready', **result)
            return result
        finally:
            if created_partial:
                partial.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    repair(args.source_zip, args.output)
