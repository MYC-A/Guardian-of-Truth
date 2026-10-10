"""Operator-only bounded parallel SFTP export of pinned verified FP8 assets."""
from concurrent.futures import ThreadPoolExecutor
import argparse
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import threading
import time


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for block in iter(lambda: stream.read(8 << 20), b''):
            value.update(block)
    return value.hexdigest()


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--manifest', type=Path, required=True)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--host', required=True)
    parser.add_argument('--port', type=int, required=True)
    parser.add_argument('--key', type=Path, required=True)
    parser.add_argument('--known-hosts', type=Path, required=True)
    parser.add_argument('--remote-root', required=True)
    parser.add_argument('--paramiko-path', type=Path)
    parser.add_argument('--workers', type=int, default=8)
    parser.add_argument('--duration', type=int, default=3600)
    args = parser.parse_args()
    if args.paramiko_path:
        import sys
        sys.path.insert(0, str(args.paramiko_path))
    import paramiko
    if not 1 <= args.workers <= 8 or args.duration < 1:
        parser.error('invalid worker/time budget')
    manifest = json.loads(args.manifest.read_text(encoding='utf-8'))
    revision = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
    if manifest['repository'] != 'Qwen/Qwen3.8-27B-FP8' or manifest['revision'] != revision:
        raise ValueError('MODEL_IDENTITY_MISMATCH')
    entries = manifest['files']
    if len({row['path'] for row in entries}) != len(entries):
        raise ValueError('DUPLICATE_ASSETS')
    names = {row['path'] for row in entries}
    if any(name + '.partial' in names for name in names):
        raise ValueError('PARTIAL_PATH_COLLISION')
    for row in entries:
        name = row['path']
        if (not isinstance(name, str) or not name or PurePosixPath(name).as_posix() != name
                or PurePosixPath(name).is_absolute() or '..' in PurePosixPath(name).parts
                or '\\' in name or ':' in name or type(row['size']) is not int or row['size'] < 1
                or not isinstance(row.get('sha256'), str)
                or re.fullmatch('[0-9a-f]{64}', row['sha256']) is None):
            raise ValueError('INVALID_ASSET')
    root = args.destination.resolve()
    root.mkdir(parents=True, exist_ok=True)
    started = time.monotonic()
    deadline = started + args.duration
    lock = threading.Lock()
    clients = []
    completed = []
    assignments = [entries[i::args.workers] for i in range(args.workers)]

    def connection():
        client = paramiko.SSHClient()
        client.load_host_keys(str(args.known_hosts))
        client.set_missing_host_key_policy(paramiko.RejectPolicy())
        try:
            client.connect(args.host, port=args.port, username='root', key_filename=str(args.key),
                           look_for_keys=False, allow_agent=False, timeout=10, auth_timeout=15, banner_timeout=15)
            channel = paramiko.SFTPClient.from_transport(client.get_transport(), window_size=64 << 20,
                                                       max_packet_size=1 << 20)
            channel.get_channel().settimeout(45)
            with lock:
                clients.append(client)
        except BaseException:
            client.close()
            raise
        return client, channel

    def stop_connections():
        with lock:
            active = list(clients)
        for client in active:
            client.close()

    timer = threading.Timer(args.duration, stop_connections)
    timer.daemon = True
    timer.start()

    def safe_target(path):
        if not path.resolve().is_relative_to(root):
            raise ValueError('LOCAL_ASSET_ESCAPES_ROOT')
        for entry in [path, *path.parents]:
            if entry == root.parent:
                break
            if entry.is_symlink() or (hasattr(entry, 'is_junction') and entry.is_junction()):
                raise ValueError('LOCAL_LINK_FORBIDDEN')

    def worker(rows):
        client, sftp = connection()
        try:
            for row in rows:
                if time.monotonic() >= deadline:
                    raise TimeoutError('EXPORT_DEADLINE')
                destination = root / row['path']
                safe_target(destination)
                destination.parent.mkdir(parents=True, exist_ok=True)
                if destination.exists():
                    if destination.stat().st_size != row['size'] or digest(destination) != row['sha256']:
                        raise ValueError('EXISTING_ASSET_MISMATCH')
                else:
                    partial = destination.with_name(destination.name + '.partial')
                    safe_target(partial)
                    if partial.exists() and partial.stat().st_size > row['size']:
                        raise ValueError('OVERSIZED_PARTIAL')
                    source = args.remote_root.rstrip('/') + '/' + row['path']
                    if sftp.stat(source).st_size != row['size']:
                        raise ValueError('REMOTE_SIZE_CHANGED')
                    offset = partial.stat().st_size if partial.exists() else 0
                    with sftp.open(source, 'rb') as remote, partial.open('ab') as output:
                        remote.seek(offset)
                        # Pipelined SFTP reads avoid a TCP roundtrip for each32KB.
                        remote.prefetch(file_size=row['size'], max_concurrent_requests=32)
                        while offset < row['size']:
                            if time.monotonic() >= deadline:
                                raise TimeoutError('EXPORT_DEADLINE')
                            block = remote.read(min(1 << 20, row['size'] - offset))
                            if not block:
                                raise EOFError('REMOTE_TRUNCATED')
                            output.write(block)
                            offset += len(block)
                        output.flush()
                        os.fsync(output.fileno())
                    if digest(partial) != row['sha256']:
                        raise ValueError('ASSET_SHA256_MISMATCH')
                    if destination.exists():
                        raise FileExistsError(destination)
                    os.link(partial, destination)
                    partial.unlink()
                with lock:
                    completed.append(row['path'])
                    print(json.dumps(dict(completed=len(completed), total=len(entries), asset=row['path'],
                                          elapsed_seconds=round(time.monotonic() - started, 2))), flush=True)
        finally:
            try:
                sftp.close()
            finally:
                client.close()
    try:
        with ThreadPoolExecutor(max_workers=args.workers) as pool:
            list(pool.map(worker, assignments))
    except BaseException as error:
        (root.parent / 'MODEL_EXPORT_FAILED.json').write_text(json.dumps(dict(error=type(error).__name__,
            detail=str(error)[:300], completed=completed)), encoding='utf-8')
        raise
    finally:
        timer.cancel()
    (root.parent / 'MODEL_EXPORT_DONE.json').write_text(json.dumps(dict(status='COMPLETE',
        assets=len(completed), bytes=sum(row['size'] for row in entries), seconds=time.monotonic()-started,
        manifest_sha256=digest(args.manifest), workers=args.workers)), encoding='utf-8')


if __name__ == '__main__':
    main()
