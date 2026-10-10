"""Download the frozen server runtime using parallel, resumable native SSH ranges.

Operator utility; no pip packages, model calls or changes to B2 are required.
The expected whole-file SHA256 is pinned to the server export receipt.
"""
import argparse
import base64
from concurrent.futures import ThreadPoolExecutor, wait, FIRST_COMPLETED
import hashlib
import json
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import threading
import time

SIZE = 5700777181
SHA256 = 'bd8fae06c167df4b166e708cccc76022e013755efb741409e533c4b3db1f5e2f'
REMOTE = '/workspace/guardian/vllm_submission_build_20261010_v4/guardian-vllm-runtime.zip'
MIB = 1024 * 1024


def digest(path):
    h = hashlib.sha256()
    with Path(path).open('rb') as source:
        for block in iter(lambda: source.read(8 * MIB), b''):
            h.update(block)
    return h.hexdigest()


def publish(parts, output, expected_size=SIZE, expected_sha=SHA256):
    partial = output.with_name(output.name + '.assembling')
    if output.exists():
        if output.stat().st_size == expected_size and digest(output) == expected_sha:
            return
        raise RuntimeError('Existing destination differs; it will not be overwritten.')
    with partial.open('wb') as target:
        for part in parts:
            with part.open('rb') as source:
                shutil.copyfileobj(source, target, 8 * MIB)
        target.flush()
        os.fsync(target.fileno())
    if partial.stat().st_size != expected_size or digest(partial) != expected_sha:
        raise RuntimeError('SHA256/size mismatch. Parts preserved; final ZIP not published.')
    # Windows rename is exclusive; the single-writer lock protects this download.
    if output.exists():
        raise RuntimeError('Destination appeared during verification; not overwritten.')
    partial.rename(output)


def remote_command(start, count, path=REMOTE, *, verify_start=None, verify_count=None):
    verify_start = start if verify_start is None else verify_start
    verify_count = count if verify_count is None else verify_count
    program = (
        'import os,sys,hashlib\n'
        f'p={path!r}\n'
        f'assert os.stat(p).st_size=={SIZE}, "REMOTE_SIZE_CHANGED"\n'
        f'f=open(p,"rb");f.seek({verify_start});n={verify_count};h=hashlib.sha256()\n'
        'while n:\n'
        ' b=f.read(min(n,1048576))\n'
        ' if not b: raise RuntimeError("UNEXPECTED_EOF")\n'
        ' h.update(b);n-=len(b)\n'
        'sys.stderr.write("GUARDIAN_CHUNK_SHA256="+h.hexdigest()+"\\n");sys.stderr.flush()\n'
        f'f.seek({start});n={count}\n'
        'while n:\n'
        ' b=f.read(min(n,1048576))\n'
        ' if not b: raise RuntimeError("UNEXPECTED_EOF")\n'
        ' sys.stdout.buffer.write(b);n-=len(b)\n'
        'sys.stdout.buffer.flush()\n'
    )
    encoded = base64.b64encode(program.encode()).decode()
    return 'python3 -c ' + shlex.quote('import base64;exec(base64.b64decode(' + repr(encoded) + '))')


