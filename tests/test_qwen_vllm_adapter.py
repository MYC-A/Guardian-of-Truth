"""Offline transport contracts; never starts vLLM or calls HTTP."""
import copy
from concurrent.futures import ThreadPoolExecutor
import json
import time

import pytest

from scripts import qwen_vllm_adapter as adapter


def request(**changes):
    return dict(dict(model=adapter.MODEL, temperature=0, max_tokens=12,
        messages=[dict(role='system', content='Return JSON'), dict(role='user', content='source text')],
        response_format=dict(type='json_schema', json_schema=dict(name='test', strict=True,
            schema=dict(type='object', properties=dict(decision=dict(type='string')), required=['decision'])))), **changes)


def payload(value):
    return json.dumps(value).encode()


def response(**changes):
    return dict(dict(model=adapter.MODEL, usage=dict(prompt_tokens=3, completion_tokens=4),
        choices=[dict(finish_reason='stop', message=dict(content='{"decision":"NO_ERROR"}',
                                                        reasoning='must stay separate'))]), **changes)


class Transport:
    def __init__(self):
        self.calls = []
        self.count = dict(count=3, max_model_len=32, tokens=[1, 2, 3])
        self.reply = response()
        self.error = None

    def __call__(self, url, wire, timeout, api_key):
        self.calls.append((url, copy.deepcopy(wire), timeout))
        assert 0 < timeout <= 90
        if self.error:
            raise self.error
        return payload(self.count if url.endswith('/tokenize') else self.reply)


def client(tmp_path, transport, **changes):
    return adapter.VllmClient(8123, 32, tmp_path / 'calls', api_key='test',
        backend_manifest=dict(model=adapter.MODEL, actual_assets='offline-fixture'), transport=transport, **changes)


def test_original_wire_schema_hashes_and_raw_are_preserved(tmp_path):
    transport = Transport()
    current = client(tmp_path, transport)
    logical = request(chat_template_kwargs=dict(custom='preserve'))
    before = copy.deepcopy(logical)
    result = current.call(logical)
    assert logical == before
    assert result['transport'] == dict(status=200)
    assert result['request_sha256'] == adapter.sha(logical)
    assert result['wire_sha256'] == adapter.sha(result['wire']) != result['request_sha256']
    assert result['wire']['response_format'] == logical['response_format']
    assert result['wire']['messages'] == logical['messages']
    assert result['wire']['chat_template_kwargs'] == dict(custom='preserve', enable_thinking=False)
    assert result['content'] == '{"decision":"NO_ERROR"}'
    assert result['raw_response']['choices'][0]['message']['reasoning'] == 'must stay separate'
    assert json.loads(result['response_raw_utf8']) == transport.reply
    assert result['timings'] is None
    preflight = transport.calls[0][1]
    for key, value in preflight.items():
        assert result['wire'][key] == value
    assert preflight['add_special_tokens'] is False
    saved = json.loads((tmp_path / 'calls/00000.json').read_text(encoding='utf-8'))
    assert saved['phase'] == 'FINISHED'
    assert saved['raw_response'] == transport.reply


@pytest.mark.parametrize('changes', [dict(model='wrong'), dict(max_tokens=True), dict(max_tokens=0),
    dict(stream=True), dict(n=2), dict(messages=[]), dict(messages=[dict(role='assistant', content='prefill')]),
    dict(chat_template_kwargs=None), dict(chat_template_kwargs=dict(enable_thinking=True)),
    dict(chat_template_kwargs=dict(add_special_tokens=True)), dict(add_generation_prompt=False),
    dict(continue_final_message=True), dict(add_special_tokens=True), dict(tools=[]),
    dict(truncate_prompt_tokens=20), dict(chat_template='new')])
def test_invalid_or_unhandled_render_never_calls_http(tmp_path, changes):
    transport = Transport()
    current = client(tmp_path, transport)
    with pytest.raises(ValueError):
        current.call(request(**changes))
    assert transport.calls == []


@pytest.mark.parametrize('count', [dict(count=True, tokens=[1], max_model_len=32),
    dict(count=3, tokens=[1, 2], max_model_len=32), dict(count=3, tokens=[1, True, 3], max_model_len=32),
    dict(count=3, tokens=[1, 2, 3]), dict(count=3, tokens=[1, 2, 3], max_model_len=31)])
def test_bad_preflight_is_technical_no_completion(tmp_path, count):
    transport = Transport()
    transport.count = count
    current = client(tmp_path, transport)
    receipt = current.call(request())
    assert receipt['transport']['status'] == 'EXC'
    assert receipt['content'] is None
    assert current.completion_http == 0
    assert len(transport.calls) == 1


