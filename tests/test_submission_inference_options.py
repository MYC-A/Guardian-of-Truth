"""Opt-in serving controls keep the baseline wire and row recovery unchanged."""
import json
from pathlib import Path
import threading

import pandas as pd
import pytest

from guardian_truth.submission import cli


class Process:
    def __init__(self):
        self.returncode = None
    def poll(self):
        return self.returncode
    def terminate(self):
        self.returncode = 0
    def wait(self, timeout=None):
        return self.returncode


def native_fixture(monkeypatch, slots=8, include_slots=True):
    commands = []
    def launch(command, **kwargs):
        commands.append(command)
        return Process()
    monkeypatch.setattr(cli.subprocess, 'Popen', launch)
    monkeypatch.setattr(cli.secrets, 'token_hex', lambda *a: 'test-owned-key')
    def metadata(url, *args, **kwargs):
        if url.endswith('/health'):
            return dict(status='ok')
        result = dict(model_alias=cli.MODEL, default_generation_settings=dict(n_ctx=32768))
        if include_slots:
            result['total_slots'] = slots
        return result
    monkeypatch.setattr(cli, 'http_json', metadata)
    return commands


def test_default_native_command_is_exact_old_baseline(monkeypatch, tmp_path):
    commands = native_fixture(monkeypatch)
    with cli.ModelServer(tmp_path, tmp_path, 8, 32768, port=9911):
        pass
    assert commands == [[str(tmp_path / 'runtime/llama/llama-server'), '-m',
        str(tmp_path / 'model/Qwen3.8-27B-Q8_0.gguf'), '--alias', cli.MODEL,
        '--host', '127.0.0.1', '--port', '9911', '-ngl', '999', '-c', '262144',
        '-np', '8', '--reasoning', 'off', '--no-context-shift', '--metrics',
        '--api-key', 'test-owned-key']]


def test_speculative_flag_is_opt_in_and_context_uses_slots(monkeypatch, tmp_path):
    commands = native_fixture(monkeypatch, slots=2)
    with cli.ModelServer(tmp_path, tmp_path, 2, 32768, port=9911, spec_type='ngram-mod'):
        pass
    command = commands[0]
    assert command[command.index('-np') + 1] == '2'
    assert command[command.index('-c') + 1] == '65536'
    assert command[-2:] == ['--spec-type', 'ngram-mod']
    assert command.count('--spec-type') == 1


@pytest.mark.parametrize('kwargs', [dict(spec_type='arbitrary'), dict(spec_type=True), dict(slots=0),
                                    dict(slots=True), dict(slots=-3)])
def test_invalid_server_options_reject_before_process_launch(monkeypatch, tmp_path, kwargs):
    commands = native_fixture(monkeypatch)
    slots = kwargs.pop('slots', 8)
    with pytest.raises(ValueError):
        cli.ModelServer(tmp_path, tmp_path, slots, 32768, **kwargs)
    assert commands == []


@pytest.mark.parametrize('backend_flag', [dict(fast=True), dict(batch_size=8192),
                                         dict(ubatch_size=512), dict(spec_type='ngram-mod')])
def test_attach_cannot_silently_ignore_backend_change(monkeypatch, tmp_path, backend_flag):
    commands = native_fixture(monkeypatch)
    with pytest.raises(ValueError, match='ATTACH_CANNOT_CHANGE_BACKEND_FLAGS'):
        cli.ModelServer(tmp_path, tmp_path, 8, 32768, port=9911, attach=True, **backend_flag)
    assert commands == []


def test_attach_validates_existing_slots_without_launch(monkeypatch, tmp_path):
    commands = native_fixture(monkeypatch, slots=2)
    with cli.ModelServer(tmp_path, tmp_path, 2, 32768, port=9911, attach=True) as server:
        assert server.props['total_slots'] == 2
    assert commands == []
    with pytest.raises(ValueError, match='SERVED_SLOTS_MISMATCH'):
        with cli.ModelServer(tmp_path, tmp_path, 8, 32768, port=9911, attach=True):
            pass


def test_legacy_owned_fixture_may_omit_slots_but_attach_requires_verification(monkeypatch, tmp_path):
    commands = native_fixture(monkeypatch, include_slots=False)
    with cli.ModelServer(tmp_path, tmp_path, 8, 32768, port=9911):
        pass
    assert len(commands) == 1
    with pytest.raises(ValueError, match='SERVED_SLOTS_NOT_VERIFIED'):
        with cli.ModelServer(tmp_path, tmp_path, 8, 32768, port=9911, attach=True):
            pass
    assert len(commands) == 1


@pytest.mark.parametrize('flags', [['--slots', '0'], ['--slots', '-1'], ['--spec-type', 'other'],
    ['--attach', '--port', '9911', '--fast'], ['--attach', '--port', '9911', '--batch-size', '8192'],
    ['--attach', '--port', '9911', '--ubatch-size', '512'],
    ['--attach', '--port', '9911', '--spec-type', 'ngram-mod']])
def test_cli_rejects_invalid_profile_before_reading_input(tmp_path, flags):
    with pytest.raises(SystemExit) as error:
        cli.main(['--input', str(tmp_path / 'nonexistent-input.csv'), '--output', str(tmp_path / 'out.parquet'), *flags])
    assert error.value.code == 2


