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
for _module in ('__init__', 'model', 'parser', 'system', 'catalog', 'values', 'provenance', 'features', 'audit'):
    _name = f'src/guardian_truth/transcript/{_module}.py'
    CODE[_name] = _name
REQUIRED = ('runtime/python/run_python.sh', 'runtime/python/bin/python3.12')
# Runtime entry points. judge_stage starts u2_context as `python -m ...`, so no import leads to it.
ENTRY_POINTS = ('scripts/judge_submission.py', 'scripts/judge_stage.py', 'src/guardian_truth/judge/u2_context.py')
ENCODER_PREFIX = 'model/encoder/'
# Must equal guardian_truth.judge.dense_encoder PINNED_* / REQUIRED_FILES (checked by tests/test_judge_u2.py).
ENCODER_PIN = ('sentence-transformers/paraphrase-multilingual-MiniLM-L12-v2', 'e8f8c211226b894fcb81acc59f3b34ba3efd5f42')
ENCODER_REQUIRED = ('config.json', 'model.safetensors', 'tokenizer.json', 'tokenizer_config.json',
                    'sentence_bert_config.json')


class MissingRuntimeModule(ImportError):
    """A guardian_truth module imported by the runtime closure does not exist in the repository."""


def _module_files(repo, module):
    """-> files of `module` (package __init__ files on the way + the module itself), or None if it does not
    exist. A directory without __init__.py counts as a namespace package."""
    parts, out = module.split('.'), []
    for k in range(1, len(parts) + 1):
        init = Path('src', *parts[:k], '__init__.py')
        if (repo / init).is_file():
            out.append(init.as_posix())
    leaf = Path('src', *parts[:-1], parts[-1] + '.py')
    if (repo / leaf).is_file():
        return out + [leaf.as_posix()]
    if (repo / Path('src', *parts)).is_dir():
        return out
    return None


def runtime_closure(repo, entry_points=ENTRY_POINTS, strict=True):
    """Repository modules (src/...) reached from the entry points through both import forms, `import
    guardian_truth.x` and `from guardian_truth.x import y` (absolute or relative, lazy imports inside functions
    included), with every package __init__.py on the way. In `from M import y`, y is a submodule only if its
    file exists; otherwise it is an attribute of M. A module that is imported but does not exist raises
    MissingRuntimeModule (strict) or is returned in the second value (strict=False)."""
    repo = Path(repo)
    todo, seen, missing = list(entry_points), set(), []

    def need(module, where):
        files = _module_files(repo, module)
        if files is None:
            missing.append('%s (imported by %s)' % (module, where))
        else:
            todo.extend(f for f in files if f not in seen)

    while todo:
        path = todo.pop()
        if path in seen:
            continue
        seen.add(path)
        tree = ast.parse((repo / path).read_text(encoding='utf-8'), filename=path)
        module = path[len('src/'):-len('.py')].replace('/', '.') if path.startswith('src/') else ''
        package = module.rsplit('.', 1)[0] if '.' in module else ''
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    if alias.name == 'guardian_truth' or alias.name.startswith('guardian_truth.'):
                        need(alias.name, path)
            elif isinstance(node, ast.ImportFrom):
                if node.level:
                    base = package.split('.') if package else []
                    base = base[:len(base) - (node.level - 1)] if node.level > 1 else base
                    target = '.'.join(base + ([node.module] if node.module else []))
                else:
                    target = node.module or ''
                if not (target == 'guardian_truth' or target.startswith('guardian_truth.')):
                    continue
                need(target, path)
                for alias in node.names:
                    files = _module_files(repo, target + '.' + alias.name)
                    if files:
                        todo.extend(f for f in files if f not in seen)
    closure = sorted(p for p in seen if p.startswith('src/'))
    if strict and missing:
        raise MissingRuntimeModule('RUNTIME_MODULE_MISSING: ' + '; '.join(sorted(set(missing))))
    return (closure, sorted(set(missing))) if not strict else closure


RUNTIME_CLOSURE, RUNTIME_MISSING = runtime_closure(Path(__file__).resolve().parents[1], strict=False)
for _name in RUNTIME_CLOSURE:
    CODE.setdefault(_name, _name)


def progress(phase, **values):
    print(json.dumps(dict(phase=phase, **values)), flush=True)


def sha256_file(path):
    with open(path, 'rb') as stream:
        return stream_digest(stream)


def check_encoder_dir(encoder_dir, encoder_id, encoder_revision):
    """An explicitly passed encoder must be the pinned one and complete; otherwise u2_dense would silently
    become its lexical fallback inside the archive. ENCODER_SOURCE.json (scripts/fetch_judge_encoder.py), when
    present, must name the same model and every listed file must still have its size and SHA256."""
    encoder_dir = Path(encoder_dir)
    if (encoder_id, encoder_revision) != ENCODER_PIN:
        raise ValueError('ENCODER_NOT_PINNED: %s@%s' % (encoder_id, encoder_revision))
    missing = [name for name in ENCODER_REQUIRED if not (encoder_dir / name).is_file()]
    if missing:
        raise ValueError('ENCODER_DIR_INCOMPLETE:' + ','.join(missing))
    source = encoder_dir / 'ENCODER_SOURCE.json'
    if source.is_file():
        info = json.loads(source.read_text(encoding='utf-8'))
        if (info.get('repository'), info.get('revision')) != ENCODER_PIN:
            raise ValueError('ENCODER_SOURCE_MISMATCH')
        for row in info.get('files', []):
            path = encoder_dir / row['path']
            if not path.is_file() or path.stat().st_size != row['size'] or sha256_file(path)[1] != row['sha256']:
                raise ValueError('ENCODER_FILE_CHANGED:' + row['path'])