def test_over_context_refuses_without_truncation(tmp_path):
    transport = Transport()
    current = client(tmp_path, transport)
    receipt = current.call(request(max_tokens=30))
    assert receipt['transport']['status'] == 'NOT_EXECUTED_CONTEXT_BUDGET'
    assert receipt['wire']['max_tokens'] == 30
    assert current.completion_http == 0


@pytest.mark.parametrize('reply', [response(model='other'), response(choices=[]), response(choices=[None]),
    response(choices=[dict(message=None)]), response(choices=[dict(message=dict(content=None), finish_reason='stop')]),
    response(usage=dict(prompt_tokens=4, completion_tokens=4)),
    response(usage=dict(prompt_tokens=3, completion_tokens=True)),
    response(usage=dict(prompt_tokens=3, completion_tokens=13)),
    response(choices=[dict(message=dict(content='{"decision":"ERROR"}'), finish_reason='content_filter')])])
def test_bad_response_retains_raw_but_cannot_supply_verdict(tmp_path, reply):
    transport = Transport()
    transport.reply = reply
    current = client(tmp_path, transport)
    receipt = current.call(request())
    assert receipt['transport']['status'] == 'EXC'
    assert receipt['content'] is None
    assert receipt['raw_response'] == reply
    assert current.completion_http == 1


def test_duplicate_json_keys_rejected_with_raw_retained(tmp_path):
    transport = Transport()
    def duplicate(url, wire, timeout, api_key):
        if url.endswith('/tokenize'):
            return payload(transport.count)
        return b'{"model":"one","model":"two"}'
    current = client(tmp_path, duplicate)
    receipt = current.call(request())
    assert receipt['transport']['detail'] == 'DUPLICATE_RESPONSE_KEY'
    assert receipt['response_raw_utf8'] == '{"model":"one","model":"two"}'
    assert receipt['content'] is None


def test_singleflight_exact_attempt_cache_and_no_aliasing(tmp_path):
    transport = Transport()
    current = client(tmp_path, transport)
    with ThreadPoolExecutor(max_workers=8) as pool:
        results = list(pool.map(lambda _: current.call(request()), range(8)))
    assert current.completion_http == current.preflight_http == 1
    assert sum(r['cached'] for r in results) == 7
    results[0]['wire']['messages'][0]['content'] = 'mutated externally'
    assert current.call(request())['wire']['messages'][0]['content'] == 'Return JSON'
    current.call(request(), attempt=1)
    assert current.completion_http == 2


def test_transport_failure_has_no_hidden_retry_and_caches_failure(tmp_path):
    transport = Transport()
    transport.error = TimeoutError('synthetic timeout')
    current = client(tmp_path, transport)
    result = current.call(request())
    assert result['transport']['status'] == 'EXC'
    assert current.call(request())['cached'] is True
    assert len(transport.calls) == 1


def test_deadline_and_durable_cap(tmp_path):
    transport = Transport()
    current = client(tmp_path, transport, max_calls=1)
    current.call(request())
    result = current.call(request(max_tokens=13))
    assert result['transport']['detail'] == 'COMPLETION_CALL_CAP'
    assert current.completion_http == 1
    saved = json.loads((tmp_path / 'calls/00000.json').read_text())
    assert saved['completion_reservation'] == 1
    current.deadline = time.monotonic() - 1
    result = current.call(request(max_tokens=14))
    assert result['transport']['detail'] == 'WHOLE_RUN_DEADLINE'
    assert len(transport.calls) == 3  # first two count + first completion


def test_existing_output_cannot_load_historical_cache(tmp_path):
    transport = Transport()
    client(tmp_path, transport)
    with pytest.raises(FileExistsError):
        client(tmp_path, transport)


def test_backend_manifest_in_cache_identity(tmp_path):
    first = client(tmp_path, Transport())
    second = adapter.VllmClient(8123, 32, tmp_path / 'new', api_key='test',
        backend_manifest=dict(model=adapter.MODEL, actual_assets='different'), transport=Transport())
    assert first.call(request())['key'] != second.call(request())['key']


def test_owned_server_command_is_pinned_and_no_forced_json(tmp_path):
    # Constructor only binds an ephemeral CPU socket; no engine/network calls.
    current = adapter.OwnedVllmServer('python-pinned', tmp_path / adapter.REVISION, tmp_path, 32768, 8,
                                     deadline=time.monotonic() + 30, asset_manifest=tmp_path / 'manifest.json')
    command = current.command()
    assert command[command.index('--served-model-name') + 1] == adapter.MODEL
    assert command[command.index('--generation-config') + 1] == 'vllm'
    assert command[command.index('--chat-template-content-format') + 1] == 'string'
    assert '--reasoning-parser' not in command
    assert '--quantization' not in command  # pinned checkpoint's config, not an assumed converter


