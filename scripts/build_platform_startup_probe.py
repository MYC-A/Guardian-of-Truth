"""Build the diagnostic startup-probe ZIP: bundled runtime + model metadata, no weights.

Source is either the competition ZIP (--source-zip) or an unpacked stage directory
(--source-root) containing runtime/ and model/<REVISION>/. Weight files are never
copied; the probe starts vLLM with --load-format dummy. Never submit for scoring.
"""
import argparse
import copy
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import struct
import zipfile

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
WEIGHT_SUFFIXES = ('.safetensors', '.bin', '.pt', '.pth', '.gguf', '.npz')
METADATA_LIMIT = 64 << 20  # tokenizer.json is ~11 MB; anything bigger is not metadata
MODEL_PREFIX = f'model/{REVISION}/'


def selected(name, size):
    """Return the probe-archive category of a source entry, or None to skip it."""
    path = PurePosixPath(name)
    if path.is_absolute() or '..' in path.parts or '\\' in name or ':' in name or '\x00' in name:
        raise ValueError('UNSAFE_SOURCE_ENTRY:' + name)
    if name.startswith('runtime/'):
        return 'runtime'
    if name.startswith('licenses/'):
        return 'licenses'
    if name.startswith(MODEL_PREFIX):
        if name.endswith('/'):
            return 'model'
        if path.suffix.lower() in WEIGHT_SUFFIXES or size > METADATA_LIMIT:
            return None
        return 'model'
    return None


def stream_digest(stream):
    digest = hashlib.sha256()
    size = 0
    for chunk in iter(lambda: stream.read(8 << 20), b''):
        digest.update(chunk)
        size += len(chunk)
    return size, digest.hexdigest()


def raw_copy(source, target, info, boundary):
    """Copy one validated ZIP record, preserving compressed bytes and Unix modes.

    zipfile has no compressed-member copy API. Its central-directory writer uses
    these documented-in-source bookkeeping fields; tests cover ZIP64 and both
    streaming descriptors and seekable headers. Final normal zipfile reads check
    CRC and manifest SHA for every copied entry before publishing.
    """
    source.fp.seek(info.header_offset)
    header = source.fp.read(30)
    if len(header) != 30 or header[:4] != b'PK\x03\x04' or info.flag_bits & 1:
        raise ValueError('INVALID_OR_ENCRYPTED_LOCAL_HEADER:' + info.filename)
    fields = struct.unpack('<4s5H3I2H', header)
    flags, method, crc, compressed, plain, name_len, extra_len = fields[2], fields[3], fields[6], fields[7], fields[8], fields[9], fields[10]
    name = source.fp.read(name_len)
    extra = source.fp.read(extra_len)
    if name.decode('utf-8' if flags & 0x800 else 'cp437') != info.filename or flags != info.flag_bits or method != info.compress_type:
        raise ValueError('LOCAL_CENTRAL_MISMATCH:' + info.filename)
    data_end = info.header_offset + 30 + name_len + extra_len + info.compress_size
    record_end = data_end
    if flags & 8:
        source.fp.seek(data_end)
        descriptor = source.fp.read(min(24, boundary - data_end))
        widths = (8, 4) if compressed == 0xffffffff or plain == 0xffffffff else (4, 8)
        matched = False
        for offset in (4, 0):
            if offset and descriptor[:4] != b'PK\x07\x08':
                continue
            for width in widths:
                length = offset + 4 + 2 * width
                if len(descriptor) < length:
                    continue
                values = struct.unpack('<I' + ('Q' if width == 8 else 'I') * 2, descriptor[offset:length])
                if values == (info.CRC, info.compress_size, info.file_size):
                    record_end = data_end + length
                    matched = True
                    break
            if matched:
                break
        if not matched:
            raise ValueError('INVALID_DATA_DESCRIPTOR:' + info.filename)
    elif crc != info.CRC or (compressed != 0xffffffff and compressed != info.compress_size) or (plain != 0xffffffff and plain != info.file_size):
        raise ValueError('LOCAL_SIZE_CRC_MISMATCH:' + info.filename)
    if record_end > boundary or data_end < info.header_offset:
        raise ValueError('OVERLAPPING_SOURCE_RECORD:' + info.filename)
    clone = copy.copy(info)
    target.fp.seek(target.start_dir)
    clone.header_offset = target.fp.tell()
    source.fp.seek(info.header_offset)
    remaining = record_end - info.header_offset
    while remaining:
        chunk = source.fp.read(min(8 << 20, remaining))
        if not chunk:
            raise ValueError('TRUNCATED_SOURCE_RECORD:' + info.filename)
        target.fp.write(chunk)
        remaining -= len(chunk)
    target.start_dir = target.fp.tell()
    target.filelist.append(clone)
    target.NameToInfo[clone.filename] = clone
    target._didModify = True


