"""Operator-only resumable pinned FP8 download directly from Hugging Face."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import os
import re
import threading
import time
import urllib.parse
import urllib.request


def checksum(path):
    h = hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            h.update(block)
    return h.hexdigest()


def main():
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument('--manifest', type=Path, required=True)
    p.add_argument('--destination', type=Path, required=True)
    p.add_argument('--workers', type=int, default=8)
    p.add_argument('--duration', type=int, default=7200)
    args = p.parse_args()
    if not 1 <= args.workers <= 8 or args.duration < 1:
        p.error('invalid download budget')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    revision = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
    if manifest['repository'] != 'Qwen/Qwen3.8-27B-FP8' or manifest['revision'] != revision:
        raise ValueError('PINNED_MODEL_REQUIRED')
    entries = manifest['files']
    names = [e['path'] for e in entries]
    if len(set(names)) != len(names) or any(n + '.partial' in names for n in names):
        raise ValueError('DUPLICATE_ASSETS')
    for e in entries:
        n = e['path']
        if (not n or PurePosixPath(n).as_posix() != n or PurePosixPath(n).is_absolute()
                or '..' in PurePosixPath(n).parts or '\\' in n or ':' in n
                or type(e['size']) is not int or e['size'] < 1
                or re.fullmatch('[0-9a-f]{64}', e['sha256']) is None):
            raise ValueError('INVALID_ASSET_MANIFEST')
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + args.duration
    lock = threading.Lock()
    finished = []

    def safe(path):
        if not path.resolve().is_relative_to(root):
            raise ValueError('ASSET_ESCAPES_ROOT')
        for entry in [path, *path.parents]:
            if entry == root.parent:
                break
            if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                raise ValueError('LOCAL_LINK_FORBIDDEN')

    def download(e):
        dest = root / e['path']
        part = dest.with_name(dest.name + '.partial')
        safe(dest); safe(part)
        dest.parent.mkdir(parents=True, exist_ok=True)
        if dest.exists():
            if dest.stat().st_size != e['size'] or checksum(dest) != e['sha256']:
                raise ValueError('EXISTING_ASSET_MISMATCH')
        else:
            url = ('https://huggingface.co/Qwen/Qwen3.8-27B-FP8/resolve/' + revision
                   + '/' + urllib.parse.quote(e['path'], safe='/') + '?download=true')
            for attempt in range(2):
                try:
                    offset = part.stat().st_size if part.exists() else 0
                    if offset > e['size']:
                        raise ValueError('OVERSIZED_PARTIAL')
                    if offset < e['size']:
                        remaining = deadline - time.monotonic()
                        if remaining <= 0:
                            raise TimeoutError('DOWNLOAD_DEADLINE')
                        request = urllib.request.Request(url, headers={'Range': f'bytes={offset}-{e["size"]-1}'})
                        with urllib.request.urlopen(request, timeout=min(45, remaining)) as response:
                            expected = f'bytes {offset}-{e["size"]-1}/{e["size"]}'
                            valid_range = response.status == 206 and response.headers.get('Content-Range') == expected
                            valid_whole = (offset == 0 and response.status == 200
                                           and response.headers.get('Content-Length') == str(e['size']))
                            if not (valid_range or valid_whole):
                                raise ValueError('UNEXPECTED_RANGE_RESPONSE')
                            with part.open('ab') as target:
                                while offset < e['size']:
                                    if time.monotonic() >= deadline:
                                        raise TimeoutError('DOWNLOAD_DEADLINE')
                                    block = response.read(min(1 << 20, e['size']-offset))
                                    if not block:
                                        raise EOFError('TRUNCATED_HTTP_ASSET')
                                    target.write(block); offset += len(block)
                                if response.read(1):
                                    raise ValueError('EXTRA_HTTP_ASSET_BYTES')
                                target.flush(); os.fsync(target.fileno())
                    if checksum(part) != e['sha256']:
                        raise ValueError('ASSET_SHA256_MISMATCH')
                    os.link(part, dest)
                    part.unlink()
                    break
                except (OSError, EOFError):
                    if attempt or time.monotonic() >= deadline:
                        raise
                    time.sleep(1)
        with lock:
            finished.append(e['path'])
            print(json.dumps(dict(done=len(finished), total=len(entries), asset=e['path'],
                                  seconds=round(time.monotonic()-started, 2))), flush=True)
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(download, entries))
    except BaseException as error:
        (root.parent/'MODEL_HTTP_FAILED.json').write_text(json.dumps(dict(error=type(error).__name__,
            detail=str(error)[:300], completed=finished)), encoding='utf-8')
        raise
    (root.parent/'MODEL_EXPORT_DONE.json').write_text(json.dumps(dict(status='COMPLETE',
        transport='PINNED_HUGGINGFACE_HTTPS', assets=len(finished), bytes=sum(e['size'] for e in entries),
        seconds=time.monotonic()-started, manifest_sha256=checksum(args.manifest))), encoding='utf-8')


if __name__ == '__main__':
    main()
