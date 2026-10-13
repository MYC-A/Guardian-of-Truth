"""Build the single-pass judge ZIP from a verified full submission ZIP that carries the runtime.

Every runtime/source record of the source ZIP is copied byte-for-byte (raw copy, no extraction).
All model weights (model/...) and old model manifests are dropped. Added: the judge code,
JUDGE_CONFIG.json, README.md, JUDGE_MANIFEST.json (size + SHA256 of every model file) and the model
directory under model/judge/. Every final member and the < 40 GB cap are re-verified before publishing.

python scripts/build_judge_submission.py --source-zip <full.zip> --source-sha256 <sha> \
    --model-dir models/qwen36-a3b-awq --model-id cyankiwi/Qwen3.6-35B-A3B-AWQ-4bit \
    --model-revision <hf commit> --output <judge.zip>
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

from scripts.assemble_vllm_submission import json_bytes, json_read, record_valid, zip_entries  # noqa: E402
from scripts.build_platform_startup_probe import file_info, raw_copy, stream_digest  # noqa: E402

CAP = 40_000_000_000
MODEL_PREFIX = 'model/judge/'
CODE = {
    'scripts/predict.py': 'submission/predict_judge.py',
    'scripts/judge_submission.py': 'scripts/judge_submission.py',
    'scripts/judge_stage.py': 'scripts/judge_stage.py',
    'src/guardian_truth/judge/__init__.py': 'src/guardian_truth/judge/__init__.py',
    'src/guardian_truth/judge/mechanical.py': 'src/guardian_truth/judge/mechanical.py',
    'src/guardian_truth/judge/prompting.py': 'src/guardian_truth/judge/prompting.py',
    'src/guardian_truth/judge/decision.py': 'src/guardian_truth/judge/decision.py',
    'JUDGE_CONFIG.json': 'submission/JUDGE_CONFIG.json',
    'README.md': 'docs/judge_20261013/README.md',
}
DROP_NAMES = {'MODEL_MANIFEST.json', 'GRANITE_MANIFEST.json', 'QWEN_MANIFEST.json', 'JUDGE_MANIFEST.json'}
REQUIRED = ('runtime/python/run_python.sh', 'runtime/python/bin/python3.12')


def progress(phase, **values):
    print(json.dumps(dict(phase=phase, **values)), flush=True)


def sha256_file(path):
    with open(path, 'rb') as stream:
        return stream_digest(stream)


def model_members(model_dir):
    model_dir = Path(model_dir).resolve()
    files = sorted(p for p in model_dir.rglob('*') if p.is_file()
                   and not any(part.startswith('.') for part in p.relative_to(model_dir).parts))
    members, manifest = [], []
    for path in files:
        rel = path.relative_to(model_dir).as_posix()
        if '..' in rel.split('/'):
            raise ValueError('UNSAFE_MODEL_FILE:' + rel)
        size, digest = sha256_file(path)
        members.append((MODEL_PREFIX + rel, path, dict(bytes=size, sha256=digest, mode=0o644)))
        manifest.append(dict(path=rel, size=size, sha256=digest))
    names = {m['path'] for m in manifest}
    if 'config.json' not in names or not any(n.endswith('.safetensors') for n in names):
        raise ValueError('MODEL_DIR_NEEDS_CONFIG_AND_SAFETENSORS')
    progress('model_hashed', files=len(members), bytes=sum(m['size'] for m in manifest))
    return members, manifest


def write_file(target, name, path):
    info = file_info(name)
    info.compress_type = zipfile.ZIP_STORED if name.endswith('.safetensors') else zipfile.ZIP_DEFLATED
    info.file_size = Path(path).stat().st_size
    with open(path, 'rb') as source, target.open(info, 'w', force_zip64=True) as stream:
        shutil.copyfileobj(source, stream, 8 << 20)


def build(source_zip, source_sha256, model_dir, model_id, model_revision, output, repo=None):
    repo = Path(repo or Path(__file__).resolve().parents[1])
    source_zip, output = Path(source_zip), Path(output)
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    for path in (output, partial, receipt_path, checksum_path):
        if path.exists():
            raise FileExistsError(path)
    code = {name: (repo / src).read_bytes().replace(b'\r\n', b'\n') for name, src in CODE.items()}
    members, files_manifest = model_members(model_dir)
    code['JUDGE_MANIFEST.json'] = json_bytes(dict(repository=model_id, revision=model_revision,
                                                  files=files_manifest))
    progress('verify_source_zip_sha256', bytes=source_zip.stat().st_size)
    before = source_zip.stat()
    if sha256_file(source_zip)[1] != source_sha256:
        raise ValueError('SOURCE_ZIP_SHA256_MISMATCH')
    output.parent.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(source_zip) as source:
        entries = zip_entries(source)
        missing = [name for name in REQUIRED if name not in entries]
        if missing:
            raise ValueError('SOURCE_RUNTIME_MISSING:' + ','.join(missing))
        original_raw = source.read('MANIFEST.json')
        manifest = json_read(original_raw)
        files = manifest['files']
        if set(files) != set(entries) - {'MANIFEST.json'}:
            raise ValueError('SOURCE_FILE_SET_MISMATCH')
        for name, row in files.items():
            record_valid(row)
            if row['bytes'] != entries[name].file_size:
                raise ValueError('SOURCE_METADATA_MISMATCH:' + name)
        dropped = sorted(n for n in files if n.startswith('model/') or n in DROP_NAMES)
        expected = {n: dict(r) for n, r in files.items() if n not in dropped}
        for name, data in code.items():
            mode = expected.get(name, {}).get('mode', 0o644)
            expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
        for name, _, record in members:
            if name in expected:
                raise ValueError('MODEL_NAME_COLLISION:' + name)
            expected[name] = record
        provenance = dict(source_zip_sha256=source_sha256,
                          source_manifest_sha256=hashlib.sha256(original_raw).hexdigest(),
                          profile='single-pass-judge-v1', model=dict(repository=model_id, revision=model_revision,
                                                                    directory=MODEL_PREFIX.rstrip('/')),
                          dropped=len(dropped), replaced_or_added_code={n: expected[n]['sha256'] for n in code})
        final = dict(manifest, files=expected, judge_build=provenance, profile='SINGLE_PASS_JUDGE')
        final_raw = json_bytes(final)
        expected_all = dict(expected, **{'MANIFEST.json': dict(bytes=len(final_raw),
                            sha256=hashlib.sha256(final_raw).hexdigest(), mode=0o644)})
        ordered = sorted(entries.values(), key=lambda i: i.header_offset)
        boundaries = {i.filename: ordered[k + 1].header_offset if k + 1 < len(ordered) else source.start_dir
                      for k, i in enumerate(ordered)}
        progress('write', dropped=len(dropped), models=len(members), code=len(code))
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
                for name, path, _ in members:
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
                    with check.open(info) as stream:
                        size, digest = stream_digest(stream)
                    row = expected_all[name]
                    if (size, digest, stat.S_IMODE(info.external_attr >> 16)) != (row['bytes'], row['sha256'], row['mode']):
                        raise ValueError('FINAL_MEMBER_MISMATCH:' + name)
            after = source_zip.stat()
            if (before.st_size, before.st_mtime_ns) != (after.st_size, after.st_mtime_ns):
                raise ValueError('SOURCE_CHANGED_DURING_BUILD')
            size, digest = sha256_file(partial)
            result = dict(output=str(output), bytes=size, sha256=digest, under_cap=size < CAP,
                          files=len(expected_all), all_members_verified=True, judge_build=provenance)
            os.replace(partial, output)
            receipt_path.write_text(json.dumps(result, indent=2), encoding='utf-8')
            checksum_path.write_text(digest + '  ' + output.name + '\n', encoding='ascii')
            progress('ready', bytes=size, sha256=digest, under_cap=size < CAP)
            return result
        finally:
            partial.unlink(missing_ok=True)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--source-zip', type=Path, required=True)
    parser.add_argument('--source-sha256', required=True)
    parser.add_argument('--model-dir', type=Path, required=True)
    parser.add_argument('--model-id', required=True)
    parser.add_argument('--model-revision', required=True)
    parser.add_argument('--output', type=Path, required=True)
    args = parser.parse_args()
    build(args.source_zip, args.source_sha256, args.model_dir, args.model_id, args.model_revision, args.output)