def test_original_recovery_receives_only_content(tmp_path):
    from guardian_truth.submission.recovery import recover_output
    transport = Transport()
    transport.reply['choices'][0]['message']['content'] = '{"decision":"ERROR"}'
    receipt = client(tmp_path, transport).call(request())
    recovered = recover_output(dict(binary=None, primary_receipt=receipt))
    assert recovered['binary'] == 1
    assert recovered['output_recovery']['mode'] == 'RAW_MODEL_DECISION'
    assert recovered['output_recovery']['cause_status'] == 'NOT_VALIDATED'


def test_schema_provider_wire_matches_legacy_with_only_model_change():
    from guardian_truth.integrated.reviewer import body
    # Empty IDs is enough to compare prompt/schema construction; no inference.
    packet = dict(current_targets=[], sources=[])
    # This checks the actual provider branch without depending on packet schema.
    from unittest.mock import patch
    with patch('guardian_truth.integrated.reviewer.schema', return_value=dict(type='object')):
        native = body(packet, 'local-llamacpp', 'old-model')
        migrated = body(packet, 'local-vllm', adapter.MODEL)
    native['model'] = adapter.MODEL
    assert migrated == native


def checkpoint(tmp_path):
    directory = tmp_path / adapter.REVISION
    directory.mkdir()
    for name, value in {
        'config.json': dict(quantization_config=dict(quant_method='fp8')),
        'tokenizer.json': {}, 'tokenizer_config.json': dict(chat_template='pinned'),
        'model.safetensors.index.json': dict(weight_map=dict(weight='one.safetensors')),
    }.items():
        (directory / name).write_text(json.dumps(value))
    (directory / 'one.safetensors').write_bytes(b'offline-fixture')
    manifest = dict(repository='Qwen/Qwen3.8-27B-FP8', revision=adapter.REVISION,
                    files=[dict(path=p.name, size=p.stat().st_size, sha256=adapter.digest(p))
                           for p in directory.iterdir()])
    (tmp_path / 'manifest.json').write_text(json.dumps(manifest))
    return directory


@pytest.mark.parametrize('failure', ['engine', 'revision', 'quantization', 'shard', 'shard_escape'])
def test_owned_server_refuses_bad_assets_before_spawn(tmp_path, monkeypatch, failure):
    directory = checkpoint(tmp_path)
    monkeypatch.setattr(adapter.subprocess, 'check_output', lambda *a, **k:
                        'wrong-version' if failure == 'engine' else adapter.ENGINE_VERSION)
    def no_spawn(*args, **kwargs):
        pytest.fail('must refuse before starting GPU process')
    monkeypatch.setattr(adapter.subprocess, 'Popen', no_spawn)
    if failure == 'revision':
        wrong = tmp_path / 'wrong-revision'
        directory.rename(wrong)
        directory = wrong
    elif failure == 'quantization':
        (directory / 'config.json').write_text('{}')
    elif failure == 'shard':
        (directory / 'one.safetensors').unlink()
    elif failure == 'shard_escape':
        (directory / 'model.safetensors.index.json').write_text(json.dumps(dict(weight_map=dict(a='../escape.safetensors'))))
    server = adapter.OwnedVllmServer('python', directory, tmp_path, 32, 1, deadline=time.monotonic() + 10,
                                   asset_manifest=tmp_path / 'manifest.json')
    with pytest.raises(ValueError):
        server.__enter__()


@pytest.mark.parametrize('served_context', [None, 31, True, 32])
def test_owned_server_readiness_and_cleanup_offline(tmp_path, monkeypatch, served_context):
    directory = checkpoint(tmp_path)
    monkeypatch.setattr(adapter.subprocess, 'check_output', lambda *a, **k: adapter.ENGINE_VERSION)
    class Process:
        pid = 123456789
        def __init__(self):
            self.stopped = False
        def poll(self):
            return 0 if self.stopped else None
        def terminate(self):
            self.stopped = True
        def wait(self, timeout):
            self.stopped = True
    process = Process()
    monkeypatch.setattr(adapter.subprocess, 'Popen', lambda *a, **k: process)
    monkeypatch.setattr(adapter.os, 'killpg', lambda *args: process.terminate(), raising=False)
    monkeypatch.setattr(adapter, 'http', lambda *a, **k: payload(dict(data=[dict(id=adapter.MODEL,
                                                                 max_model_len=served_context)])))
    server = adapter.OwnedVllmServer('python', directory, tmp_path, 32, 1, deadline=time.monotonic() + 10,
                                   asset_manifest=tmp_path / 'manifest.json')
    if served_context == 32:
        with server:
            assert server.manifest['generation_config'] == 'vllm'
            assert server.manifest['shard_sizes'] == {'one.safetensors': 15}
            assert 'EXTERNAL_FULL_SHA_MANIFEST' in server.manifest['weight_integrity']
    else:
        with pytest.raises(ValueError):
            server.__enter__()
    assert process.stopped
    assert server.log.closed
    assert not server.handlers


