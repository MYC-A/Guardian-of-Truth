"""Finite local off-box collector; never starts training or publishes an artifact."""
import argparse
import hashlib
import json
from pathlib import Path, PurePosixPath
import shlex
import subprocess
import time


def write(path, data):
    temp = path.with_suffix(path.suffix + '.tmp')
    temp.write_text(json.dumps(data, indent=2) + '\n', encoding='utf-8'); temp.replace(path)


def main():
    p = argparse.ArgumentParser()
    for name in ('ssh', 'key', 'out'):
        p.add_argument('--' + name, type=Path, required=True)
    p.add_argument('--host', required=True); p.add_argument('--port', type=int, required=True)
    p.add_argument('--remote-root', required=True); p.add_argument('--finish', required=True)
    a = p.parse_args(); root = PurePosixPath(a.remote_root)
    if not str(root).startswith('/workspace/') or '..' in root.parts or PurePosixPath(a.finish).name != a.finish:
        raise ValueError('UNSAFE_COLLECTION_SCOPE')
    a.out.mkdir(parents=True, exist_ok=True)
    args = [str(a.ssh), '-T', '-i', str(a.key), '-o', 'BatchMode=yes', '-o', 'ConnectTimeout=15',
            '-p', str(a.port), a.host]
    started = time.monotonic(); errors = []; attempts = 0
    write(a.out / 'COLLECTOR_STARTED.json', dict(remote_root=str(root), finish=a.finish, budget_seconds=32400,
                                              source_sha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()))
    try:
        while time.monotonic() - started < 32400:
            # Only fixed small status receipts, never stdout from a live model.
            names = ['TRAINING_PROFILE.json', 'train-v1/PROGRESS.json', 'train-v1/TRAINED.json', 'train-v1/FAIL.json',
                     a.finish + '/PROGRESS.json', a.finish + '/DONE.json', a.finish + '/FAIL.json',
                     a.finish + '-export.INDEX.json']
            code = ('from pathlib import Path\nimport json\nr=Path(' + repr(str(root)) + ')\n' +
                    'names=' + repr(names) + '\nprint(json.dumps({n:json.loads((r/n).read_bytes()) for n in names if (r/n).exists()}))\n')
            result = subprocess.run(args + ['python3 -'], input=code.encode(), capture_output=True, timeout=50)
            if result.returncode:
                errors.append(dict(seconds=time.monotonic() - started, exit_code=result.returncode))
                write(a.out / 'COLLECTOR_ERRORS.json', errors[-20:]); time.sleep(60); continue
            state = json.loads(result.stdout)
            write(a.out / 'LIVE_STATE.json', dict(seconds=time.monotonic() - started, receipts=state))
            index = state.get(a.finish + '-export.INDEX.json')
            if index:
                name = index['name']
                if PurePosixPath(name).name != name or index['bytes'] > 2_000_000_000:
                    raise ValueError('UNSAFE_EXPORT')
                target = a.out / name; part = target.with_suffix(target.suffix + '.partial')
                attempts += 1
                try:
                    with part.open('wb') as stream:
                        result = subprocess.run(args + ['cat -- ' + shlex.quote(str(root / name))],
                                                stdout=stream, stderr=subprocess.PIPE, timeout=1800)
                    digest = hashlib.file_digest(part.open('rb'), 'sha256').hexdigest()
                    if result.returncode or part.stat().st_size != index['bytes'] or digest != index['sha256']:
                        raise ValueError('EXPORTED_BYTES_OR_SHA_MISMATCH')
                    part.replace(target); write(a.out / (name + '.INDEX.json'), index)
                    write(a.out / 'COLLECTED.json', dict(complete=True, archive=str(target), sha256=digest,
                        quality_complete=index['quality_complete'], failure_recorded=index['failure_recorded'],
                        seconds=time.monotonic() - started))
                    return
                except Exception as error:
                    errors.append(dict(seconds=time.monotonic() - started, error=str(error)))
                    write(a.out / 'COLLECTOR_ERRORS.json', errors[-20:])
                    if attempts >= 3:
                        raise
            time.sleep(60)
        raise TimeoutError('FINITE_COLLECTION_DEADLINE')
    except Exception as error:
        write(a.out / 'COLLECTOR_FAILED.json', dict(complete=False, error_type=type(error).__name__,
            error=str(error), seconds=time.monotonic() - started))
        raise


if __name__ == '__main__':
    main()
