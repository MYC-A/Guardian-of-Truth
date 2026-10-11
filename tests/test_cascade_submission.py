import csv
import json
import sys
import time
import types
from pathlib import Path

import pytest

from scripts import cascade_submission as cs


def _run_nowd(*args, **kwargs):
    return cs.run(*args, watchdog=False, **kwargs)


cs.run_nowd = _run_nowd


@pytest.fixture(autouse=True)
def bundled_qwen(tmp_path):
    (tmp_path / 'model' / cs.QWEN_REVISION).mkdir(parents=True)
    (tmp_path / cs.GRANITE_MODEL).mkdir(parents=True)


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
    import stat
    for name in ('o.csv', 'o.parquet'):
        assert stat.S_IMODE((tmp_path / name).stat().st_mode) & 0o444 == 0o444  # readable by everyone
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


def fake_stages(monkeypatch, granite, *, done=True, gone=True, qwen=None, qwen_error=None, calls=None, ids=None):
    """granite: {original id: result} in input order, or a per-row list. Stages see internal row keys."""
    if isinstance(granite, dict):
        ids = list(granite) if ids is None else ids
        per_row = [granite.get(i) for i in ids]
    else:
        per_row = list(granite)
    key = lambda k: 'row%07d' % k
    seen = {}

    def run_granite(root, python, snapshot, work, clock):
        import pandas as pd
        snap = pd.read_parquet(snapshot)
        assert list(snap['id']) == [key(k) for k in range(len(snap))]
        seen['n'] = len(snap)
        return {key(k): r for k, r in enumerate(per_row) if r is not None}, done, gone

    def run_qwen(root, python, candidates, work, clock, on_positive):
        if calls is not None:
            calls.append([ids[int(r['id'][3:])] if ids else r['id'] for r in candidates])
        for identifier in qwen or []:
            on_positive(key(ids.index(identifier)) if ids and identifier in ids else identifier)
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
    assert cs.run_nowd(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert calls == [['r2', 'r3', 'r1', 'r4']]  # P(yes) desc, ties in input order
    assert read_csv(out) == [('r0', 1), ('r1', 0), ('r2', 0), ('r3', 1), ('r4', 0)]


def test_long_csv_fields(tmp_path, monkeypatch):
    import csv as csv_module
    csv_module.field_size_limit(131072)
    data = rows(2)
    data[1]['prompt'] = 'x' * 300000 + '\n"quoted",\n' + 'y' * 1000
    fake_stages(monkeypatch, {'r0': g(0, .1), 'r1': g(1, 1)})
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 0), ('r1', 1)]
    import pandas as pd
    assert pd.read_parquet(tmp_path / 'w' / 'input.parquet')['prompt'][1] == data[1]['prompt']


def test_qwen_failure_keeps_granite_and_positives(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {'r0': g(0, .5), 'r1': g(1, 1)}, qwen=['r0'], qwen_error=RuntimeError('VLLM_START_FAILED'))
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 1), ('r1', 1)]


def test_signal_during_qwen_writes_then_reraises(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {'r0': g(0, .5), 'r1': g(1, 1)}, qwen=['r0'], qwen_error=SystemExit(143))
    out = tmp_path / 'pred.csv'
    with pytest.raises(SystemExit):
        cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w')
    assert read_csv(out) == [('r0', 1), ('r1', 1)]


def test_no_granite_means_failure_without_output(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {})
    out = tmp_path / 'pred.csv'
    with pytest.raises(RuntimeError, match='GRANITE_PRODUCED_NO_PREDICTIONS'):
        cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w')
    assert not out.exists()


@pytest.mark.parametrize('kwargs', [dict(done=False), dict(gone=False)])
def test_qwen_skipped_on_incomplete_granite(tmp_path, monkeypatch, kwargs):
    calls = []
    fake_stages(monkeypatch, {'r0': g(1, 1)}, calls=calls, **kwargs)  # r1 missing -> 0
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
    assert calls == [] and read_csv(out) == [('r0', 1), ('r1', 0)]


def test_qwen_skipped_when_late(tmp_path, monkeypatch):
    calls = []
    fake_stages(monkeypatch, {'r0': g(0, .2)}, calls=calls)
    out = tmp_path / 'pred.csv'
    cs.run_nowd(tmp_path, write_input(tmp_path, rows(1)), out, work=tmp_path / 'w',
           started_wall=time.time() - cs.QWEN_LAUNCH_LATEST - 5)
    assert calls == [] and read_csv(out) == [('r0', 0)]


