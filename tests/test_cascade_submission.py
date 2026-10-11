import csv
import json
import sys
import time
import types
from pathlib import Path

import pytest

from scripts import cascade_submission as cs


@pytest.fixture(autouse=True)
def bundled_qwen(tmp_path):
    (tmp_path / 'model' / cs.QWEN_REVISION).mkdir(parents=True)


def rows(n):
    return [dict(id=f'r{i}', prompt=f'p{i}', response=f'a{i}') for i in range(n)]


def write_input(tmp_path, data):
    import pandas as pd
    path = tmp_path / 'test.csv'
    pd.DataFrame(data).to_csv(path, index=False)
    return path


def read_csv(path):
    with open(path, newline='', encoding='utf-8') as stream:
        return [(r['id'], int(r['label'])) for r in csv.DictReader(stream)]


def test_write_labels_csv_and_parquet(tmp_path):
    cs.write_labels(tmp_path / 'o.csv', ['a', 'b'], {'a': 1, 'b': 0})
    assert read_csv(tmp_path / 'o.csv') == [('a', 1), ('b', 0)]
    import pandas as pd
    cs.write_labels(tmp_path / 'o.parquet', ['a', 'b'], {'a': 0, 'b': 1})
    frame = pd.read_parquet(tmp_path / 'o.parquet')
    assert list(frame.columns) == ['id', 'label'] and str(frame['label'].dtype) == 'int64'
    assert frame['label'].tolist() == [0, 1]
    assert not [p for p in tmp_path.iterdir() if p.name.endswith('.tmp')]
    with pytest.raises(ValueError):
        cs.write_labels(tmp_path / 'x.csv', ['a'], {'a': 2})
    assert not (tmp_path / 'x.csv').exists()


def test_clock_clamps_untrusted_start():
    assert cs.Clock(time.time() + 1000).elapsed() < 1
    assert 1799 < cs.Clock(time.time() - 10 ** 6).elapsed() < 1801
    assert 99 < cs.Clock(repr(time.time() - 100)).elapsed() < 101
    assert cs.Clock('garbage').elapsed() < 1


def test_read_granite_tolerates_torn_tail(tmp_path):
    path = tmp_path / 'g.jsonl'
    path.write_text('{"event":"ready","startup_s":5}\n{"id":"a","pred":1,"p_yes":0.9}\n'
                    '{"id":"b","pred":null}\n{"id":"c","pr', encoding='utf-8')
    records, ready, done = cs.read_granite(path)
    assert set(records) == {'a'} and ready['startup_s'] == 5 and not done


def fake_stages(monkeypatch, granite, *, done=True, gone=True, qwen=None, qwen_error=None, calls=None):
    def run_granite(root, python, snapshot, work, clock):
        return granite, done, gone

    def run_qwen(root, python, candidates, work, clock, on_positive):
        if calls is not None:
            calls.append([r['id'] for r in candidates])
        for identifier in qwen or []:
            on_positive(identifier)
        on_positive(None)
        if qwen_error:
            raise qwen_error
        return {}
    monkeypatch.setattr(cs, 'run_granite', run_granite)
    monkeypatch.setattr(cs, 'run_qwen', run_qwen)
    monkeypatch.setattr(cs, 'wait_gpu_released', lambda clock: None)


def g(pred, p):
    return dict(pred=pred, p_yes=p)


def test_cascade_or_and_order(tmp_path, monkeypatch):
    data = rows(5)
    calls = []
    granite = {'r0': g(1, .9), 'r1': g(0, .1), 'r2': g(0, .4), 'r3': g(0, .4), 'r4': g(0, .0)}
    fake_stages(monkeypatch, granite, qwen=['r3'], calls=calls)
    out = tmp_path / 'pred.csv'
    assert cs.run(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert calls == [['r2', 'r3', 'r1', 'r4']]  # P(yes) desc, ties in input order
    assert read_csv(out) == [('r0', 1), ('r1', 0), ('r2', 0), ('r3', 1), ('r4', 0)]


def test_long_csv_fields(tmp_path, monkeypatch):
    import csv as csv_module
    csv_module.field_size_limit(131072)
    data = rows(2)
    data[1]['prompt'] = 'x' * 300000 + '\n"quoted",\n' + 'y' * 1000
    fake_stages(monkeypatch, {'r0': g(0, .1), 'r1': g(1, 1)})
    out = tmp_path / 'pred.csv'
    assert cs.run(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 0), ('r1', 1)]
    import pandas as pd
    assert pd.read_parquet(tmp_path / 'w' / 'input.parquet')['prompt'][1] == data[1]['prompt']


