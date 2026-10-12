"""Archive public entrypoint: B2 legacy on pinned FP8/vLLM, graphs 16 x 16.

The archive builder installs this file at scripts/predict.py. Inference only
reads id/prompt/response. Row positions identify inference; original ids are echoed.
Empty inputs produce CSV or Parquet without a GPU.
"""
from __future__ import annotations

import argparse
import csv
import ctypes
import ctypes.util
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import time

REVISION = '017b9c7af6b5689d5dd426a76e0bc077eb5ca20a'
PROFILE = 'B2-vllm-0.19.1-FP8-graphs16-legacy-recovery1'
IO_VERSION = 'position-identity-csv-large-fields-20261012'


def read_input(path):
    """Read only inference columns, preserving CSV ids and permitting duplicates."""
    import pandas as pd
    path = Path(path)
    with path.open('rb') as stream:
        parquet = stream.read(4) == b'PAR1'

    def columns(fields):
        names = [name.strip().lstrip('\ufeff').lower() for name in fields]
        if len(names) != len(set(names)):
            raise ValueError('DUPLICATE_COLUMNS')
        lookup = dict(zip(names, fields))
        if not {'id', 'prompt', 'response'} <= set(lookup):
            raise ValueError('REQUIRED_COLUMNS: id,prompt,response')
        return lookup

    if parquet:
        frame = pd.read_parquet(path)
        lookup = columns(list(frame.columns))
        records = frame[[lookup[key] for key in ('id', 'prompt', 'response')]].to_dict('records')
        records = [dict(zip(('id', 'prompt', 'response'), row.values())) for row in records]
    else:
        csv.field_size_limit(2 ** 31 - 1)
        with path.open(encoding='utf-8-sig', newline='') as stream:
            reader = csv.DictReader(stream)
            lookup = columns(reader.fieldnames or [])
            records = [{key: row.get(lookup[key]) for key in ('id', 'prompt', 'response')}
                       for row in reader]
    rows = []
    for number, record in enumerate(records):
        identifier = record['id']
        if identifier is None or (not isinstance(identifier, str) and pd.isna(identifier)):
            identifier = ''
        if not isinstance(identifier, str):
            identifier = str(identifier)
        row = {'id': identifier}
        for key in ('prompt', 'response'):
            if not isinstance(record[key], str):
                raise ValueError(f'NON_STRING_OR_NULL_{key}: row {number}')
            row[key] = record[key]
        rows.append(row)
    return rows


def emit_progress(event, **values):
    """Best-effort bounded metadata; do not print prompts, responses or ids."""
    try:
        print('GUARDIAN_B2 ' + json.dumps(dict(event=event, **values), sort_keys=True), flush=True)
    except Exception:
        pass


def host_environment_record():
    """Bounded read-only metadata before exec; never imports Torch or runs CUDA."""
    versions = {}
    for package in ('vllm', 'torch', 'transformers', 'flashinfer-python', 'triton', 'pandas', 'pyarrow'):
        try:
            versions[package] = importlib.metadata.version(package)
        except Exception as error:
            versions[package] = 'UNAVAILABLE:' + type(error).__name__
    record = dict(python=sys.version.split()[0], executable=sys.executable,
                  packages=versions, nvcc=shutil.which('nvcc'),
                  environment={key: os.environ.get(key, '')[:2048] for key in (
                      'CUDA_VISIBLE_DEVICES', 'NVIDIA_VISIBLE_DEVICES', 'CUDA_HOME', 'CUDA_PATH',
                      'LD_LIBRARY_PATH', 'TRITON_LIBCUDA_PATH', 'FLASHINFER_WORKSPACE_BASE')})
    try:
        record['find_libcuda'] = ctypes.util.find_library('cuda')
        # Loading the library only tests visibility; do not call cuInit.
        ctypes.CDLL('libcuda.so.1')
        record['libcuda_load'] = 'SUCCESS_NO_CUDA_INITIALIZATION'
    except Exception as error:
        record['libcuda_load'] = type(error).__name__ + ':' + str(error)[:1024]
    return record


def emit_host_environment():
    try:
        print('GUARDIAN_HOST_ENVIRONMENT=' + json.dumps(host_environment_record(), sort_keys=True),
              file=sys.stderr, flush=True)
    except Exception as error:
        # Optional diagnostics must not alter the boot path or read input data.
        try:
            print('GUARDIAN_HOST_ENVIRONMENT_UNAVAILABLE=' + type(error).__name__,
                  file=sys.stderr, flush=True)
        except Exception:
            pass


