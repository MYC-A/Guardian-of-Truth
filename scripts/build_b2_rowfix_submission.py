"""Repack the pinned graphs16 ZIP with row identity/CSV repair and progress logs."""
from __future__ import annotations

import argparse
import ast
import hashlib
import json
import os
from pathlib import Path
import shutil
import stat
import subprocess
import sys
import time
import zipfile

if __package__ in (None, ''):
    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from scripts.assemble_vllm_submission import json_bytes, json_read, record_valid, zip_entries
from scripts.build_platform_startup_probe import file_info, raw_copy, stream_digest

SOURCE_SHA256 = 'bcdb2a884f2a369b53eeee468a1f16b24202b0ef6524e551452e7a27ec116382'
CAP = 40_000_000_000


def progress(phase, **values):
    print(json.dumps(dict(phase=phase, **values), sort_keys=True), flush=True)


def sha256_file(path, phase):
    digest, size, last = hashlib.sha256(), 0, time.monotonic()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b''):
            digest.update(chunk)
            size += len(chunk)
            if time.monotonic() - last > 15:
                progress(phase, bytes=size)
                last = time.monotonic()
    return size, digest.hexdigest()


def logging_only_adapter(old, new):
    """Require byte-source AST equivalence after removing added progress logging."""
    class StripLogging(ast.NodeTransformer):
        def visit_FunctionDef(self, node):
            if node.name == 'emit_row_progress':
                return None
            return self.generic_visit(node)

        def visit_Expr(self, node):
            if (isinstance(node.value, ast.Call) and isinstance(node.value.func, ast.Name)
                    and node.value.func.id == 'emit_row_progress'):
                return None
            return self.generic_visit(node)

    before = ast.parse(old)
    after = StripLogging().visit(ast.parse(new))
    if ast.dump(before, include_attributes=False) != ast.dump(after, include_attributes=False):
        raise ValueError('NON_LOGGING_ADAPTER_CHANGE')
    return new


def validate_members(path, expected):
    with zipfile.ZipFile(path) as bundle:
        actual = zip_entries(bundle)
        if set(actual) != set(expected):
            raise ValueError('FINAL_FILE_SET_MISMATCH')
        last = time.monotonic()
        for count, (name, info) in enumerate(actual.items(), 1):
            with bundle.open(info) as stream:
                size, digest = stream_digest(stream)  # zipfile checks CRC at EOF
            row = expected[name]
            if (size, digest, stat.S_IMODE(info.external_attr >> 16)) != (
                    row['bytes'], row['sha256'], row['mode']):
                raise ValueError('FINAL_MEMBER_MISMATCH:' + name)
            if time.monotonic() - last > 15:
                progress('verify_progress', members=count, total=len(actual))
                last = time.monotonic()