def test_qwen_failure_keeps_granite_and_positives(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {'r0': g(0, .5), 'r1': g(1, 1)}, qwen=['r0'], qwen_error=RuntimeError('VLLM_START_FAILED'))
    out = tmp_path / 'pred.csv'
    assert cs.run(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 1), ('r1', 1)]


def test_signal_during_qwen_writes_then_reraises(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {'r0': g(0, .5), 'r1': g(1, 1)}, qwen=['r0'], qwen_error=SystemExit(143))
    out = tmp_path / 'pred.csv'
    with pytest.raises(SystemExit):
        cs.run(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w')
    assert read_csv(out) == [('r0', 1), ('r1', 1)]


def test_no_granite_means_failure_without_output(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {})
    out = tmp_path / 'pred.csv'
    with pytest.raises(RuntimeError, match='GRANITE_PRODUCED_NO_PREDICTIONS'):
        cs.run(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w')
    assert not out.exists()


@pytest.mark.parametrize('kwargs', [dict(done=False), dict(gone=False)])
def test_qwen_skipped_on_incomplete_granite(tmp_path, monkeypatch, kwargs):
    calls = []
    fake_stages(monkeypatch, {'r0': g(1, 1)}, calls=calls, **kwargs)  # r1 missing -> 0
    out = tmp_path / 'pred.csv'
    assert cs.run(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
    assert calls == [] and read_csv(out) == [('r0', 1), ('r1', 0)]


def test_qwen_skipped_when_late(tmp_path, monkeypatch):
    calls = []
    fake_stages(monkeypatch, {'r0': g(0, .2)}, calls=calls)
    out = tmp_path / 'pred.csv'
    cs.run(tmp_path, write_input(tmp_path, rows(1)), out, work=tmp_path / 'w',
           started_wall=time.time() - cs.QWEN_LAUNCH_LATEST - 5)
    assert calls == [] and read_csv(out) == [('r0', 0)]


def test_empty_input(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {})
    path = tmp_path / 'e.csv'
    path.write_text('id,prompt,response\n', encoding='utf-8')
    assert cs.run(tmp_path, path, tmp_path / 'o.csv', work=tmp_path / 'w') == 0
    assert read_csv(tmp_path / 'o.csv') == []


class FakeInner:
    model = 'm'

    def __init__(self, statuses):
        self.statuses = statuses
        self.completion_http = 0

    def call(self, request, attempt=0, tag=''):
        status = self.statuses.pop(0)
        if isinstance(status, BaseException):
            raise status
        return dict(transport=dict(status=status))


def test_row_tagging_client():
    client = cs.RowTaggingClient(FakeInner([200, 'NOT_EXECUTED_CONTEXT_BUDGET', 'EXC', ValueError('x')]))
    client.local.row = 'a'
    client.call({}); client.call({}, attempt=1)
    assert client.unclean == set() and client.model == 'm'
    client.local.row = 'b'
    client.call({})
    client.local.row = 'c'
    with pytest.raises(ValueError):
        client.call({})
    assert client.unclean == {'b', 'c'}


def test_run_qwen_with_fake_engine(tmp_path, monkeypatch):
    """Clean positives are reported; unclean rows and late rows are not."""
    adapter = types.ModuleType('scripts.qwen_vllm_adapter')
    adapter.ENGINE_VERSION = '0.19.1'

    class Server:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            self.port, self.api_key, self.manifest = 1, 'k', {}
        def __enter__(self):
            return self
        def __exit__(self, *args):
            return False

    class Client:
        completion_http = 0
        def __init__(self, *args, **kwargs):
            self.model = adapter.MODEL
        def call(self, request, attempt=0, tag=''):
            return dict(transport=dict(status='EXC' if request['id'] == 'r1' else 200))
    adapter.OwnedVllmServer, adapter.VllmClient = Server, Client
    monkeypatch.setitem(sys.modules, 'scripts.qwen_vllm_adapter', adapter)
    import scripts
    monkeypatch.setattr(scripts, 'qwen_vllm_adapter', adapter, raising=False)
    pipeline = types.ModuleType('guardian_truth.v6fix.pipeline')
    pipeline.Layers = lambda client, model, **kw: None
    monkeypatch.setitem(sys.modules, 'guardian_truth.v6fix.pipeline', pipeline)
    cli = types.ModuleType('guardian_truth.submission.cli')

    def predict_one(row, client, layers, model=None, provider=None):
        client.call(dict(id=row['id']))
        return dict(binary=1 if row['id'] != 'r2' else 0)
    cli.predict_one = predict_one
    monkeypatch.setitem(sys.modules, 'guardian_truth.submission.cli', cli)
    positives = []
    clock = cs.Clock()
    stats = cs.run_qwen(tmp_path, 'py', rows(4), tmp_path, clock, positives.append)
    assert sorted(p for p in positives if p) == ['r0', 'r3']
    assert stats['clean'] == 3 and stats['unclean'] == 1 and stats['positives'] == 2
    assert adapter.QUANT_METHODS == cs.QWEN_QUANT_METHODS and adapter.REVISION == cs.QWEN_REVISION
    late = cs.Clock(time.time() - cs.ACCEPT_UNTIL - 1)
    positives.clear()
    (tmp_path / 'late').mkdir()
    stats = cs.run_qwen(tmp_path, 'py', rows(2), tmp_path / 'late', late, positives.append)
    assert stats['skipped_late'] == 2 and not [p for p in positives if p]


def test_granite_only_variant_skips_qwen(tmp_path, monkeypatch):
    import shutil
    shutil.rmtree(tmp_path / 'model' / cs.QWEN_REVISION)
    calls = []
    fake_stages(monkeypatch, {'r0': g(0, .9), 'r1': g(1, 1)}, calls=calls)
    out = tmp_path / 'pred.csv'
    assert cs.run(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
    assert calls == [] and read_csv(out) == [('r0', 0), ('r1', 1)]


def test_read_input_csv_quirks(tmp_path):
    path = tmp_path / 'q.csv'
    big = 'z' * 200000
    text = ('\ufeff Id ,extra,PROMPT,response\r\n'
            '7,x,"line1\r\nline2, ""q""",ok\r\n'
            '8,y,' + big + ',\r\n'
            '7,z,,dup\r\n')
    path.write_bytes(text.encode('utf-8') + b'9,w,\xff\xfe bad bytes,r\r\n')
    got = cs.read_input(path)
    assert [r['id'] for r in got] == ['7', '8', '7', '9']
    assert got[0]['prompt'] == 'line1\r\nline2, "q"' and got[0]['response'] == 'ok'
    assert got[1]['prompt'] == big and got[1]['response'] == ''
    assert got[2]['prompt'] == '' and '\ufffd' in got[3]['prompt']


def test_read_input_parquet_nulls_and_int_ids(tmp_path):
    import pandas as pd
    path = tmp_path / 'p.bin'
    pd.DataFrame({'id': [1, 2], 'prompt': ['a', None], 'response': [None, 'b'], 'label': [0, 1]}).to_parquet(path)
    assert cs.read_input(path) == [dict(id='1', prompt='a', response=''), dict(id='2', prompt='', response='b')]
    with pytest.raises(ValueError, match='REQUIRED_COLUMNS'):
        bad = tmp_path / 'b.csv'
        bad.write_text('id,text\n1,a\n', encoding='utf-8')
        cs.read_input(bad)


def test_duplicate_ids_keep_all_rows(tmp_path, monkeypatch):
    data = [dict(id='a', prompt='p', response='r'), dict(id='a', prompt='p2', response='r2'),
            dict(id='b', prompt='p', response='r')]
    fake_stages(monkeypatch, {'a': g(1, 1), 'b': g(0, 0)})
    out = tmp_path / 'pred.csv'
    cs.run(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w')
    assert read_csv(out) == [('a', 1), ('a', 1), ('b', 0)]


def test_kill_group_falls_back_to_killpg(monkeypatch):
    import subprocess
    process = subprocess.Popen(['sleep', '60'], start_new_session=True)
    def broken(*args):
        raise OSError('pidfd blocked')
    monkeypatch.setattr(cs, '_kill_owned_group', broken)
    assert cs.kill_owned_group(process.pid, 'tok', seconds=(3, 2)) is True
    process.wait(timeout=5)
    assert process.returncode is not None


def test_entrypoint_ignores_unknown_args(tmp_path, monkeypatch):
    import importlib.util
    spec = importlib.util.spec_from_file_location('entry', Path(__file__).resolve().parents[1] / 'submission/predict_cascade.py')
    entry = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(entry)
    monkeypatch.setattr(entry, 'bootstrap', lambda root, arguments: None)
    seen = {}
    monkeypatch.setattr(cs, 'run', lambda root, i, o, **kw: seen.update(i=i, o=o) or 0)
    assert entry.main(['--input', 'a.csv', '--output', 'b.csv', '--gpus', '1']) == 0
    assert seen['i'].name == 'a.csv' and seen['o'].name == 'b.csv'
