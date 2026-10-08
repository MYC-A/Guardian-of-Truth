"""Stream a verified server ZIP onto a larger local disk, then verify its contents.

Paramiko is an operator dependency, never included in the competition runtime.
Existing known_hosts are mandatory. A partial file is never advertised as ready.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import shlex
import stat
import time
import zipfile


def verify_archive(path):
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_ZIP_ENTRIES')
        for entry in archive.infolist():
            pieces = entry.filename.split('/')
            if entry.filename.startswith('/') or ':' in pieces[0] or '..' in pieces or '\\' in entry.filename or 'metrics' in pieces:
                raise ValueError('UNSAFE_ZIP_PATH')
            mode = entry.external_attr >> 16
            if stat.S_ISLNK(mode):
                raise ValueError('ZIP_SYMLINK_FORBIDDEN')
            if entry.is_dir() and stat.S_IMODE(mode) != 0o755:
                raise ValueError('ZIP_DIRECTORY_PERMISSIONS')
        manifest = json.loads(archive.read('MANIFEST.json'))
        if manifest.get('fixture_only'):
            raise ValueError('SMOKE_FIXTURE_CANNOT_BE_SUBMITTED')
        expected = dict(manifest['files'])
        expected['model/Qwen3.8-27B-Q8_0.gguf'] = dict(bytes=manifest['model_bytes'], sha256=manifest['model_sha256'])
        actual = {x.filename for x in archive.infolist() if not x.is_dir()}
        if actual != set(expected) | {'MANIFEST.json'}:
            raise ValueError('ZIP_MANIFEST_FILE_SET_MISMATCH')
        executable = {'runtime/python/bin/python3.12', 'runtime/llama/llama-server', 'runtime/lib/ld-linux-x86-64.so.2'}
        for name in actual:
            entry = archive.getinfo(name)
            if stat.S_IMODE(entry.external_attr >> 16) != (0o755 if name in executable else 0o644):
                raise ValueError('ZIP_FILE_PERMISSIONS: ' + name)
            if name == 'MANIFEST.json':
                continue
            if entry.file_size != expected[name]['bytes']:
                raise ValueError('ZIP_MANIFEST_SIZE_MISMATCH: ' + name)
            digest = hashlib.sha256()
            with archive.open(name) as source:
                for chunk in iter(lambda: source.read(8 * 1024 * 1024), b''):
                    digest.update(chunk)  # ZipFile also checks the entry CRC.
            if digest.hexdigest() != expected[name]['sha256']:
                raise ValueError('ZIP_MANIFEST_HASH_MISMATCH: ' + name)
        if not {'pyproject.toml', 'scripts/predict.py', 'Dockerfile'} <= actual:
            raise ValueError('REQUIRED_ROOT_FILES_MISSING')
        return manifest


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--host', required=True)
    ap.add_argument('--port', type=int, required=True)
    ap.add_argument('--user', default='root')
    ap.add_argument('--identity', type=Path, required=True)
    ap.add_argument('--server-repo', required=True)
    ap.add_argument('--stage', required=True)
    ap.add_argument('--output', type=Path, required=True)
    a = ap.parse_args()
    import paramiko
    a.output.parent.mkdir(parents=True, exist_ok=True)
    partial = a.output.with_suffix(a.output.suffix + '.partial')
    status = a.output.with_suffix(a.output.suffix + '.status.json')
    if a.output.exists() or partial.exists() or status.exists():
        raise ValueError('DOWNLOAD_PATH_ALREADY_EXISTS')
    started = time.monotonic()
    count = 0
    def save(state, **values):
        temporary = status.with_suffix(status.suffix + '.new')
        temporary.write_text(json.dumps(dict(state=state, pid=os.getpid(), bytes=count,
                                               elapsed_seconds=time.monotonic() - started, **values), indent=2), encoding='utf-8')
        os.replace(temporary, status)
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    client.load_host_keys(str(Path.home() / '.ssh/known_hosts'))
    client.set_missing_host_key_policy(paramiko.RejectPolicy())
    try:
        save('CONNECTING')
        client.connect(a.host, port=a.port, username=a.user, key_filename=str(a.identity),
                       allow_agent=False, look_for_keys=False, timeout=10, banner_timeout=10, auth_timeout=10)
        command = ' '.join(shlex.quote(x) for x in ['python3', a.server_repo.rstrip('/') + '/scripts/build_qwen_submission.py',
                                                   'zip', '--stage', a.stage, '--destination', '-'])
        _, stdout, stderr = client.exec_command(command, timeout=120)
        digest = hashlib.sha256()
        save('VERIFYING_SERVER_STAGE_THEN_STREAMING')
        last = time.monotonic()
        with partial.open('xb') as target:
            for chunk in iter(lambda: stdout.read(8 * 1024 * 1024), b''):
                target.write(chunk)
                digest.update(chunk)
                count += len(chunk)
                if time.monotonic() - last >= 10:
                    save('STREAMING')
                    last = time.monotonic()
            target.flush()
            os.fsync(target.fileno())
        error = stderr.read().decode('utf-8', 'replace')
        exit_status = stdout.channel.recv_exit_status()
        if exit_status:
            raise RuntimeError('REMOTE_ARCHIVE_FAILED: ' + error[-1500:])
        if count >= 40_000_000_000:
            raise ValueError('ARCHIVE_EXCEEDS_UPLOAD_LIMIT')
        save('VERIFYING_LOCAL_ARCHIVE', zip_sha256=digest.hexdigest())
        manifest = verify_archive(partial)
        os.replace(partial, a.output)
        save('READY', output=str(a.output.resolve()), zip_sha256=digest.hexdigest(),
             model_sha256=manifest['model_sha256'], artifact_commit=manifest['commit'])
        print(status.read_text(encoding='utf-8'))
    except BaseException as error:
        save('FAILED', error=f'{type(error).__name__}: {error}')
        raise
    finally:
        client.close()


if __name__ == '__main__':
    main()
