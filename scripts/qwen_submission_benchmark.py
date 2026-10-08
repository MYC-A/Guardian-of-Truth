"""Run a fresh whole-input performance arm and retain external wall timing.

Optional wait uses a specific preceding process plus a terminal exit receipt.
It never restarts a disappeared process or substitutes partial predictions.
"""
import argparse
import hashlib
import json
import os
from pathlib import Path
import subprocess
import sys
import time


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--stage', type=Path, required=True)
    ap.add_argument('--input', type=Path, required=True)
    ap.add_argument('--output-dir', type=Path, required=True)
    ap.add_argument('--workers', type=int, default=16)
    ap.add_argument('--flash', action='store_true')
    ap.add_argument('--batch-size', type=int)
    ap.add_argument('--ubatch-size', type=int)
    ap.add_argument('--wait-pid', type=int)
    ap.add_argument('--wait-exit-file', type=Path)
    a = ap.parse_args()
    if a.output_dir.exists():
        raise ValueError('BENCHMARK_OUTPUT_ALREADY_EXISTS')
    a.output_dir.mkdir(parents=True)
    status = a.output_dir / 'supervisor.json'
    def save(**values):
        status.write_text(json.dumps(dict(updated=time.time(), **values), indent=2), encoding='utf-8')
    if a.wait_pid:
        if not a.wait_exit_file:
            raise ValueError('WAIT_REQUIRES_TERMINAL_RECEIPT')
        save(state='WAITING', previous_pid=a.wait_pid)
        while not a.wait_exit_file.exists():
            try:
                os.kill(a.wait_pid, 0)
            except ProcessLookupError:
                save(state='PREVIOUS_DISAPPEARED_WITHOUT_RECEIPT', previous_pid=a.wait_pid)
                raise RuntimeError('PREVIOUS_PROCESS_DISAPPEARED')
            time.sleep(10)
        previous_exit = int(a.wait_exit_file.read_text().strip())
    else:
        previous_exit = None
    command = [sys.executable, str(a.stage / 'scripts/predict.py'), '--input', str(a.input),
               '--output', str(a.output_dir / 'predictions.parquet'),
               '--work-dir', str(a.output_dir / 'receipts'), '--workers', str(a.workers)]
    if a.flash:
        command += ['--fast']
    if a.batch_size:
        command += ['--batch-size', str(a.batch_size)]
    if a.ubatch_size:
        command += ['--ubatch-size', str(a.ubatch_size)]
    manifest = dict(command=command, input_sha256=hashlib.sha256(a.input.read_bytes()).hexdigest(),
                    previous_exit=previous_exit, start_epoch=time.time())
    start = time.monotonic()
    with (a.output_dir / 'console.log').open('w', encoding='utf-8') as f:
        process = subprocess.Popen(command, stdout=f, stderr=subprocess.STDOUT)
        save(state='RUNNING', pid=process.pid, **manifest)
        try:
            returncode = process.wait(timeout=1800)
        except subprocess.TimeoutExpired:
            process.terminate()
            try:
                process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill()
                process.wait()
            save(state='TIMEOUT', seconds=time.monotonic() - start, **manifest)
            raise
    save(state='COMPLETE' if returncode == 0 else 'FAILED', exit_status=returncode,
         external_seconds=time.monotonic() - start, **manifest)
    (a.output_dir / 'exit_status').write_text(str(returncode), encoding='utf-8')
    return returncode


if __name__ == '__main__':
    sys.exit(main())
