"""Archive public entrypoint: B2 legacy on pinned FP8/vLLM, graphs 16 x 16.

The archive builder installs this file at scripts/predict.py. Inference only
reads id/prompt/response. Empty inputs produce a genuine Parquet without a GPU.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
PROFILE = 'B2-vllm-0.19.1-FP8-graphs16-legacy-recovery1'


def bootstrap(root, arguments):
    """Only the platform dispatcher uses system Python; no system-site fallback."""
    wrapper = root / 'runtime/python/run_python.sh'
    binary = root / 'runtime/python/bin/python3.12'
    if not wrapper.is_file() or not binary.is_file():
        raise RuntimeError('BUNDLED_PYTHON_RUNTIME_MISSING')
    if (os.environ.get('GUARDIAN_BUNDLED_PYTHON') == '1'
            and Path(sys.executable).resolve() == binary.resolve()):
        return
    env = dict(os.environ, GUARDIAN_BUNDLED_PYTHON='1', PYTHONDONTWRITEBYTECODE='1',
               PYTHONUTF8='1', PYTHONNOUSERSITE='1')
    os.execve(str(wrapper), [str(wrapper), str(Path(__file__).resolve()), *arguments], env)
    raise RuntimeError('BUNDLED_PYTHON_EXEC_RETURNED')


def digest(path):
    value = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(4 << 20), b''):
            value.update(chunk)
    return value.hexdigest()


def atomic_publish(source, output):
    """Publish the exact verified Parquet bytes atomically without overwriting."""
    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(prefix=output.name + '.', suffix='.tmp', dir=output.parent)
    try:
        with os.fdopen(descriptor, 'wb') as stream, Path(source).open('rb') as original:
            shutil.copyfileobj(original, stream)
            stream.flush()
            os.fsync(stream.fileno())
        # Same-filesystem hardlink is atomic and refuses any existing target,
        # including one created after initial validation by another process.
        os.link(temporary, output)
    finally:
        Path(temporary).unlink(missing_ok=True)


def verify_predictions(path, rows):
    import pandas as pd
    predictions = pd.read_parquet(path)
    if (list(predictions.columns) != ['id', 'label'] or not predictions.index.is_unique
            or predictions['id'].tolist() != [row['id'] for row in rows]
            or not predictions['id'].is_unique
            or not pd.api.types.is_integer_dtype(predictions['label'])
            or pd.api.types.is_bool_dtype(predictions['label'])
            or predictions['label'].isna().any()
            or not predictions['label'].isin([0, 1]).all()):
        raise ValueError('INCOMPLETE_OR_MISALIGNED_PREDICTIONS')


def completion_cap(rows):
    # Fixed B2 branches plus a deliberately conservative byte allowance for
    # DF's ten-claim overflow batches. Never derives a budget from gold or IDs.
    return 64 + 32 * len(rows) + sum((len(row['response'].encode('utf-8')) + 9) // 10 for row in rows)


def run(root, input_path, output, work_dir=None):
    """Run the frozen public profile; failures retain receipts and no output."""
    from guardian_truth.submission.cli import read_rows, write_predictions
    from scripts import qwen_vllm_adapter as adapter
    started = time.monotonic()
    input_path, output = Path(input_path).resolve(), Path(output).resolve()
    if input_path == output:
        raise ValueError('INPUT_OUTPUT_SAME_PATH')
    if output.exists():
        raise FileExistsError(output)
    original_sha = digest(input_path)
    rows = read_rows(input_path)
    if digest(input_path) != original_sha:
        raise ValueError('INPUT_CHANGED_DURING_READ')
    if work_dir is None:
        work = Path(tempfile.mkdtemp(prefix='guardian-vllm-submission-')).resolve()
        if work.is_relative_to(root):
            raise ValueError('WORK_DIR_MUST_BE_OUTSIDE_ARCHIVE')
    else:
        work = Path(work_dir).resolve()
        if work.is_relative_to(root):
            raise ValueError('WORK_DIR_MUST_BE_OUTSIDE_ARCHIVE')
        work.mkdir(parents=True, exist_ok=False)
    cache = work / 'cache'
    cache.mkdir()
    os.environ.update(HF_HUB_OFFLINE='1', TRANSFORMERS_OFFLINE='1',
                      HF_HOME=str(cache / 'huggingface'), XDG_CACHE_HOME=str(cache),
                      VLLM_CACHE_ROOT=str(cache / 'vllm'), TRITON_CACHE_DIR=str(cache / 'triton'),
                      TORCHINDUCTOR_CACHE_DIR=str(cache / 'torchinductor'),
                      VLLM_NO_USAGE_STATS='1', DO_NOT_TRACK='1', PYTHONDONTWRITEBYTECODE='1')
    record = dict(profile=PROFILE, rows=len(rows), input_sha256=original_sha,
                  input_format='PARQUET_OR_CSV', output_format='PARQUET',
                  runtime_input_columns=['id', 'prompt', 'response'], completion_cap=completion_cap(rows),
                  completion_cap_formula='64 + 32*rows + sum(ceil(response_utf8_bytes/10))',
                  cache=str(cache), work=str(work), entrypoint_sha256=digest(__file__))
    # Frozen clean snapshot excludes extra columns and binds adapter's cohort to
    # the already validated source. No labels or external receipts are read.
    snapshot = work / 'input.parquet'
    import pandas as pd
    pd.DataFrame(rows, columns=['id', 'prompt', 'response']).to_parquet(snapshot, index=False)
    record['snapshot_sha256'] = digest(snapshot)
    adapter.write_json(work / 'submission.json', record)
    try:
        if rows:
            adapter.main(['--python', str(root / 'runtime/python/run_python.sh'),
                          '--model-dir', str(root / 'model' / REVISION),
                          '--asset-manifest', str(root / 'MODEL_MANIFEST.json'),
                          '--input', str(snapshot), '--output', str(work / 'run'),
                          '--limit', str(len(rows)), '--workers', '16', '--slots', '16',
                          '--context', '32768', '--startup-timeout', '600',
                          '--duration', '1800', '--timeout', '600',
                          '--max-calls', str(record['completion_cap'])])
            prediction_path = work / 'run/predictions.parquet'
            done = json.loads((work / 'run/DONE.json').read_text(encoding='utf-8'))
            if done.get('rows') != len(rows):
                raise ValueError('RUN_COHORT_MISMATCH')
            record['run'] = done
        else:
            prediction_path = work / 'empty.parquet'
            write_predictions(prediction_path, [])
            record['run'] = dict(rows=0, completion_http=0, preflight_http=0, default_zero_fallbacks=0)
        if digest(snapshot) != record['snapshot_sha256']:
            raise ValueError('SNAPSHOT_CHANGED_DURING_INFERENCE')
        verify_predictions(prediction_path, rows)
        atomic_publish(prediction_path, output)
        record.update(status='COMPLETE', output_sha256=digest(output), seconds=time.monotonic() - started)
        adapter.write_json(work / 'submission.json', record)
    except BaseException as error:
        record.update(status='FAILED', error=type(error).__name__, seconds=time.monotonic() - started)
        adapter.write_json(work / 'submission.json', record)
        raise
    finally:
        print(f'receipts={work}', flush=True)


def main(argv=None):
    arguments = list(sys.argv[1:] if argv is None else argv)
    root = Path(__file__).resolve().parents[1]
    bootstrap(root, arguments)
    sys.path[:0] = [str(root / 'src'), str(root), str(root / 'runtime/site-packages')]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--input', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--work-dir', type=Path, help='Fresh writable receipt directory outside the archive')
    args = parser.parse_args(arguments)
    run(root, args.input, args.output, args.work_dir)


if __name__ == '__main__':
    main()
