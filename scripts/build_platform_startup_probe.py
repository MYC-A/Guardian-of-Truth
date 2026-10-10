"""Build the diagnostic startup-probe ZIP: bundled runtime + model metadata, no weights.

Source is either the competition ZIP (--source-zip) or an unpacked stage directory
(--source-root) containing runtime/ and model/<REVISION>/. Weight files are never
copied; the probe starts vLLM with --load-format dummy. Never submit for scoring.
"""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shutil
import stat
import zipfile

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
WEIGHT_SUFFIXES = ('.safetensors', '.bin', '.pt', '.pth', '.gguf', '.npz')
METADATA_LIMIT = 64 << 20  # tokenizer.json is ~11 MB; anything bigger is not metadata
MODEL_PREFIX = f'model/{REVISION}/'


def selected(name, size):
    """Return the probe-archive category of a source entry, or None to skip it."""
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name:
        raise ValueError('UNSAFE_SOURCE_ENTRY:' + name)
    if name.startswith('runtime/'):
        return 'runtime'
    if name.startswith(MODEL_PREFIX):
        if name.endswith('/'):
            return 'model'
        if path.suffix.lower() in WEIGHT_SUFFIXES or size > METADATA_LIMIT:
            return None
        return 'model'
    return None


def probe_payload(root):
    return {
        'scripts/predict.py': (root / 'submission/platform_startup_probe.py').read_bytes(),
        'scripts/platform_environment_probe.py': (root / 'submission/platform_environment_probe.py').read_bytes(),
        'probe_build_backend.py': (root / 'submission/probe_build_backend.py').read_bytes(),
        'pyproject.toml': b'[build-system]\nrequires = []\nbuild-backend = "probe_build_backend"\nbackend-path = ["."]\n',
        'DIAGNOSTIC_ONLY_NOT_FOR_SCORING.txt': (
            b'Startup diagnostic, not a competition solution. No input reads, no predictions, dummy weights.\n'
            b'Exit code 2 after GUARDIAN_STARTUP_PROBE done is intentional. Keep and share the platform log.\n'),
        'README.md': b'# Guardian startup probe\n\nUpload only for diagnosis, never submit for scoring.\n',
    }


def file_info(name, mode=0o644):
    info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFREG | mode) << 16
    info.compress_type = zipfile.ZIP_DEFLATED
    return info


def dir_info(name):
    info = zipfile.ZipInfo(name.rstrip('/') + '/', date_time=(1980, 1, 1, 0, 0, 0))
    info.create_system = 3
    info.external_attr = (stat.S_IFDIR | 0o755) << 16 | 0x10
    return info


def source_entries(source_zip=None, source_root=None):
    """Yield (name, size, mode, is_dir, opener) from either source kind."""
    if source_zip is not None:
        archive = zipfile.ZipFile(source_zip)
        for info in archive.infolist():
            mode = (info.external_attr >> 16) & 0o7777
            symlink = stat.S_ISLNK(info.external_attr >> 16)
            yield (info.filename, info.file_size, mode or (0o755 if info.is_dir() else 0o644),
                   info.is_dir(), symlink,
                   (lambda info=info: archive.read(info)) if symlink else (lambda info=info: archive.open(info)))
        archive.close()
        return
    source_root = Path(source_root)
    for top in ('runtime', 'model'):
        base = source_root / top
        if not base.exists():
            continue
        for path in sorted([base, *base.rglob('*')]):
            name = path.relative_to(source_root).as_posix()
            if path.is_symlink():
                target = str(path.readlink()).encode()
                yield name, len(target), 0o777, False, True, (lambda target=target: target)
                continue
            if path.is_dir():
                yield name + '/', 0, 0o755, True, False, None
            else:
                yield (name, path.stat().st_size, stat.S_IMODE(path.stat().st_mode), False, False,
                       (lambda path=path: path.open('rb')))


def build(output, source_zip=None, source_root=None):
    if (source_zip is None) == (source_root is None):
        raise ValueError('EXACTLY_ONE_SOURCE_REQUIRED')
    root = Path(__file__).resolve().parents[1]
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    payload = probe_payload(root)
    counts = dict(runtime=0, model=0, skipped_weights_or_other=0)
    copied_bytes = 0
    model_files = []
    with output.open('xb') as raw, zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED,
                                                   allowZip64=True) as archive:
        written_dirs = set()
        for name in ('scripts/',):
            archive.writestr(dir_info(name), b'')
            written_dirs.add(name)
        for name, value in sorted(payload.items()):
            archive.writestr(file_info(name), value)
        for name, size, mode, is_dir, symlink, opener in source_entries(source_zip, source_root):
            category = selected(name, size)
            if category is None:
                counts['skipped_weights_or_other'] += 1
                continue
            if symlink:
                # Mirror the real archive: keep the link entry (Unix mode S_IFLNK, target as data).
                target = opener()
                info = zipfile.ZipInfo(name, date_time=(1980, 1, 1, 0, 0, 0))
                info.create_system = 3
                info.external_attr = (stat.S_IFLNK | 0o777) << 16
                archive.writestr(info, target)
                counts[category] += 1
                continue
            if is_dir:
                if name not in written_dirs:
                    archive.writestr(dir_info(name), b'')
                    written_dirs.add(name)
                continue
            info = file_info(name, 0o755 if mode & 0o111 else 0o644)
            with opener() as source, archive.open(info, 'w', force_zip64=size > (1 << 31)) as target:
                shutil.copyfileobj(source, target, 8 << 20)
            counts[category] += 1
            copied_bytes += size
            if category == 'model':
                model_files.append(PurePosixPath(name).name)
        if 'config.json' not in model_files:
            raise ValueError('MODEL_CONFIG_MISSING_IN_SOURCE')
        if not counts['runtime']:
            raise ValueError('RUNTIME_MISSING_IN_SOURCE')
        manifest = dict(purpose='DIAGNOSTIC_ONLY_NOT_FOR_SCORING', expected_exit_code=2, revision=REVISION,
                        load_format='dummy', counts=counts, copied_uncompressed_bytes=copied_bytes,
                        model_metadata_files=sorted(model_files),
                        probe_files={name: hashlib.sha256(value).hexdigest() for name, value in payload.items()})
        archive.writestr(file_info('MANIFEST.json'), json.dumps(manifest, indent=2, sort_keys=True) + '\n')
    with zipfile.ZipFile(output) as check:
        names = check.namelist()
        assert len(names) == len(set(names)), 'DUPLICATE_ENTRIES'
        assert not any(PurePosixPath(n).suffix.lower() in WEIGHT_SUFFIXES for n in names), 'WEIGHTS_LEAKED'
        assert all(not n.startswith('/') and '..' not in PurePosixPath(n).parts for n in names)
        for name, value in payload.items():
            assert check.read(name) == value
    digest = hashlib.sha256()
    with output.open('rb') as stream:
        for chunk in iter(lambda: stream.read(8 << 20), b''):
            digest.update(chunk)
    receipt = dict(output=str(output), bytes=output.stat().st_size, sha256=digest.hexdigest(), **manifest)
    with output.with_suffix('.verification.json').open('x', encoding='utf-8') as target:
        json.dump(receipt, target, indent=2)
    return receipt


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-zip', type=Path)
    group.add_argument('--source-root', type=Path)
    options = parser.parse_args()
    print(json.dumps(build(options.output, options.source_zip, options.source_root), indent=2))
