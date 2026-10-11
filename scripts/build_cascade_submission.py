"""Build the Granite FP8 -> Qwen3.8 AWQ cascade ZIP from the toolchain-fixed full ZIP.

Copies every runtime/source record of the verified source ZIP byte-for-byte (compressed
records, no extraction), drops the Qwen3.8 FP8 weights and their manifest, replaces the
entrypoint/adapter/README, adds the cascade code and both model directories (each file
checked against the committed SHA256 manifests), then re-reads and verifies every final
member (size, SHA256, CRC, mode) and the < 40 GB cap before publishing.

python scripts/build_cascade_submission.py --source-zip <toolchain-fixed.zip> \
    --source-sha256 <sha> [--granite-dir <dir>] [--qwen-dir <dir>] --output <new.zip>
Without --qwen-dir the archive is Granite-only (~14 GB; the cascade skips Qwen).
Without --granite-dir it is Qwen-only (diagnostic; Qwen B2 on rows in seeded-shuffled order).
"""
from __future__ import annotations

import argparse
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
from scripts import cascade_submission as cascade

CAP = 40_000_000_000
OLD_REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
DOCS = Path('docs/cascade_20261011')
CODE = {
    'scripts/predict.py': 'submission/predict_cascade.py',
    'scripts/cascade_submission.py': 'scripts/cascade_submission.py',
    'scripts/granite_stage.py': 'scripts/granite_stage.py',
    'scripts/qwen_vllm_adapter.py': 'scripts/qwen_vllm_adapter.py',
    'README.md': 'docs/cascade_20261011/README.md',
    cascade.QWEN_MANIFEST: 'docs/cascade_20261011/QWEN_MANIFEST.json',
    'GRANITE_MANIFEST.json': 'docs/cascade_20261011/GRANITE_MANIFEST.json',
}
DROP_PREFIXES = ('model/' + OLD_REVISION + '/',)
DROP_NAMES = ('MODEL_MANIFEST.json',)


def progress(phase, **values):
    print(json.dumps(dict(phase=phase, **values)), flush=True)


def sha256_file(path):
    with open(path, 'rb') as stream:
        return stream_digest(stream)


def model_members(directory, manifest, prefix):
    """(zip name, source path, record) for every manifest file, verified by size and SHA256."""
    directory = Path(directory)
    members = []
    for entry in manifest['files']:
        name = entry['path']
        if '/' in name or '\\' in name or name.startswith('.') or name in ('', '..'):
            raise ValueError('UNSAFE_MODEL_FILE:' + name)
        path = directory / name
        size, digest = sha256_file(path)
        if (size, digest) != (entry['size'], entry['sha256']):
            raise ValueError('MODEL_FILE_MISMATCH:' + name)
        members.append((prefix + name, path, dict(bytes=size, sha256=digest, mode=0o644)))
    progress('model_verified', prefix=prefix, files=len(members), bytes=sum(m[2]['bytes'] for m in members))
    return members


def write_file(target, name, path):
    info = file_info(name)
    info.compress_type = zipfile.ZIP_STORED if name.endswith('.safetensors') else zipfile.ZIP_DEFLATED
    info.file_size = Path(path).stat().st_size
    with open(path, 'rb') as source, target.open(info, 'w', force_zip64=True) as stream:
        shutil.copyfileobj(source, stream, 8 << 20)


