"""Public packaging and all-row/output contract tests without GPU/HTTP."""
import json
import os
from pathlib import Path

import pandas as pd
import pytest

from submission import predict_vllm as public
from scripts import qwen_vllm_adapter as adapter


@pytest.fixture
def archive(tmp_path):
    root = tmp_path / 'archive'
    (root / 'runtime/python/bin').mkdir(parents=True)
    (root / 'runtime/python/bin/python3.12').write_text('unused binary')
    (root / 'runtime/python/run_python.sh').write_text('unused wrapper')
    return root


def input_frame(tmp_path, count=3, csv=False):
    frame = pd.DataFrame(dict(id=[f'id-{n}' for n in range(count)],
                              prompt=['source policy\nexact unicode: Привет'] * count,
                              response=['assistant response'] * count, label=[1] * count))
    path = tmp_path / ('input.csv' if csv else 'input.parquet')
    if csv:
        frame.to_csv(path, index=False)
    else:
        frame.to_parquet(path, index=False)
    return path, frame


def fake_adapter(monkeypatch, labels=None, mutate=None):
    calls = []
    def main(arguments):
        pairs = dict(zip(arguments[::2], arguments[1::2]))
        assert '--enforce-eager' not in arguments
        calls.append(pairs)
        rows = pd.read_parquet(pairs['--input'])
        assert list(rows.columns) == ['id', 'prompt', 'response']
        destination = Path(pairs['--output'])
        destination.mkdir()
        predictions = pd.DataFrame(dict(id=rows['id'], label=labels if labels is not None else
                                         [n % 2 for n in range(len(rows))]))
        if mutate:
            predictions = mutate(predictions)
        predictions.to_parquet(destination / 'predictions.parquet', index=False)
        (destination / 'DONE.json').write_text(json.dumps(dict(rows=len(rows), completion_http=3,
                                                              default_zero_fallbacks=0)))
    monkeypatch.setattr(adapter, 'main', main)
    return calls


@pytest.mark.parametrize('csv,count', [(False, 3), (True, 3), (False, 71)])
def test_all_rows_equal_fixed_profile_and_original_output_order(tmp_path, archive, monkeypatch, csv, count):
    source, frame = input_frame(tmp_path, count, csv)
    calls = fake_adapter(monkeypatch)
    output = tmp_path / 'predictions.parquet'
    work = tmp_path / 'work'
    public.run(archive, source, output, work)
    actual = pd.read_parquet(output)
    assert actual['id'].tolist() == frame['id'].tolist()
    assert actual['label'].tolist() == [n % 2 for n in range(count)]
    assert output.read_bytes()[:4] == b'PAR1'
    options = calls[0]
    assert options['--limit'] == str(count)
    assert options['--max-calls'] == str(public.completion_cap(frame.to_dict('records')))
    assert options['--workers'] == options['--slots'] == '16'
    assert options['--context'] == '32768'
    assert options['--timeout'] == options['--startup-timeout'] == '600'
    assert options['--duration'] == '1800'
    assert options['--python'] == str(archive / 'runtime/python/run_python.sh')
    assert options['--model-dir'] == str(archive / 'model' / public.REVISION)
    assert options['--asset-manifest'] == str(archive / 'MODEL_MANIFEST.json')
    snapshot = pd.read_parquet(work / 'input.parquet')
    assert snapshot[['prompt', 'response']].equals(frame[['prompt', 'response']])
    assert os.environ['HF_HUB_OFFLINE'] == os.environ['TRANSFORMERS_OFFLINE'] == '1'
    assert Path(os.environ['VLLM_CACHE_ROOT']).is_relative_to(work)
    receipt = json.loads((work / 'submission.json').read_text())
    assert receipt['status'] == 'COMPLETE' and receipt['rows'] == count
    assert receipt['input_sha256'] == public.digest(source)


@pytest.mark.parametrize('csv', [False, True])
def test_empty_input_real_parquet_without_server(tmp_path, archive, monkeypatch, csv):
    source, _ = input_frame(tmp_path, 0, csv)
    monkeypatch.setattr(adapter, 'main', lambda *a: pytest.fail('empty input must not start GPU'))
    output = tmp_path / 'empty-result.parquet'
    public.run(archive, source, output, tmp_path / 'empty-work')
    assert output.read_bytes()[:4] == b'PAR1'
    frame = pd.read_parquet(output)
    assert list(frame.columns) == ['id', 'label'] and len(frame) == 0