def test_runner_passes_opt_in_identity_preserves_order_and_discards_gold(tmp_path, monkeypatch):
    source = tmp_path / 'input.csv'
    source.write_text('id,prompt,response,gold\na,system,one,1\nb,system,two,0\nc,system,three,1\n')
    target = tmp_path / 'artifacts'
    class Server:
        def __init__(self, *args, **kwargs):
            self.port, self.api_key = 1234, 'offline'
            self.manifest = dict(model=adapter.MODEL)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(adapter, 'OwnedVllmServer', Server)
    from guardian_truth.v6fix import pipeline
    monkeypatch.setattr(pipeline, 'Layers', lambda *a, **k: object())
    seen = []
    def predict(row, client, layers, **options):
        seen.append((row, options))
        assert client.model == adapter.MODEL
        return dict(id=row['id'], binary=0)
    monkeypatch.setattr(adapter, 'predict_one', predict)
    predictions = []
    monkeypatch.setattr(adapter, 'write_predictions', lambda path, rows: predictions.extend(rows))
    adapter.main(['--python', 'unused', '--model-dir', str(tmp_path), '--asset-manifest', str(tmp_path / 'unused.json'),
                  '--input', str(source), '--output', str(target)])
    assert [r['id'] for r in predictions] == ['a', 'b']
    assert all(set(row) == {'id', 'prompt', 'response'} for row, _ in seen)
    assert all(options == dict(model=adapter.MODEL, provider='local-vllm') for _, options in seen)
    assert json.loads((target / 'DONE.json').read_text())['completion_http'] == 0


def cleanup_server(tmp_path):
    import io
    server = adapter.OwnedVllmServer('unused', tmp_path, tmp_path, 32, 1,
        deadline=time.monotonic() + 20, asset_manifest=tmp_path / 'unused.json')
    class ExitedLeader:
        pid = 987654321
        waited = False
        def poll(self):
            return 0
        def wait(self, timeout):
            self.waited = True
    server.process = ExitedLeader()
    server.pgid = server.process.pid
    server.log = io.StringIO()
    return server