def build(source_zip, source_sha256, granite_dir, qwen_dir, output, repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[1])
    source_zip, output = Path(source_zip), Path(output)
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    for path in (output, partial, receipt_path, checksum_path):
        if path.exists():
            raise FileExistsError(path)
    code = {name: (repo / source).read_bytes().replace(b'\r\n', b'\n') for name, source in CODE.items()}
    if granite_dir is None and qwen_dir is None:
        raise ValueError('NO_MODELS')
    granite_only = qwen_dir is None  # variant: no Qwen weights; the runtime then skips stage 2
    qwen_only = granite_dir is None  # variant: no Granite; the runtime runs Qwen alone
    qwen_manifest, granite_manifest = (json_read(code[cascade.QWEN_MANIFEST]), json_read(code['GRANITE_MANIFEST.json']))
    if (qwen_manifest.get('repository'), qwen_manifest.get('revision')) != (cascade.QWEN_REPOSITORY, cascade.QWEN_REVISION):
        raise ValueError('QWEN_MANIFEST_IDENTITY_MISMATCH')
    progress('verify_source_zip_sha256', bytes=source_zip.stat().st_size)
    before = source_zip.stat()
    if sha256_file(source_zip)[1] != source_sha256:
        raise ValueError('SOURCE_ZIP_SHA256_MISMATCH')
    models = [] if qwen_only else model_members(granite_dir, granite_manifest, cascade.GRANITE_MODEL + '/')
    if qwen_only:
        del code['GRANITE_MANIFEST.json']
    if granite_only:
        del code[cascade.QWEN_MANIFEST]
    else:
        models += model_members(qwen_dir, qwen_manifest, 'model/' + cascade.QWEN_REVISION + '/')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_zip) as source:
        entries = zip_entries(source)
        original_raw = source.read('MANIFEST.json')
        manifest = json_read(original_raw)
        if manifest.get('model_mode') != 'FULL_MODELS_SHA256_VERIFIED' or 'operator_repair' not in manifest:
            raise ValueError('TOOLCHAIN_FIXED_FULL_SOURCE_REQUIRED')
        files = manifest['files']
        if set(files) != set(entries) - {'MANIFEST.json'}:
            raise ValueError('SOURCE_FILE_SET_MISMATCH')
        for name, row in files.items():
            record_valid(row)
            if row['bytes'] != entries[name].file_size:
                raise ValueError('SOURCE_METADATA_MISMATCH:' + name)
        dropped = sorted(n for n in files if n.startswith(DROP_PREFIXES) or n in DROP_NAMES)
        if not any(n.startswith(DROP_PREFIXES) for n in dropped):
            raise ValueError('SOURCE_FP8_MODEL_NOT_FOUND')
        expected = {n: dict(r) for n, r in files.items() if n not in dropped}
        for name, data in code.items():
            mode = expected.get(name, {}).get('mode', 0o644)
            expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
        for name, _, record in models:
            if name in expected:
                raise ValueError('MODEL_NAME_COLLISION:' + name)
            expected[name] = record
        provenance = dict(source_zip_sha256=source_sha256,
                          source_manifest_sha256=hashlib.sha256(original_raw).hexdigest(),
                          profile=cascade.PROFILE, granite_only=granite_only, qwen_only=qwen_only, dropped=len(dropped),
                          replaced_or_added_code={n: expected[n]['sha256'] for n in code},
                          models=dict(granite=cascade.GRANITE_MODEL,
                                      qwen='model/' + cascade.QWEN_REVISION, qwen_repository=cascade.QWEN_REPOSITORY))
        final = dict(manifest, files=expected, cascade_build=provenance,
                     profile=('GRANITE41_FP8_ONLY' if granite_only else
                              'QWEN38_AWQ_B2_ONLY' if qwen_only else 'CASCADE_GRANITE41_FP8_OR_QWEN38_AWQ_B2'))
        final_raw = json_bytes(final)
        expected_all = dict(expected, **{'MANIFEST.json': dict(bytes=len(final_raw),
                            sha256=hashlib.sha256(final_raw).hexdigest(), mode=0o644)})
        ordered = sorted(entries.values(), key=lambda i: i.header_offset)
        boundaries = {i.filename: ordered[k + 1].header_offset if k + 1 < len(ordered) else source.start_dir
                      for k, i in enumerate(ordered)}
        progress('write', copied=len(ordered) - len(dropped) - 1, models=len(models), code=len(code))
        try:
            with partial.open('xb') as raw, zipfile.ZipFile(raw, 'w', allowZip64=True) as target:
                last = time.monotonic()
                for info in ordered:
                    name = info.filename
                    if name in dropped or name == 'MANIFEST.json' or name in code:
                        continue
                    raw_copy(source, target, info, boundaries[name])
                    if time.monotonic() - last > 25:
                        progress('copy_progress', bytes=target.start_dir)
                        last = time.monotonic()
                for name, data in code.items():
                    target.writestr(file_info(name, expected[name]['mode']), data)
                target.writestr(file_info('MANIFEST.json'), final_raw)
                for name, path, _ in models:
                    write_file(target, name, path)
                    progress('model_written', name=name, bytes=target.start_dir)
                    if target.start_dir > CAP:
                        raise ValueError('ARCHIVE_CAP_EXCEEDED')
            if partial.stat().st_size >= CAP:
                raise ValueError('ARCHIVE_CAP_EXCEEDED')
            progress('verify_all_members', members=len(expected_all))
            with zipfile.ZipFile(partial) as check:
                actual = zip_entries(check)
                if set(actual) != set(expected_all):
                    raise ValueError('FINAL_FILE_SET_MISMATCH')
                for name, info in actual.items():
                    with check.open(info) as stream:  # zipfile checks CRC at EOF
                        size, digest = stream_digest(stream)
                    row = expected_all[name]
                    if (size, digest, stat.S_IMODE(info.external_attr >> 16)) != (row['bytes'], row['sha256'], row['mode']):
                        raise ValueError('FINAL_MEMBER_MISMATCH:' + name)
            after = source_zip.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('SOURCE_CHANGED_DURING_BUILD')
            size, digest = sha256_file(partial)
            result = dict(output=str(output), bytes=size, sha256=digest, under_cap=size < CAP,
                          files=len(expected_all), all_members_verified=True, cascade_build=provenance)
            os.replace(partial, output)
            receipt_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
            checksum_path.write_text(digest + '  ' + output.name + '\n', encoding='ascii')
            progress('ready', **result)
            return result
        finally:
            partial.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--granite-dir', type=Path, help='Omit for the Qwen-only archive')
    parser.add_argument('--qwen-dir', type=Path, help='Omit for the Granite-only archive')
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source_zip, args.source_sha256, args.granite_dir, args.qwen_dir, args.output)