def safe_link(name, data):
    target = data.decode('utf-8')
    path = PurePosixPath(target)
    if path.is_absolute() or '\\' in target or ':' in target or '\x00' in target:
        raise ValueError('UNSAFE_SYMLINK:' + name)
    parts = list(PurePosixPath(name).parent.parts)
    for part in path.parts:
        if part == '..':
            if not parts:
                raise ValueError('UNSAFE_SYMLINK:' + name)
            parts.pop()
        elif part != '.':
            parts.append(part)


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
    for top in ('runtime', 'model', 'licenses'):
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


def build(output, source_zip=None, source_root=None, *, repair_toolchain=False):
    if (source_zip is None) == (source_root is None):
        raise ValueError('EXACTLY_ONE_SOURCE_REQUIRED')
    root = Path(__file__).resolve().parents[1]
    output = Path(output)
    partial = output.with_name(output.name + '.partial')
    receipt_path = output.with_suffix('.verification.json')
    checksum_path = output.with_name(output.name + '.sha256')
    if source_root is not None:
        try:
            relative_output = output.resolve().relative_to(Path(source_root).resolve())
        except ValueError:
            pass
        else:
            if relative_output.parts and relative_output.parts[0] in ('runtime', 'model', 'licenses'):
                raise ValueError('OUTPUT_INSIDE_SELECTED_SOURCE_TREE')
    output.parent.mkdir(parents=True, exist_ok=True)
    for path in (output, partial, receipt_path, checksum_path):
        if path.exists():
            raise FileExistsError(str(path))
    payload = probe_payload(root)
    counts = dict(runtime=0, model=0, licenses=0, skipped_weights_or_other=0)
    model_files, expected = [], {}
    copied_bytes = 0
    source = None
    source_identity = dict(whole_source_sha256_verified=False)
    patches, changes = {}, {}
    try:
        if source_zip is not None:
            source_zip = Path(source_zip)
            before = source_zip.stat()
            source = zipfile.ZipFile(source_zip)
            infos = source.infolist()
            names = [info.filename for info in infos]
            if len(names) != len(set(names)):
                raise ValueError('DUPLICATE_SOURCE_ENTRIES')
            for info in infos:
                selected(info.filename, info.file_size)  # Validate even omitted names.
            ordered = sorted(infos, key=lambda i: i.header_offset)
            boundaries = {info.filename: (ordered[index + 1].header_offset if index + 1 < len(ordered) else source.start_dir)
                          for index, info in enumerate(ordered)}
            if len({i.header_offset for i in infos}) != len(infos):
                raise ValueError('DUPLICATE_SOURCE_OFFSETS')
            source.fp.seek(source.start_dir)
            _, central_sha = stream_digest(source.fp)
            source_identity.update(path=str(source_zip), bytes=before.st_size, central_directory_and_end_sha256=central_sha)
            manifest_files = None
            if 'MANIFEST.json' in names:
                if source.getinfo('MANIFEST.json').file_size > 64 << 20:
                    raise ValueError('SOURCE_MANIFEST_TOO_LARGE')
                manifest_raw = source.read('MANIFEST.json')
                manifest_files = json.loads(manifest_raw)['files']
                if not isinstance(manifest_files, dict):
                    raise ValueError('INVALID_SOURCE_MANIFEST')
                source_identity['manifest_sha256'] = hashlib.sha256(manifest_raw).hexdigest()
            entries = [(i.filename, i.file_size, stat.S_IMODE(i.external_attr >> 16), i.is_dir(),
                        stat.S_ISLNK(i.external_attr >> 16), lambda i=i: source.open(i)) for i in infos]
            if repair_toolchain:
                try:
                    from .repair_vllm_toolchain import archive_patches
                except ImportError:
                    from repair_vllm_toolchain import archive_patches
                patches, changes = archive_patches(source)
        else:
            if repair_toolchain:
                raise ValueError('TOOLCHAIN_REPAIR_REQUIRES_SOURCE_ZIP')
            entries = source_entries(source_root=source_root)
            manifest_files = None
        with partial.open('xb') as raw, zipfile.ZipFile(raw, 'w', compression=zipfile.ZIP_DEFLATED, allowZip64=True) as archive:
            archive.writestr(dir_info('scripts/'), b'')
            for name, value in sorted(payload.items()):
                archive.writestr(file_info(name), value)
                expected[name] = dict(bytes=len(value), sha256=hashlib.sha256(value).hexdigest(), mode=0o644)
            seen = set(payload) | {'scripts/', 'MANIFEST.json'}
            for name, size, mode, is_dir, symlink, opener in entries:
                category = selected(name, size)
                if category is None:
                    counts['skipped_weights_or_other'] += 1
                    continue
                if name in seen:
                    raise ValueError('DUPLICATE_SELECTED_ENTRY:' + name)
                seen.add(name)
                mode = mode or (0o755 if is_dir else 0o644)
                if is_dir:
                    if size:
                        raise ValueError('NONEMPTY_DIRECTORY_ENTRY:' + name)
                    if source is not None:
                        raw_copy(source, archive, source.getinfo(name), boundaries[name])
                    else:
                        archive.writestr(dir_info(name), b'')
                    continue
                if source is not None and manifest_files is not None:
                    record = manifest_files.get(name)
                    if not isinstance(record, dict) or record.get('bytes') != size or record.get('mode') != mode or len(record.get('sha256', '')) != 64:
                        raise ValueError('SOURCE_MANIFEST_MISMATCH:' + name)
                    expected[name] = dict(record)
                elif source is not None:
                    with opener() as stream:
                        actual_size, digest = stream_digest(stream)
                    expected[name] = dict(bytes=actual_size, sha256=digest, mode=mode)
                if symlink:
                    data = source.read(name) if source is not None else opener()
                    safe_link(name, data)
                if name in patches:
                    data, mode = patches[name]
                    size = len(data)
                    archive.writestr(file_info(name, mode), data)
                    expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
                elif source is not None:
                    raw_copy(source, archive, source.getinfo(name), boundaries[name])
                elif symlink:
                    info = file_info(name, mode)
                    info.external_attr = (stat.S_IFLNK | mode) << 16
                    archive.writestr(info, data)
                    expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
                else:
                    info = file_info(name, mode)
                    with opener() as stream, archive.open(info, 'w', force_zip64=size > (1 << 31)) as target:
                        digest = hashlib.sha256()
                        while True:
                            chunk = stream.read(8 << 20)
                            if not chunk:
                                break
                            target.write(chunk)
                            digest.update(chunk)
                    expected[name] = dict(bytes=size, sha256=digest.hexdigest(), mode=mode)
                counts[category] += 1
                copied_bytes += size
                if category == 'model':
                    model_files.append(PurePosixPath(name).name)
            if 'config.json' not in model_files:
                raise ValueError('MODEL_CONFIG_MISSING_IN_SOURCE')
            if not counts['runtime']:
                raise ValueError('RUNTIME_MISSING_IN_SOURCE')
            for name in sorted(set(patches) - seen):
                data, mode = patches[name]
                archive.writestr(file_info(name, mode), data)
                expected[name] = dict(bytes=len(data), sha256=hashlib.sha256(data).hexdigest(), mode=mode)
                counts['runtime'] += 1
                copied_bytes += len(data)
            manifest = dict(purpose='DIAGNOSTIC_ONLY_NOT_FOR_SCORING', expected_exit_code=2, revision=REVISION,
                            load_format='dummy', counts=counts, copied_uncompressed_bytes=copied_bytes,
                            model_metadata_files=sorted(model_files), files=expected, source_identity=source_identity,
                            probe_files={name: hashlib.sha256(value).hexdigest() for name, value in payload.items()},
                            toolchain_wrapper_repairs=changes)
            archive.writestr(file_info('MANIFEST.json'), json.dumps(manifest, indent=2, sort_keys=True) + '\n')
        with zipfile.ZipFile(partial) as check:
            names = check.namelist()
            if len(names) != len(set(names)):
                raise ValueError('DUPLICATE_ENTRIES')
            for info in check.infolist():
                selected(info.filename, info.file_size)
                if info.filename.startswith(MODEL_PREFIX) and not info.is_dir() and selected(info.filename, info.file_size) != 'model':
                    raise ValueError('MODEL_WEIGHTS_LEAKED')
                if info.is_dir() or info.filename == 'MANIFEST.json':
                    continue
                with check.open(info) as stream:
                    actual_size, digest = stream_digest(stream)  # zipfile also verifies CRC.
                record = expected[info.filename]
                if actual_size != record['bytes'] or digest != record['sha256'] or stat.S_IMODE(info.external_attr >> 16) != record['mode']:
                    raise ValueError('COPIED_MEMBER_VERIFICATION_FAILED:' + info.filename)
        if source is not None:
            after = source_zip.stat()
            if (before.st_size, before.st_mtime_ns, before.st_ino) != (after.st_size, after.st_mtime_ns, after.st_ino):
                raise ValueError('SOURCE_CHANGED_DURING_BUILD')
        with partial.open('rb') as stream:
            size, digest = stream_digest(stream)
        receipt = dict(output=str(output), bytes=size, sha256=digest, all_copied_members_sha256_and_crc_verified=True, **manifest)
        # Exclusive publication: hard-link creates the final name without replacing
        # a file created by another process; same-directory NTFS/POSIX supported.
        os.link(partial, output)
        partial.unlink()
        with receipt_path.open('x', encoding='utf-8') as target:
            json.dump(receipt, target, indent=2)
        with checksum_path.open('x', encoding='ascii') as target:
            target.write(digest + '  ' + output.name + '\n')
        return receipt
    finally:
        if source is not None:
            source.close()
        if partial.exists():
            partial.unlink()


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--repair-toolchain', action='store_true')
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument('--source-zip', type=Path)
    group.add_argument('--source-root', type=Path)
    options = parser.parse_args()
    print(json.dumps(build(options.output, options.source_zip, options.source_root,
                           repair_toolchain=options.repair_toolchain), indent=2))
