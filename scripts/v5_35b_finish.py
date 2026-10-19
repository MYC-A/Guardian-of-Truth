"""Finite supervised post-training evaluation/export; no promotion or quality retries."""
import argparse
import json
from pathlib import Path
import subprocess
import sys
import tarfile
import time

sys.path.insert(0, str(Path(__file__).resolve().parent))
from v5_35b_common import BASE_REVISION, sha, write


def main():
    parser = argparse.ArgumentParser()
    for name in ('training', 'data', 'model', 'manifest', 'runtime-python', 'out'):
        parser.add_argument('--' + name, type=Path, required=True)
    parser.add_argument('--training-program', required=True)
    parser.add_argument('--training-wait-seconds', type=int, choices=(33900,43200), default=33900)
    parser.add_argument('--require-full-epoch', action='store_true')
    a = parser.parse_args(); a.out.mkdir(exist_ok=False)
    started = time.monotonic(); phases = []
    write(a.out / 'START.json', dict(complete=False, training=str(a.training),
        training_program=a.training_program, source_sha256=sha(Path(__file__)),
        quality_retries=0, promotion=False, private_submission=False))

    def run(name, command, timeout):
        phase = dict(name=name, start_unix=time.time()); phases.append(phase)
        write(a.out / 'PROGRESS.json', phases)
        with (a.out / (name + '.log')).open('w', encoding='utf-8', buffering=1) as stream:
            result = subprocess.run(command, stdout=stream, stderr=subprocess.STDOUT, timeout=timeout)
        phase.update(exit_code=result.returncode, seconds=time.time() - phase['start_unix'])
        write(a.out / 'PROGRESS.json', phases)
        if result.returncode:
            raise RuntimeError('POSTTRAIN_PHASE_FAILED:' + name)

    try:
        while not (a.training / 'TRAINED.json').exists():
            status = subprocess.run(['supervisorctl', 'status', a.training_program], capture_output=True, text=True)
            if (a.training / 'FAIL.json').exists() or any(s in status.stdout for s in ('EXITED', 'FATAL', 'STOPPED')):
                raise RuntimeError('TRAINING_EXITED_WITHOUT_TRAINED:' + status.stdout.strip())
            if status.returncode or time.monotonic() - started > a.training_wait_seconds:
                raise TimeoutError('TRAINING_WAIT_FAILED_OR_LIMIT')
            time.sleep(20)
        trained = json.loads((a.training / 'TRAINED.json').read_bytes())
        if not trained['complete'] or trained['optimizer_updates'] <= 0 or trained['base_revision'] != BASE_REVISION:
            raise ValueError('INVALID_TRAINED_RECEIPT')
        if a.require_full_epoch and (not trained['epoch_complete'] or trained['rows_done'] != 1458):
            raise ValueError('FULL_EPOCH_REQUIRED_FOR_THIS_EVALUATION')
        if sha(a.training / 'adapter/adapter_model.safetensors') != trained['adapter_sha256']:
            raise ValueError('FINAL_ADAPTER_IDENTITY_DRIFT')
        for _ in range(90):
            status = subprocess.run(['supervisorctl', 'status', a.training_program], capture_output=True, text=True)
            used = subprocess.check_output(['nvidia-smi', '--query-gpu=memory.used', '--format=csv,noheader,nounits'], text=True).strip()
            if 'RUNNING' not in status.stdout and used == '0':
                break
            time.sleep(1)
        else:
            raise RuntimeError('PREVIOUS_TRAINING_DID_NOT_RELEASE_GPU')
        script = str(Path(__file__).with_name('v5_35b_evaluate.py'))
        run('paired-native', [str(a.runtime_python), script, 'score', '--data', str(a.data),
            '--training', str(a.training), '--model', str(a.model), '--manifest', str(a.manifest),
            '--out', str(a.out / 'paired-native')], 7300)
        run('analysis', [str(a.runtime_python), script, 'analyze', '--data', str(a.data),
            '--run', str(a.out / 'paired-native'), '--out', str(a.out / 'analysis')], 900)
        write(a.out / 'QUALITY_DONE.json', dict(complete=True, phases=phases,
            adapter_sha256=trained['adapter_sha256'], epoch_complete=trained['epoch_complete'],
            epoch_fraction=trained['epoch_fraction'], seconds=time.monotonic() - started,
            scope='paired classifier-only', production_promoted=False, private_improvement_measured=False))
    except Exception as error:
        write(a.out / 'FAIL.json', dict(complete=False, error_type=type(error).__name__, error=str(error),
                                      phases=phases, seconds=time.monotonic() - started))
        raise
    finally:
        archive = a.out.parent / (a.out.name + '-export.tar.gz')
        if archive.exists():
            raise FileExistsError('EXPORT_ALREADY_EXISTS')
        # Preserve the final adapter and all diagnostics even if evaluation
        # failed. Optimizer checkpoints remain separately in the training dir.
        with tarfile.open(archive, 'w:gz', compresslevel=3) as tar:
            for name in ('START.json', 'MODEL_READY.json', 'LOADER_COMPATIBILITY.json', 'TRAINED.json',
                         'PROGRESS.json', 'FAIL.json', 'training.jsonl', 'adapter', 'final'):
                p = a.training / name
                if p.exists():
                    tar.add(p, arcname='training/' + name)
            tar.add(a.out, arcname='posttrain')
            for name in ('PREPARED.json', 'INDEX.json'):
                tar.add(a.data / name, arcname='evaluation-input-metadata/' + name)
        write(a.out.parent / (a.out.name + '-export.INDEX.json'), dict(name=archive.name,
            bytes=archive.stat().st_size, sha256=sha(archive), quality_complete=(a.out / 'QUALITY_DONE.json').exists(),
            failure_recorded=(a.out / 'FAIL.json').exists()))
    write(a.out / 'DONE.json', dict(complete=True, seconds=time.monotonic() - started,
                                  export=a.out.name + '-export.INDEX.json'))


if __name__ == '__main__':
    main()
