"""Finite preflight-to-training chain with hourly training health receipts."""
import argparse
import json
import math
from pathlib import Path
import subprocess
import sys
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v5_35b_common import sha, write
from v5_35b_train import check_gate


def main():
    parser = argparse.ArgumentParser()
    for name in ('root', 'training-python', 'runtime-python', 'model'):
        parser.add_argument('--' + name, type=Path, required=True)
    a = parser.parse_args(); r = a.root; out = r / 'launch-v1'; out.mkdir(exist_ok=False)
    pilot = r / 'pilot8-budget9h-v1'; native = r / 'native8-budget9h-v1'; training = r / 'train-v1'
    scripts = Path(__file__).resolve().parent; started = time.monotonic(); phases = []
    common = ['--model', str(a.model), '--manifest', str(r / 'BASE_MODEL_MANIFEST.json'),
              '--data', str(r / 'prepared-v1')]
    write(out / 'START.json', dict(optimizer_budget_seconds=32400, hourly_health_interval_seconds=3600,
        layers=8, shared=True, backend='AWQ_TORCH', fresh_initialization=True, quality_retries=0,
        source_sha256={n: sha(scripts / n) for n in ('v5_35b_launch.py', 'v5_35b_train.py', 'v5_35b_common.py')},
        status='EXPLORATORY_ONLY_HUMAN_UNVERIFIED'))

    def run(name, command, timeout, hourly=False):
        rec = dict(phase=name, start_unix=time.time()); phases.append(rec); write(out / 'PROGRESS.json', phases)
        with (out / (name + '.log')).open('w', encoding='utf-8', buffering=1) as stream:
            process = subprocess.Popen(command, stdout=stream, stderr=subprocess.STDOUT)
            deadline = time.monotonic() + timeout; checks = 0; previous_rows = None
            while True:
                try:
                    code = process.wait(timeout=min(3600 if hourly else 30, max(.1, deadline - time.monotonic())))
                    break
                except subprocess.TimeoutExpired:
                    if time.monotonic() >= deadline:
                        process.terminate()
                        try:
                            process.wait(timeout=90)
                        except subprocess.TimeoutExpired:
                            process.kill(); process.wait(timeout=30)
                        raise TimeoutError('FINITE_PHASE_TIMEOUT:' + name)
                    if hourly:
                        checks += 1; p = training / 'PROGRESS.json'
                        progress = json.loads(p.read_bytes()) if p.exists() else None
                        healthy = (progress is not None and progress.get('step', 0) > 0 and
                                   math.isfinite(progress.get('loss', float('nan'))) and
                                   math.isfinite(progress.get('grad_norm', float('nan'))) and
                                   (previous_rows is None or progress.get('rows_done', 0) > previous_rows))
                        gpu = subprocess.run(['nvidia-smi', '--query-gpu=utilization.gpu,memory.used,memory.total',
                                              '--format=csv,noheader'], capture_output=True, text=True, timeout=20)
                        receipt = dict(check=checks, unix=time.time(), healthy=healthy, progress=progress,
                                       gpu=gpu.stdout.strip(), process_alive=process.poll() is None,
                                       fail_file=(training / 'FAIL.json').exists())
                        write(out / ('HEALTH_HOUR_%02d.json' % checks), receipt)
                        write(out / 'HEALTH_LATEST.json', receipt)
                        previous_rows = progress.get('rows_done', 0) if progress else None
                        if not healthy or receipt['fail_file']:
                            process.terminate()
                            try:
                                process.wait(timeout=90)
                            except subprocess.TimeoutExpired:
                                process.kill(); process.wait(timeout=30)
                            raise RuntimeError('HOURLY_TRAINING_HEALTH_FAILED')
        rec.update(exit_code=code, seconds=time.time() - rec['start_unix']); write(out / 'PROGRESS.json', phases)
        if code:
            raise RuntimeError('PHASE_FAILED:' + name)

    try:
        used = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip()
        if used != '0':
            raise RuntimeError('GPU_BUSY_AT_LAUNCH')
        run('pilot', [str(a.training_python), str(scripts / 'v5_35b_train.py'), *common, '--out', str(pilot),
            '--pilot', '--layers', '8', '--backend', 'AWQ_TORCH', '--budget-seconds', '32400'], 1200)
        p = json.loads((pilot / 'DONE.json').read_bytes())
        if not p['complete'] or not p['technical_feasible'] or p['optimizer_updates'] != 0:
            raise ValueError('PILOT_GATE_NOT_PASSED')
        run('native', [str(a.runtime_python), str(scripts / 'v5_35b_native_probe.py'), *common,
            '--out', str(native), '--pilot', str(pilot)], 720)
        n = json.loads((native / 'DONE.json').read_bytes())
        if not n['complete'] or not n['group_gone'] or not n['nonzero_adapter_binding_proven']:
            raise ValueError('NATIVE_GATE_NOT_PASSED')
        if not math.isfinite(n['hf_native_zero_abs_delta']) or n['hf_native_zero_abs_delta'] > 2:
            raise ValueError('HF_NATIVE_DISCREPANCY_REQUIRES_INVESTIGATION')
        gate = dict(layers=8, shared=True, backend='AWQ_TORCH', optimizer_budget_seconds=32400,
                    train_tokens_sha256=p['train_tokens_sha256'],
                    pilot=dict(path=str(pilot / 'DONE.json'), sha256=sha(pilot / 'DONE.json')),
                    native=dict(path=str(native / 'DONE.json'), sha256=sha(native / 'DONE.json')),
                    estimated_full_epoch_seconds=p['estimated_epoch_seconds'], epoch_fits_budget=p['epoch_fits_budget'],
                    checkpoint_selection_on_holdout=False, profile_selection='technical only; no quality labels inspected')
        write(r / 'TRAINING_PROFILE.json', gate)
        check_gate(r / 'TRAINING_PROFILE.json', json.loads((r / 'prepared-v1/DONE.json').read_bytes()), 8, True, 'AWQ_TORCH')
        run('training', [str(a.training_python), str(scripts / 'v5_35b_train.py'), *common,
            '--out', str(training), '--layers', '8', '--backend', 'AWQ_TORCH',
            '--budget-seconds', '32400', '--gate', str(r / 'TRAINING_PROFILE.json')], 33300, hourly=True)
        trained = json.loads((training / 'TRAINED.json').read_bytes())
        if not trained['complete'] or trained['optimizer_updates'] <= 0:
            raise ValueError('TRAINING_INCOMPLETE')
        write(out / 'DONE.json', dict(complete=True, phases=phases, optimizer_updates=trained['optimizer_updates'],
            rows_done=trained['rows_done'], epoch_fraction=trained['epoch_fraction'], seconds=time.monotonic() - started))
    except Exception as error:
        write(out / 'FAIL.json', dict(complete=False, phases=phases, error_type=type(error).__name__,
                                     error=str(error), seconds=time.monotonic() - started))
        raise


if __name__ == '__main__':
    main()