def save_receipt(path, value):
    temporary = path.with_name(path.name+'.tmp')
    with temporary.open('w', encoding='utf-8') as stream:
        json.dump(value, stream)
        stream.flush(); os.fsync(stream.fileno())
    os.replace(temporary, path)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, default=Path('A:/Guardian-submissions/vllm-fp8-build-20261010/server-runtime/guardian-vllm-runtime.zip'))
    parser.add_argument('--host', default='92.96.154.105')
    parser.add_argument('--port', type=int, default=43666)
    parser.add_argument('--key', type=Path, default=Path.home()/'.ssh/guardian_vast_me')
    parser.add_argument('--workers', type=int, choices=range(1, 9), default=4)
    parser.add_argument('--timeout', type=int, default=240)
    parser.add_argument('--duration', type=int, default=7200, help='Transfer time limit in seconds; final local hashing is additional.')
    args = parser.parse_args()
    ssh = shutil.which('ssh')
    if not ssh or not args.key.is_file():
        raise RuntimeError('Native ssh or guardian_vast_me key not found.')
    if args.timeout <= 0 or args.duration <= 0:
        raise ValueError('Timeout/duration must be positive.')
    output = args.output.resolve()
    output.parent.mkdir(parents=True, exist_ok=True)
    if output.exists():
        if output.stat().st_size == SIZE and digest(output) == SHA256:
            print('Already downloaded and SHA256 verified:', output, flush=True)
            return
        raise RuntimeError('Destination already exists with different bytes; preserved.')
    folder = output.with_name(output.name+'.parts')
    folder.mkdir(exist_ok=True)
    lock = (folder/'download.lock').open('a+b')
    lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
    if os.name == 'nt':
        import msvcrt
        msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
    else:
        import fcntl
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    started = time.monotonic()
    deadline = started + args.duration
    chunk = 64 * MIB
    stop = threading.Event()
    guard = threading.Lock()
    children = set()
    specs = [(i, offset, min(chunk, SIZE-offset)) for i, offset in enumerate(range(0, SIZE, chunk))]

    def paths(i):
        return folder/f'{i:04d}.part', folder/f'{i:04d}.json'

    def fetch(spec):
        i, offset, length = spec
        part, receipt = paths(i)
        if part.exists() and receipt.exists():
            try:
                old = json.loads(receipt.read_text(encoding='utf-8'))
            except (ValueError, UnicodeError):
                old = None  # Reverify the full chunk against the server below.
            if old == dict(offset=offset, bytes=length, sha256=digest(part), remote_verified=True) and part.stat().st_size == length:
                return
        if part.exists() and part.stat().st_size > length:
            raise RuntimeError(f'Oversized chunk {i}; preserved.')
        for attempt in range(3):
            if stop.is_set() or time.monotonic() >= deadline:
                raise RuntimeError('Download stopped or total time limit reached.')
            prefix = part.stat().st_size if part.exists() else 0
            command = [ssh, '-T', '-i', str(args.key), '-p', str(args.port),
                '-o', 'BatchMode=yes', '-o', 'IdentitiesOnly=yes',
                '-o', 'PreferredAuthentications=publickey', '-o', 'PasswordAuthentication=no',
                '-o', 'StrictHostKeyChecking=yes', '-o', 'ConnectTimeout=10',
                '-o', 'ServerAliveInterval=15', '-o', 'ServerAliveCountMax=2',
                'root@'+args.host, remote_command(offset+prefix, length-prefix, verify_start=offset, verify_count=length)]
            with (folder/f'{i:04d}.stderr.log').open('wb') as error:
                with guard:
                    if stop.is_set():
                        raise RuntimeError('Download cancelled before SSH launch.')
                    proc = subprocess.Popen(command, stdout=subprocess.PIPE, stderr=error,
                        creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
                    children.add(proc)
                timer = threading.Timer(min(args.timeout, max(1, deadline-time.monotonic())), proc.kill)
                timer.start()
                try:
                    with part.open('ab') as target:
                        remaining = length-prefix
                        while True:
                            data = proc.stdout.read(MIB)
                            if not data:
                                break
                            if len(data) > remaining:
                                raise RuntimeError('Unexpected SSH stdout bytes; chunk not admitted.')
                            target.write(data); remaining -= len(data)
                    code = proc.wait()
                finally:
                    timer.cancel()
                    if proc.poll() is None:
                        proc.kill(); proc.wait()
                    proc.stdout.close()
                    with guard:
                        children.discard(proc)
            if code == 0 and part.stat().st_size == length:
                markers = [line.split('=', 1)[1].strip() for line in
                    (folder/f'{i:04d}.stderr.log').read_text(encoding='utf-8', errors='replace').splitlines()
                    if line.startswith('GUARDIAN_CHUNK_SHA256=')]
                actual = digest(part)
                if markers != [actual]:
                    raise RuntimeError(f'Chunk {i}: server SHA mismatch. Move this chunk aside and restart; bytes preserved.')
                save_receipt(receipt, dict(offset=offset, bytes=length, sha256=actual, remote_verified=True))
                return
            print(f'Chunk {i}: interrupted (SSH exit {code}); retry {attempt+1}/3, prefix preserved.', flush=True)
        raise RuntimeError(f'Chunk {i}: bounded retries exhausted. Restart this script to resume.')

    received = sum(min(paths(i)[0].stat().st_size, length) if paths(i)[0].exists() else 0 for i, _, length in specs)
    if shutil.disk_usage(output.parent).free < 2*SIZE-received + 256*MIB:
        raise RuntimeError('Need space for remaining chunks plus 5.7GB assembled ZIP.')
    print(f'Runtime: {SIZE/1e9:.2f} GB, {args.workers} SSH streams. Resume: {received/1e9:.2f} GB.', flush=True)
    print('Keep server online. Same command resumes after interruption.', flush=True)
    pool = ThreadPoolExecutor(max_workers=args.workers)
    try:
        pending = {pool.submit(fetch, spec) for spec in specs}
        while pending:
            done, pending = wait(pending, timeout=5, return_when=FIRST_COMPLETED)
            for task in done:
                task.result()
            size = sum(min(paths(i)[0].stat().st_size, length) if paths(i)[0].exists() else 0 for i, _, length in specs)
            elapsed = max(1, time.monotonic()-started)
            print(f'{size/SIZE:.1%} | {size/1e9:.2f}/{SIZE/1e9:.2f} GB | {(size-received)/MIB/elapsed:.2f} MiB/s', flush=True)
        print('Assembling ZIP and verifying pinned SHA256...', flush=True)
        publish([paths(i)[0] for i, _, _ in specs], output)
        save_receipt(output.with_name(output.name+'.verified.json'), dict(
            status='SHA256_VERIFIED', bytes=SIZE, sha256=SHA256, remote=REMOTE,
            gpu_validation='NOT_EXECUTED', runtime_only=True))
        print('SUCCESS: '+str(output), flush=True)
        print('Parts retained for safe resume; this runtime ZIP has no model weights.', flush=True)
    finally:
        stop.set()
        with guard:
            for child in list(children):
                if child.poll() is None:
                    child.kill()
        pool.shutdown(wait=True, cancel_futures=True)
        lock.close()


if __name__ == '__main__':
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print('STOPPED:', str(error), flush=True)
        raise SystemExit(1)