def build(source_path, output, *, source_sha256=SOURCE_SHA256, repo_root=None):
    source_path, output = Path(source_path).resolve(), Path(output).resolve()
    repo = Path(repo_root or Path(__file__).resolve().parents[1])
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    ready_path = output.with_suffix('.ready.json')
    targets = (output, partial, receipt_path, checksum_path, ready_path)
    if source_path in targets or len(set(targets)) != len(targets):
        raise ValueError('SOURCE_OUTPUT_COLLISION')
    if any(path.exists() or path.is_symlink() for path in targets):
        raise FileExistsError('OUTPUT_ALREADY_EXISTS')
    before = source_path.stat()
    output.parent.mkdir(parents=True, exist_ok=True)
    if shutil.disk_usage(output.parent).free < before.st_size + (64 << 20):
        raise ValueError('INSUFFICIENT_FREE_SPACE')
    progress('verify_source', bytes=before.st_size)
    _, source_digest = sha256_file(source_path, 'verify_source_progress')
    if source_digest != source_sha256:
        raise ValueError('SOURCE_ZIP_SHA256_MISMATCH')
    code = {
        'scripts/predict.py': (repo / 'submission/predict_vllm.py').read_bytes().replace(b'\r\n', b'\n'),
        'scripts/qwen_vllm_adapter.py': (repo / 'scripts/qwen_vllm_adapter.py').read_bytes().replace(b'\r\n', b'\n'),
        'README.md': (repo / 'docs/qwen_graphs16_rowfix_20261012.md').read_bytes().replace(b'\r\n', b'\n'),
    }
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
        if not set(code) <= set(files):
            raise ValueError('PATCH_TARGET_MISSING')
        logging_only_adapter(source.read('scripts/qwen_vllm_adapter.py'), code['scripts/qwen_vllm_adapter.py'])
        expected = {name: dict(row) for name, row in files.items()}
        changes = {}
        for name, data in code.items():
            expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=files[name]['mode'])
            changes[name] = dict(before=files[name]['sha256'], after=expected[name]['sha256'])
        commit = subprocess.run(['git', '-C', str(repo), 'rev-parse', 'HEAD'],
                                check=True, capture_output=True, text=True).stdout.strip()
        provenance = dict(source_zip_sha256=source_digest,
                          source_manifest_sha256=hashlib.sha256(original_raw).hexdigest(),
                          operator_commit=commit, changes=changes,
                          model_and_dependencies_unchanged=True, b2_inference_unchanged=True,
                          row_identity='POSITION', duplicate_ids_allowed=True,
                          csv_large_fields=True, output_format='BY_REQUESTED_SUFFIX',
                          validation_scope='CPU_IO_CONTRACT_AND_ARCHIVE_INTEGRITY_NOT_GPU_QUALITY_OR_FULL_TIME')
        final = dict(manifest, files=expected, operator_row_identity_repair=provenance)
        final_raw = json_bytes(final)
        expected_all = dict(expected, **{'MANIFEST.json': dict(bytes=len(final_raw),
            sha256=hashlib.sha256(final_raw).hexdigest(), mode=0o644)})
        ordered = sorted(entries.values(), key=lambda info: info.header_offset)
        if len({info.header_offset for info in ordered}) != len(ordered):
            raise ValueError('DUPLICATE_SOURCE_OFFSETS')
        boundaries = {info.filename: ordered[k + 1].header_offset if k + 1 < len(ordered) else source.start_dir
                      for k, info in enumerate(ordered)}
        created = False
        try:
            progress('copy_compressed_records', members=len(entries), patched=len(code) + 1)
            raw = partial.open('xb')
            created = True
            with raw, zipfile.ZipFile(raw, 'w', allowZip64=True) as target:
                last = time.monotonic()
                for count, info in enumerate(ordered, 1):
                    name = info.filename
                    if name == 'MANIFEST.json':
                        target.writestr(file_info(name), final_raw)
                    elif name in code:
                        target.writestr(file_info(name, expected[name]['mode']), code[name])
                    else:
                        raw_copy(source, target, info, boundaries[name])
                    if target.start_dir >= CAP:
                        raise ValueError('ARCHIVE_CAP_EXCEEDED')
                    if time.monotonic() - last > 15:
                        progress('copy_progress', members=count, bytes=target.start_dir)
                        last = time.monotonic()
            if partial.stat().st_size >= CAP:
                raise ValueError('ARCHIVE_CAP_EXCEEDED')
            progress('verify_all_members_sha256_crc_modes', members=len(expected_all))
            validate_members(partial, expected_all)
            after = source_path.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (
                    after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('SOURCE_CHANGED_DURING_BUILD')
            progress('hash_final_zip')
            size, digest = sha256_file(partial, 'hash_final_progress')
            result = dict(output=str(output), bytes=size, sha256=digest, files=len(expected_all),
                          under_cap=size < CAP, all_members_verified=True, operator_row_identity_repair=provenance,
                          code_hashes={name: expected[name]['sha256'] for name in code})
            os.link(partial, output)
            partial.unlink()
            receipt_path.write_bytes(json_bytes(result))
            checksum_path.write_text(digest + '  ' + output.name + '\n', encoding='ascii')
            ready_path.write_bytes(json_bytes(dict(result, status='READY_FOR_PLATFORM_TEST',
                real_model_quality_and_full_platform_time_tested=False)))
            progress('ready', **result)
            return result
        finally:
            if created:
                partial.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    arguments = parser.parse_args()
    build(arguments.source_zip, arguments.output)