def test_existing_output_rejected_before_gpu_or_work(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    output = tmp_path / 'result.parquet'
    output.write_bytes(b'keep')
    monkeypatch.setattr(adapter, 'main', lambda *a: pytest.fail('must not call'))
    with pytest.raises(FileExistsError):
        public.run(archive, source, output, tmp_path / 'work')
    assert output.read_bytes() == b'keep'
    assert not (tmp_path / 'work').exists()


def test_existing_work_never_reads_historical_receipts(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    work = tmp_path / 'old'
    work.mkdir()
    monkeypatch.setattr(adapter, 'main', lambda *a: pytest.fail('must not call'))
    with pytest.raises(FileExistsError):
        public.run(archive, source, tmp_path / 'result.parquet', work)


def test_work_must_be_outside_archive(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    with pytest.raises(ValueError, match='OUTSIDE_ARCHIVE'):
        public.run(archive, source, tmp_path / 'result.parquet', archive / 'cache')
    assert not (archive / 'cache').exists()


@pytest.mark.parametrize('mutate', [lambda frame: frame.iloc[::-1], lambda frame: frame.iloc[:-1],
    lambda frame: frame.assign(label=[0.0] * len(frame)), lambda frame: frame.assign(label=[True] * len(frame)),
    lambda frame: frame.assign(label=[2] * len(frame)), lambda frame: frame.assign(id=['duplicate'] * len(frame)),
    lambda frame: frame.assign(unasked='extra')])
def test_invalid_prediction_shape_never_publishes(tmp_path, archive, monkeypatch, mutate):
    source, _ = input_frame(tmp_path)
    fake_adapter(monkeypatch, mutate=mutate)
    output = tmp_path / 'result.parquet'
    with pytest.raises(ValueError, match='PREDICTIONS'):
        public.run(archive, source, output, tmp_path / 'work')
    assert not output.exists()
    assert json.loads((tmp_path / 'work/submission.json').read_text())['status'] == 'FAILED'


def test_adapter_failure_retains_receipt_no_silent_fallback(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    def fail(*args):
        raise RuntimeError('MODEL_START_FAILED')
    monkeypatch.setattr(adapter, 'main', fail)
    with pytest.raises(RuntimeError):
        public.run(archive, source, tmp_path / 'result.parquet', tmp_path / 'work')
    assert not (tmp_path / 'result.parquet').exists()


def test_output_recovery_labels_unchanged(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    fake_adapter(monkeypatch, labels=[0, 1, 0])
    output = tmp_path / 'result.parquet'
    public.run(archive, source, output, tmp_path / 'work')
    assert pd.read_parquet(output)['label'].tolist() == [0, 1, 0]


def test_atomic_publish_race_cannot_overwrite(tmp_path):
    original, output = tmp_path / 'original', tmp_path / 'output'
    original.write_bytes(b'new exact bytes')
    output.write_bytes(b'existing output')
    with pytest.raises(FileExistsError):
        public.atomic_publish(original, output)
    assert output.read_bytes() == b'existing output'
    assert not list(tmp_path.glob('*.tmp'))


def test_bootstrap_dispatches_through_wrapper_even_spoofed_marker(archive, monkeypatch):
    calls = []
    monkeypatch.setenv('GUARDIAN_BUNDLED_PYTHON', '1')
    monkeypatch.setattr(public.sys, 'executable', 'unrelated-system-python')
    def dispatch(path, arguments, environment):
        calls.append((path, arguments, environment))
        raise SystemExit('exec')
    monkeypatch.setattr(public.os, 'execve', dispatch)
    with pytest.raises(SystemExit):
        public.bootstrap(archive, ['--input', 'real.parquet', '--output', 'out.parquet'])
    path, arguments, environment = calls[0]
    assert path == str(archive / 'runtime/python/run_python.sh')
    assert arguments[-4:] == ['--input', 'real.parquet', '--output', 'out.parquet']
    assert environment['GUARDIAN_BUNDLED_PYTHON'] == '1'


def test_bootstrap_accepts_actual_bundled_interpreter(archive, monkeypatch):
    monkeypatch.setenv('GUARDIAN_BUNDLED_PYTHON', '1')
    monkeypatch.setattr(public.sys, 'executable', str(archive / 'runtime/python/bin/python3.12'))
    monkeypatch.setattr(public.os, 'execve', lambda *a: pytest.fail('already bootstrapped'))
    public.bootstrap(archive, [])


def test_public_arguments_forward_cleanly_no_sysargv_mutation(monkeypatch):
    monkeypatch.setattr(public, 'bootstrap', lambda root, args: None)
    captured = []
    monkeypatch.setattr(public, 'run', lambda *args: captured.append(args))
    old_arguments = list(public.sys.argv)
    public.main(['--input', 'file.csv', '--output', 'result.parquet', '--work-dir', 'fresh'])
    assert public.sys.argv == old_arguments
    assert captured[0][1:] == (Path('file.csv'), Path('result.parquet'), Path('fresh'))


def test_completion_cap_scales_with_rows_and_current_move_bytes_only():
    row = dict(id='unused', prompt='policy', response='Привет')
    initial = public.completion_cap([row])
    assert initial == 64 + 32 + 2
    assert public.completion_cap([dict(row, id='different', label=1, prompt='large policy' * 10000)]) == initial
    assert public.completion_cap([dict(row, response='x' * 10000)]) == 64 + 32 + 1000
    assert public.completion_cap([row] * 100) > public.completion_cap([row] * 46)


def test_input_replacement_during_read_is_refused(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    from guardian_truth.submission import cli
    original = cli.read_rows
    def replaced(path):
        rows = original(path)
        source.write_bytes(b'replaced after read')
        return rows
    monkeypatch.setattr(cli, 'read_rows', replaced)
    with pytest.raises(ValueError, match='INPUT_CHANGED'):
        public.run(archive, source, tmp_path / 'output.parquet', tmp_path / 'work')
    assert not (tmp_path / 'work').exists()


def test_snapshot_replacement_during_run_refuses_publication(tmp_path, archive, monkeypatch):
    source, _ = input_frame(tmp_path)
    fake_adapter(monkeypatch)
    original = adapter.main
    def mutated(arguments):
        original(arguments)
        pairs = dict(zip(arguments[::2], arguments[1::2]))
        Path(pairs['--input']).write_bytes(b'mutated snapshot')
    monkeypatch.setattr(adapter, 'main', mutated)
    with pytest.raises(ValueError, match='SNAPSHOT_CHANGED'):
        public.run(archive, source, tmp_path / 'output.parquet', tmp_path / 'work')
    assert not (tmp_path / 'output.parquet').exists()