@pytest.mark.parametrize('ignore_term', [False, True])
def test_dead_leader_remaining_child_is_cleaned_bounded(tmp_path, monkeypatch, ignore_term):
    server = cleanup_server(tmp_path)
    clock, alive, sent, closed = [0.0], {100}, [], []
    monkeypatch.setattr(adapter.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(adapter.time, 'monotonic', lambda: clock[0])
    monkeypatch.setattr(adapter.time, 'sleep', lambda value: clock.__setitem__(0, clock[0] + value))
    monkeypatch.setattr(adapter, 'owned_group_handles', lambda pgid, token: [(100, 42)] if alive else [])
    def send(descriptor, signum):
        sent.append((descriptor, signum))
        if not ignore_term or signum == 9:
            alive.clear()
    monkeypatch.setattr(adapter.signal, 'pidfd_send_signal', send, raising=False)
    monkeypatch.setattr(adapter.os, 'close', closed.append)
    server.__exit__()
    assert not alive
    assert sent[0] == (42, adapter.signal.SIGTERM)
    if ignore_term:
        assert (42, 9) in sent
    assert clock[0] <= 12.1
    assert len(closed) == len(sent)
    assert server.process.waited and server.log.closed and not server.handlers
    assert json.loads((tmp_path / 'cleanup.json').read_text())['status'] == 'CLEANED'
    # Idempotent, never re-signals a PGID after completed ownership cleanup.
    server.__exit__()
    assert len(closed) == len(sent)


def test_child_exits_between_scan_and_signal_is_harmless(tmp_path, monkeypatch):
    server = cleanup_server(tmp_path)
    remaining = [True]
    monkeypatch.setattr(adapter.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(adapter, 'owned_group_handles', lambda *args: [(100, 42)] if remaining[0] else [])
    def vanished(*args):
        remaining[0] = False
        raise ProcessLookupError('already exited')
    monkeypatch.setattr(adapter.signal, 'pidfd_send_signal', vanished, raising=False)
    closed = []
    monkeypatch.setattr(adapter.os, 'close', closed.append)
    server.__exit__()
    assert closed == [42]
    assert server.cleanup_done


def test_cleanup_error_still_restores_handlers_and_closes_log(tmp_path, monkeypatch):
    server = cleanup_server(tmp_path)
    restored = []
    server.handlers = {adapter.signal.SIGTERM: 'previous'}
    monkeypatch.setattr(adapter.signal, 'SIGKILL', 9, raising=False)
    monkeypatch.setattr(adapter.signal, 'signal', lambda *args: restored.append(args))
    def denied(*args):
        raise PermissionError('ownership unreadable')
    monkeypatch.setattr(adapter, 'owned_group_handles', denied)
    with pytest.raises(PermissionError):
        server.__exit__()
    assert restored == [(adapter.signal.SIGTERM, 'previous')]
    assert not server.handlers and server.log.closed
    assert json.loads((tmp_path / 'cleanup.json').read_text())['status'] == 'CLEANUP_FAILED'


@pytest.mark.parametrize('environment,session,zombie,expected', [
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0OTHER=1\0', 700, False, True),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=foreign\0', 700, False, False),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0', 701, False, False),
    (b'GUARDIAN_VLLM_OWNER_TOKEN=ours\0', 700, True, False),
])
def test_group_member_ownership_excludes_reused_pgid(tmp_path, monkeypatch, environment, session, zombie, expected):
    process = tmp_path / '701'
    process.mkdir()
    (process / 'stat').write_text(f'701 (engine (worker)) {"Z" if zombie else "S"} 1 700 {session} 0 0')
    (process / 'environ').write_bytes(environment)
    opened, closed = [], []
    monkeypatch.setattr(adapter.os, 'pidfd_open', lambda pid, flags: opened.append(pid) or 42, raising=False)
    monkeypatch.setattr(adapter.os, 'close', closed.append)
    handles = adapter.owned_group_handles(700, 'ours', proc_root=tmp_path)
    assert handles == ([(701, 42)] if expected else [])
    assert closed == ([] if expected or zombie or session != 700 else [42])
    if expected:
        adapter.os.close(handles[0][1])
        assert closed == [42]


def test_open_pidfd_is_closed_if_proc_disappears(tmp_path, monkeypatch):
    process = tmp_path / '701'
    process.mkdir()
    (process / 'stat').write_text('701 (engine) S 1 700 700 0')
    closed = []
    monkeypatch.setattr(adapter.os, 'pidfd_open', lambda *args: 42, raising=False)
    monkeypatch.setattr(adapter.os, 'close', closed.append)
    assert adapter.owned_group_handles(700, 'ours', proc_root=tmp_path) == []
    assert closed == [42]


def test_runner_checklist_flag_builds_once_and_passes_maps(tmp_path, monkeypatch):
    source = tmp_path / 'input.csv'
    source.write_text('id,prompt,response\na,system,one\nb,system,two\n')
    target = tmp_path / 'artifacts'
    class Server:
        def __init__(self, *args, **kwargs):
            self.port, self.api_key = 1234, 'offline'
            self.manifest = dict(model=adapter.MODEL)
        def __enter__(self):
            return self
        def __exit__(self, *args):
            pass
    monkeypatch.setattr(adapter, 'OwnedVllmServer', Server)
    from guardian_truth.v6fix import pipeline
    from guardian_truth.checklist import build as checklist_build
    monkeypatch.setattr(pipeline, 'Layers', lambda *a, **k: object())
    built = []
    def fake_build(client, model, rows, workers=1):
        built.append([r['id'] for r in rows])
        return {'k': dict(items=[])}
    monkeypatch.setattr(checklist_build, 'build', fake_build)
    seen = []
    monkeypatch.setattr(adapter, 'predict_one', lambda row, client, layers, **o: seen.append(o) or dict(id=row['id'], binary=0))
    monkeypatch.setattr(adapter, 'write_predictions', lambda path, rows: None)
    adapter.main(['--python', 'unused', '--model-dir', str(tmp_path), '--asset-manifest', str(tmp_path / 'unused.json'),
                  '--input', str(source), '--output', str(target), '--checklist'])
    assert built == [['a', 'b']]
    assert all(o == dict(model=adapter.MODEL, provider='local-vllm', checklists={'k': dict(items=[])}) for o in seen)
    assert json.loads((target / 'checklists.json').read_text())['policies'] == 1
    assert json.loads((target / 'protocol.json').read_text())['checklist'] is True