def model_members(model_dir, prefix=MODEL_PREFIX):
    model_dir = Path(model_dir).resolve()
    files = sorted(p for p in model_dir.rglob('*') if p.is_file()
                   and not any(part.startswith('.') for part in p.relative_to(model_dir).parts))
    members, manifest = [], []
    for path in files:
        rel = path.relative_to(model_dir).as_posix()
        if '..' in rel.split('/'):
            raise ValueError('UNSAFE_MODEL_FILE:' + rel)
        size, digest = sha256_file(path)
        members.append((prefix + rel, path, dict(bytes=size, sha256=digest, mode=0o644)))
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


def build(source_zip, source_sha256, model_dir, model_id, model_revision, output, repo=None,
          encoder_dir=None, encoder_id=None, encoder_revision=None, context_mode=None,
          judge_config=None, source_revision=None):
    repo = Path(repo or Path(__file__).resolve().parents[1])
    if context_mode is not None and context_mode not in ('legacy', 'u2', 'u2_dense'):
        raise ValueError('INVALID_BUILD_CONTEXT_MODE:' + str(context_mode))
    if context_mode == 'u2_dense' and encoder_dir is None:
        raise ValueError('DENSE_BUILD_REQUIRES_ENCODER')
    if (encoder_dir is None) != (encoder_revision is None) or (encoder_dir is None) != (encoder_id is None):
        raise ValueError('ENCODER_NEEDS_DIR_ID_AND_REVISION')
    source_zip, output = Path(source_zip), Path(output)
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    for path in (output, partial, receipt_path, checksum_path):
        if path.exists():
            raise FileExistsError(path)
    closure = runtime_closure(repo)          # raises MissingRuntimeModule
    unpacked = sorted(set(closure) - set(CODE))
    if unpacked:
        raise ValueError('RUNTIME_MODULES_NOT_PACKED:' + ','.join(unpacked))
    code = {name: (repo / src).read_bytes().replace(b'\r\n', b'\n') for name, src in CODE.items()}
    config = json.loads(Path(judge_config).read_text(encoding='utf-8')) if judge_config else json.loads(code['JUDGE_CONFIG.json'])
    if context_mode is not None:
        config['context_mode'] = context_mode
    from guardian_truth.judge.prompting import score_keys
    from guardian_truth.judge.decision import validate_aggregate
    from guardian_truth.judge.blind_review import validate_review_config
    validate_aggregate(config, [k for k, _, _ in score_keys(config)])
    review = validate_review_config(config)
    code['JUDGE_CONFIG.json'] = json_bytes(config)
    if review['review_mode'] != 'off':
        code['README.md'] = (repo / 'docs/judge_20261013/README_BLIND_REVIEW_SUBMISSION.md').read_bytes().replace(b'\r\n', b'\n')
    elif config.get('profile') == 'judge-6q-mean-z-20261018':
        code['README.md'] = (repo / 'docs/judge_20261013/README_6Q_SUBMISSION.md').read_bytes().replace(b'\r\n', b'\n')
    elif config.get('profile') == 'judge-6q-max-logit-20261018':
        code['README.md'] = (repo / 'docs/judge_20261013/README_6Q_MAX.md').read_bytes().replace(b'\r\n', b'\n')
    members, files_manifest = model_members(model_dir)
    judge_manifest = dict(repository=model_id, revision=model_revision, files=files_manifest)
    if encoder_dir is not None:
        check_encoder_dir(encoder_dir, encoder_id, encoder_revision)
        encoder_members, encoder_files = model_members(encoder_dir, ENCODER_PREFIX)
        members += encoder_members
        judge_manifest['encoder'] = dict(repository=encoder_id, revision=encoder_revision,
                                         directory=ENCODER_PREFIX.rstrip('/'), files=encoder_files)
    code['JUDGE_MANIFEST.json'] = json_bytes(judge_manifest)
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
        # Every runtime module is written from this repository; older source copies of other modules stay.
        progress('source_modules_not_replaced', count=sum(1 for n in files if n.startswith('src/guardian_truth/')
                                                         and n.endswith('.py') and n not in code))
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
                          profile=config.get('profile', 'single-pass-judge'), source_revision=source_revision,
                          config_sha256=hashlib.sha256(code['JUDGE_CONFIG.json']).hexdigest(),
                          review_mode=review['review_mode'], model=dict(repository=model_id, revision=model_revision,
                                                                    directory=MODEL_PREFIX.rstrip('/')),
                          context_mode=config.get('context_mode', 'legacy'),
                          questions=config.get('questions', ['overall']), aggregate=config.get('aggregate', 'primary'),
                          aggregate_keys=config.get('aggregate_keys', []),
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
    parser.add_argument('--encoder-dir', type=Path, default=None, help='u2_dense encoder (scripts/fetch_judge_encoder.py)')
    parser.add_argument('--encoder-id', default=None)
    parser.add_argument('--encoder-revision', default=None)
    parser.add_argument('--context-mode', choices=('legacy', 'u2', 'u2_dense'), default=None,
                        help='Override the context mode in the ZIP only; repository defaults are unchanged')
    parser.add_argument('--judge-config', type=Path, default=None,
                        help='Explicit opt-in archive config; repository production defaults stay unchanged')
    parser.add_argument('--source-revision', default=None, help='Pinned code commit recorded in the archive manifest')
    args = parser.parse_args()
    build(args.source_zip, args.source_sha256, args.model_dir, args.model_id, args.model_revision, args.output,
          encoder_dir=args.encoder_dir, encoder_id=args.encoder_id, encoder_revision=args.encoder_revision,
          context_mode=args.context_mode, judge_config=args.judge_config, source_revision=args.source_revision)