def test_empty_input(tmp_path, monkeypatch):
    fake_stages(monkeypatch, {})
    path = tmp_path / 'e.csv'
    path.write_text('id,prompt,response\n', encoding='utf-8')
    assert cs.run_nowd(tmp_path, path, tmp_path / 'o.csv', work=tmp_path / 'w') == 0
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


SERVERS = []


def test_run_qwen_with_fake_engine(tmp_path, monkeypatch, variant='awq'):
    """Clean positives are reported; unclean rows and late rows are not."""
    adapter = types.ModuleType('scripts.qwen_vllm_adapter')
    adapter.ENGINE_VERSION = '0.19.1'
    SERVERS.clear()

    class Server:
        def __init__(self, *args, **kwargs):
            self.kwargs = kwargs
            SERVERS.append((args, kwargs))
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
    profile = cs.QWEN_PROFILES[variant]
    assert adapter.QUANT_METHODS == profile['quant'] and adapter.REVISION == profile['revision']
    assert adapter.EXTRA_SERVER_ARGS == profile['server_args']
    args, kwargs = SERVERS[0]
    assert args[1] == tmp_path / 'model' / profile['revision'] and args[4] == profile['slots']
    assert kwargs['asset_manifest'] == tmp_path / profile['manifest']
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
    assert cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), out, work=tmp_path / 'w') == 0
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
    # Repeated ids are distinct rows: each keeps its own label, output follows input order verbatim.
    data = [dict(id='a', prompt='p', response='r'), dict(id='a', prompt='p2', response='r2'),
            dict(id='b', prompt='p', response='r'), dict(id='a', prompt='p3', response='r3')]
    calls = []
    fake_stages(monkeypatch, [g(1, 1), g(0, .2), g(0, 0), g(0, .7)], calls=calls)
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('a', 1), ('a', 0), ('b', 0), ('a', 0)]
    assert calls == [['row0000003', 'row0000001', 'row0000002']]


def test_duplicate_ids_qwen_positive_hits_one_row(tmp_path, monkeypatch):
    data = [dict(id='x', prompt='p', response='r'), dict(id='x', prompt='p2', response='r2')]

    def run_qwen(root, python, candidates, work, clock, on_positive):
        on_positive(candidates[-1]['id'])
        on_positive(None)
    fake_stages(monkeypatch, [g(0, .9), g(0, .1)])
    monkeypatch.setattr(cs, 'run_qwen', run_qwen)
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('x', 0), ('x', 1)]


def test_ids_written_verbatim(tmp_path, monkeypatch):
    data = [dict(id=' 007 ', prompt='p', response='r'), dict(id='1.0', prompt='p', response='r'),
            dict(id='id,"q"', prompt='p', response='r')]
    fake_stages(monkeypatch, [g(1, 1), g(0, 0), g(1, 1)])
    out = tmp_path / 'pred.csv'
    with open(tmp_path / 'test.csv', 'w', newline='', encoding='utf-8') as stream:
        writer = csv.DictWriter(stream, ['id', 'prompt', 'response'])
        writer.writeheader()
        writer.writerows(data)
    assert cs.run_nowd(tmp_path, tmp_path / 'test.csv', out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [(' 007 ', 1), ('1.0', 0), ('id,"q"', 1)]


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


def test_watchdog_exit_code(tmp_path):
    import threading
    codes, fired = [], threading.Event()
    def fake_exit(code):
        codes.append(code); fired.set()
    clock = cs.Clock(time.time() - cs.WATCHDOG)
    cs.start_watchdog(clock, tmp_path / 'none.csv', exit=fake_exit)
    assert fired.wait(5) and codes == [1]
    (tmp_path / 'o.csv').write_text('id,label\n')
    fired.clear()
    cs.start_watchdog(clock, tmp_path / 'o.csv', exit=fake_exit)
    assert fired.wait(5) and codes == [1, 0]


def qwen_only(tmp_path, monkeypatch, trace_binary, *, error=None, positives_before_error=()):
    import shutil
    shutil.rmtree(tmp_path / cs.GRANITE_MODEL)
    seen = []

    def run_granite(*args):
        raise AssertionError('granite must not run')

    def run_qwen(root, python, candidates, work, clock, on_positive):
        seen.extend(r['id'] for r in candidates)
        for r in candidates:
            if r['id'] in positives_before_error:
                on_positive(r['id'])
        on_positive(None)
        if error:
            raise error
        clean = 0
        for r in candidates:
            if trace_binary(r) == 1:
                on_positive(r['id'])
            clean += 1
        on_positive(None)
        return dict(clean=clean)
    monkeypatch.setattr(cs, 'run_granite', run_granite)
    monkeypatch.setattr(cs, 'run_qwen', run_qwen)
    return seen


def test_qwen_only_variant(tmp_path, monkeypatch):
    data = [dict(id='d', prompt=f'p{i}', response='hall' if i % 3 == 0 else 'ok') for i in range(9)]
    by_key = {}
    seen = qwen_only(tmp_path, monkeypatch, lambda r: int(r['response'] == 'hall'))
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, data), out, work=tmp_path / 'w') == 0
    keys = ['row%07d' % k for k in range(9)]
    assert sorted(seen) == keys and seen != keys  # all rows, seeded shuffle
    assert read_csv(out) == [('d', int(i % 3 == 0)) for i in range(9)]