def bootstrap(root, arguments):
    """Only the platform dispatcher uses system Python; no system-site fallback."""
    wrapper = root / 'runtime/python/run_python.sh'
    binary = root / 'runtime/python/bin/python3.12'
    if not wrapper.is_file() or not binary.is_file():
        raise RuntimeError('BUNDLED_PYTHON_RUNTIME_MISSING')
    if (os.environ.get('GUARDIAN_BUNDLED_PYTHON') == '1'
            and Path(sys.executable).resolve() == binary.resolve()):
        return
    emit_host_environment()
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
    """Publish the verified export atomically without overwriting."""
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
    from guardian_truth.submission.cli import write_predictions
    from scripts import qwen_vllm_adapter as adapter
    started = time.monotonic()
    input_path, output = Path(input_path).resolve(), Path(output).resolve()
    if input_path == output:
        raise ValueError('INPUT_OUTPUT_SAME_PATH')
    if output.exists():
        raise FileExistsError(output)
    original_sha = digest(input_path)
    rows = read_input(input_path)
    if digest(input_path) != original_sha:
        raise ValueError('INPUT_CHANGED_DURING_READ')
    model_rows = [dict(row, id=f'row{number:07d}') for number, row in enumerate(rows)]
    output_format = 'PARQUET' if output.suffix.lower() in ('.parquet', '.pq') else 'CSV'
    duplicate_rows = len(rows) - len({row['id'] for row in rows})
    emit_progress('input', profile=PROFILE, io_version=IO_VERSION, rows=len(rows),
                  duplicate_id_rows=duplicate_rows, output_format=output_format)
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
                  input_format='PARQUET_OR_CSV', output_format=output_format,
                  io_version=IO_VERSION, row_identity='POSITION', duplicate_id_rows=duplicate_rows,
                  runtime_input_columns=['id', 'prompt', 'response'], completion_cap=completion_cap(rows),
                  completion_cap_formula='64 + 32*rows + sum(ceil(response_utf8_bytes/10))',
                  cache=str(cache), work=str(work), entrypoint_sha256=digest(__file__))
    # Frozen clean snapshot excludes extra columns and binds adapter's cohort to
    # the already validated source. No labels or external receipts are read.
    snapshot = work / 'input.parquet'
    import pandas as pd
    pd.DataFrame(model_rows, columns=['id', 'prompt', 'response']).to_parquet(snapshot, index=False)
    adapter.write_json(work / 'original-ids.json', [row['id'] for row in rows])
    record['snapshot_sha256'] = digest(snapshot)
    adapter.write_json(work / 'submission.json', record)
    try:
        if rows:
            emit_progress('inference_start', rows=len(rows), workers=16, slots=16,
                          context=32768, duration=1800)
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
        verify_predictions(prediction_path, model_rows)
        predictions = pd.read_parquet(prediction_path)
        predictions['id'] = [row['id'] for row in rows]
        exported = work / ('export.parquet' if output_format == 'PARQUET' else 'export.csv')
        if output_format == 'PARQUET':
            predictions.to_parquet(exported, index=False)
            check = pd.read_parquet(exported)
        else:
            predictions.to_csv(exported, index=False, encoding='utf-8', lineterminator='\n')
            check = pd.read_csv(exported, dtype={'id': str}, keep_default_na=False)
        if (list(check.columns) != ['id', 'label']
                or check['id'].tolist() != [row['id'] for row in rows]
                or check['label'].tolist() != predictions['label'].tolist()):
            raise ValueError('EXPORT_ALIGNMENT_MISMATCH')
        atomic_publish(exported, output)
        record.update(status='COMPLETE', output_sha256=digest(output), seconds=time.monotonic() - started)
        adapter.write_json(work / 'submission.json', record)
        emit_progress('complete', rows=len(rows), seconds=round(record['seconds'], 2),
                      positives=int(predictions['label'].sum()), output_format=output_format,
                      default_zero_fallbacks=record['run'].get('default_zero_fallbacks', 0))
    except BaseException as error:
        record.update(status='FAILED', error=type(error).__name__, seconds=time.monotonic() - started)
        adapter.write_json(work / 'submission.json', record)
        emit_progress('failed', error=type(error).__name__, seconds=round(record['seconds'], 2))
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
