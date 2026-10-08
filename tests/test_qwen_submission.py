import csv
import json
from pathlib import Path

import pandas as pd
import pytest

from guardian_truth.submission.cli import LocalClient, read_rows, write_predictions, main


def test_csv_keeps_ids_and_drops_gold(tmp_path):
    source = tmp_path / 'input.csv'
    with source.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=['id', 'prompt', 'response', 'label', 'explanation'])
        writer.writeheader()
        writer.writerows([dict(id=i, prompt='⟦USER⟧ test', response='', label=1, explanation='secret') for i in ['001', '1']])
    assert read_rows(source) == [dict(id=i, prompt='⟦USER⟧ test', response='') for i in ['001', '1']]


@pytest.mark.parametrize('rows', [
    [dict(id='a', prompt='p', response='r'), dict(id='a', prompt='p', response='r')],
    [dict(id='a', prompt=None, response='r')],
    [dict(id=1, prompt='p', response='r')],
])
def test_invalid_input_rejected_before_inference(tmp_path, rows):
    path = tmp_path / 'data.parquet'
    pd.DataFrame(rows).to_parquet(path)
    with pytest.raises(ValueError):
        read_rows(path)


def test_duplicate_csv_columns(tmp_path):
    path = tmp_path / 'input.csv'
    path.write_text('id,prompt,response,prompt\na,p,r,p\n', encoding='utf-8')
    with pytest.raises(ValueError, match='DUPLICATE_COLUMNS'):
        read_rows(path)


def test_empty_dataset_does_not_start_model(tmp_path):
    source, dest = tmp_path / 'input.csv', tmp_path / 'predictions.csv'
    source.write_text('id,prompt,response\n', encoding='utf-8')
    main(['--input', str(source), '--output', str(dest)])
    result = pd.read_parquet(dest)
    assert list(result.columns) == ['id', 'label']
    assert len(result) == 0


def test_output_parquet_even_csv_extension(tmp_path):
    path = tmp_path / 'predictions.csv'
    write_predictions(path, [dict(id='001', label=1), dict(id='1', label=0)])
    assert path.read_bytes()[:4] == b'PAR1'
    assert pd.read_parquet(path).to_dict('records') == [dict(id='001', label=1), dict(id='1', label=0)]


def test_client_reserves_completion_and_never_sends_overflow(monkeypatch):
    from guardian_truth.submission import cli
    calls = []
    def fake(url, payload=None, timeout=20, api_key=None):
        calls.append(url)
        return dict(input_tokens=32000)
    monkeypatch.setattr(cli, 'http_json', fake)
    client = LocalClient(9999, 32768)
    record = client.call(dict(model=client.model, messages=[], max_tokens=1700))
    assert record['transport']['status'] == 'NOT_EXECUTED_CONTEXT_BUDGET'
    assert len(calls) == 1


def test_client_exact_request_attempt_cache(monkeypatch):
    from guardian_truth.submission import cli
    calls = []
    def fake(url, payload=None, timeout=20, api_key=None):
        calls.append(url)
        if url.endswith('/input_tokens'):
            return dict(input_tokens=12)
        return dict(choices=[dict(message=dict(content='{}'), finish_reason='stop')], usage={})
    monkeypatch.setattr(cli, 'http_json', fake)
    client = LocalClient(9999, 32768)
    request = dict(model=client.model, messages=[], max_tokens=1700)
    client.call(request)
    assert client.call(request)['cached'] is True
    client.call(request, attempt=1)
    assert len(calls) == 4


def test_rejected_primary_cannot_become_negative(monkeypatch):
    from guardian_truth.repair import v5
    from guardian_truth.submission.cli import predict_one
    class Layers:
        def findings(self, row):
            return dict(findings=[])
    monkeypatch.setattr(v5, 'run_v5', lambda *a, **k: dict(
        A=dict(final=None, steps=[dict(admission='REJECTED:ValidationError', raw_content='{}', transport=dict(status=200))]),
        A_adm2=dict(decision=None, admission='REJECTED:ValidationError')))
    trace = predict_one(dict(id='a', prompt='p', response='r'), LocalClient(9999, 32768), Layers())
    assert trace['binary'] is None
    assert trace['error'] == 'PRIMARY_INFERENCE_FAILURE'


def test_occupied_port_does_not_spawn(monkeypatch, tmp_path):
    import socket
    from guardian_truth.submission import cli
    def forbidden(*a, **k):
        pytest.fail('must not spawn with occupied port')
    monkeypatch.setattr(cli.subprocess, 'Popen', forbidden)
    with socket.socket() as listener:
        listener.bind(('127.0.0.1', 0))
        listener.listen()
        with pytest.raises(OSError):
            with cli.ModelServer(tmp_path, tmp_path, 1, 32768, port=listener.getsockname()[1]):
                pass