def test_qwen_only_order_is_deterministic(tmp_path, monkeypatch):
    first = qwen_only(tmp_path, monkeypatch, lambda r: 0)
    cs.run_nowd(tmp_path, write_input(tmp_path, rows(20)), tmp_path / 'a.csv', work=tmp_path / 'w1')
    second = []
    monkeypatch.setattr(cs, 'run_qwen', lambda root, python, c, work, clock, op: (second.extend(r['id'] for r in c),
                                                                                  dict(clean=1))[1])
    cs.run_nowd(tmp_path, write_input(tmp_path, rows(20)), tmp_path / 'b.csv', work=tmp_path / 'w2')
    assert first == second


def test_qwen_only_no_clean_rows_fails_without_output(tmp_path, monkeypatch):
    qwen_only(tmp_path, monkeypatch, lambda r: 0)
    monkeypatch.setattr(cs, 'run_qwen', lambda *a: dict(clean=0))
    out = tmp_path / 'pred.csv'
    with pytest.raises(RuntimeError, match='QWEN_PRODUCED_NO_PREDICTIONS'):
        cs.run_nowd(tmp_path, write_input(tmp_path, rows(3)), out, work=tmp_path / 'w')
    assert not out.exists()


def test_qwen_only_failure_before_any_positive_raises(tmp_path, monkeypatch):
    qwen_only(tmp_path, monkeypatch, lambda r: 0, error=RuntimeError('VLLM_START_FAILED'))
    out = tmp_path / 'pred.csv'
    with pytest.raises(RuntimeError, match='VLLM_START_FAILED'):
        cs.run_nowd(tmp_path, write_input(tmp_path, rows(3)), out, work=tmp_path / 'w')
    assert not out.exists()


def test_qwen_only_failure_after_positive_keeps_them(tmp_path, monkeypatch):
    qwen_only(tmp_path, monkeypatch, lambda r: 0, error=RuntimeError('ENGINE_DIED'),
              positives_before_error=('row0000001',))
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, rows(3)), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 0), ('r1', 1), ('r2', 0)]


def test_no_model_bundled(tmp_path, monkeypatch):
    import shutil
    qwen_only(tmp_path, monkeypatch, lambda r: 0)
    shutil.rmtree(tmp_path / 'model' / cs.QWEN_REVISION)
    with pytest.raises(RuntimeError, match='NO_MODEL_BUNDLED'):
        cs.run_nowd(tmp_path, write_input(tmp_path, rows(2)), tmp_path / 'p.csv', work=tmp_path / 'w')


def test_run_qwen_fp8_profile(tmp_path, monkeypatch):
    import shutil
    shutil.rmtree(tmp_path / 'model' / cs.QWEN_REVISION)
    (tmp_path / 'model' / cs.QWEN_PROFILES['fp8']['revision']).mkdir()
    assert cs.qwen_profile(tmp_path)[0] == 'fp8'
    test_run_qwen_with_fake_engine(tmp_path, monkeypatch, variant='fp8')


def test_fp8_profile_matches_old_production_adapter():
    from scripts import qwen_vllm_adapter as adapter
    fp8 = cs.QWEN_PROFILES['fp8']
    assert (adapter.REPOSITORY, adapter.REVISION) == (fp8['repository'], fp8['revision'])
    assert tuple(adapter.QUANT_METHODS) == fp8['quant'] and tuple(adapter.EXTRA_SERVER_ARGS) == fp8['server_args']


def test_qwen_only_with_fp8(tmp_path, monkeypatch):
    import shutil
    seen = qwen_only(tmp_path, monkeypatch, lambda r: int(r['id'] == 'row0000001'))
    shutil.rmtree(tmp_path / 'model' / cs.QWEN_REVISION)
    (tmp_path / 'model' / cs.QWEN_PROFILES['fp8']['revision']).mkdir()
    out = tmp_path / 'pred.csv'
    assert cs.run_nowd(tmp_path, write_input(tmp_path, rows(3)), out, work=tmp_path / 'w') == 0
    assert read_csv(out) == [('r0', 0), ('r1', 1), ('r2', 0)] and len(seen) == 3