def cli_fixture(monkeypatch, tmp_path, predict):
    launches = []
    class Server:
        port, api_key, props = 9911, None, {}
        def __init__(self, root, work, slots, context, **kwargs):
            launches.append(dict(slots=slots, context=context, **kwargs))
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(cli, 'ModelServer', Server)
    monkeypatch.setattr(cli, 'predict_one', predict)
    source = tmp_path / 'input.csv'
    source.write_text('id,prompt,response\n001,p,r\n002,p,r\n003,p,r\n004,p,r\n', encoding='utf-8')
    output, work = tmp_path / 'out.parquet', tmp_path / 'work'
    return launches, output, work, ['--input', str(source), '--output', str(output), '--work-dir', str(work)]


@pytest.mark.parametrize('workers,slots', [(4, 2), (2, 4)])
def test_cli_row_workers_are_independent_from_native_slots(monkeypatch, tmp_path, workers, slots):
    barrier = threading.Barrier(workers)
    lock = threading.Lock()
    running = dict(active=0, peak=0)
    def predict(row, client, layers, profile):
        with lock:
            running['active'] += 1
            running['peak'] = max(running['peak'], running['active'])
        barrier.wait(timeout=5)
        with lock:
            running['active'] -= 1
        return dict(id=row['id'], binary=1)
    launches, output, work, arguments = cli_fixture(monkeypatch, tmp_path, predict)
    cli.main([*arguments, '--workers', str(workers), '--slots', str(slots), '--spec-type', 'ngram-mod'])
    assert running['peak'] == workers
    assert launches[0]['slots'] == slots and launches[0]['context'] == 32768
    assert launches[0]['spec_type'] == 'ngram-mod'
    assert pd.read_parquet(output).to_dict('records') == [dict(id=f'{i:03d}', label=1) for i in range(1, 5)]
    report = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    assert report['workers'] == workers and report['gpu_slots'] == slots and report['spec_type'] == 'ngram-mod'


def test_cli_defaults_keep_slots_equal_workers_and_zero_recovery(monkeypatch, tmp_path):
    def predict(row, *args):
        return dict(id=row['id'], binary=None, error='test technical failure')
    launches, output, work, arguments = cli_fixture(monkeypatch, tmp_path, predict)
    cli.main(arguments)
    assert launches[0]['slots'] == 8 and launches[0]['spec_type'] is None
    report = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    assert report['workers'] == report['gpu_slots'] == 8
    assert report['spec_type'] == 'none' and report['default_zero_fallbacks'] == 4
    assert pd.read_parquet(output)['label'].tolist() == [0, 0, 0, 0]


def test_cli_explicit_none_retains_default_native_profile(monkeypatch, tmp_path):
    launches, _, work, arguments = cli_fixture(monkeypatch, tmp_path,
        lambda row, *a: dict(id=row['id'], binary=0))
    cli.main([*arguments, '--workers', '3', '--spec-type', 'none'])
    assert launches[0]['slots'] == 3 and launches[0]['spec_type'] is None
    report = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    assert report['workers'] == report['gpu_slots'] == 3 and report['spec_type'] == 'none'


def test_longest_first_changes_execution_order_only_and_keeps_all_original_outputs(monkeypatch, tmp_path):
    calls = []
    def predict(row, client, layers, profile):
        calls.append((row['id'], row['prompt'], row['response'], profile))
        assert layers.skip_inapplicable_f is True
        return dict(id=row['id'], binary=int(row['response'] == 'one'))
    launches, output, work, arguments = cli_fixture(monkeypatch, tmp_path, predict)
    source = tmp_path / 'input.csv'
    source.write_text('id,prompt,response\nshort,p,zero\nlong,very long prompt,one\ntieA,tie,zero\ntieB,tie,zero\n',
                      encoding='utf-8')
    cli.main([*arguments, '--workers', '1', '--slots', '8', '--queue-order', 'longest-first', '--skip-inapplicable-f'])
    assert [c[0] for c in calls] == ['long', 'tieA', 'tieB', 'short']
    assert pd.read_parquet(output).to_dict('records') == [dict(id='short', label=0), dict(id='long', label=1),
                                                       dict(id='tieA', label=0), dict(id='tieB', label=0)]
    report = json.loads((work / 'run.json').read_text(encoding='utf-8'))
    assert report['submission_order'] == [c[0] for c in calls]
    assert report['queue_order'] == 'longest-first' and report['skip_inapplicable_f'] is True
    assert launches[0]['slots'] == 8


def test_source_scheduling_never_uses_gold_or_id_and_default_keeps_original_order():
    rows = [dict(id='ZZ', prompt='p', response='r', label=1),
            dict(id='AA', prompt='longer', response='r', label=0)]
    assert cli.scheduled_rows(rows) == rows
    assert cli.scheduled_rows(rows, 'longest-first') == list(reversed(rows))
    relabeled = [dict(r, id=str(i), label=1-r['label']) for i, r in enumerate(rows)]
    assert [r['prompt'] for r in cli.scheduled_rows(relabeled, 'longest-first')] == ['longer', 'p']
    with pytest.raises(ValueError, match='INVALID_QUEUE_ORDER'):
        cli.scheduled_rows(rows, 'unsupported')
