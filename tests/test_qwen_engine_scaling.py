"""Fixed work, ownership, paired wires and fail-fast reporting without a GPU."""
import copy
import json
import os
import threading
import time

import pytest

from scripts import qwen_engine_scaling as bench


def receipt(wire):
    return dict(model=bench.MODEL, response_model=bench.MODEL, request_sha256=bench.sha(wire),
                content='synthetic output', finish_reason='length', cached=False,
                input_tokens=1500, usage=dict(prompt_tokens=1500, completion_tokens=wire['max_tokens']),
                timings=dict(prompt_n=1500, prompt_ms=100, predicted_n=wire['max_tokens'], predicted_ms=200),
                transport=dict(status=200))


@pytest.fixture
def offline(monkeypatch):
    servers, clients, requests, peak = [], [], [], {}
    monkeypatch.setattr(bench, 'digest', lambda path: bench.MODEL_SHA256 if str(path).endswith('.gguf') else
                        bench.NATIVE_SHA256 if str(path).endswith('llama-server') else 'code-sha')
    monkeypatch.setattr(bench, 'native_metrics', lambda _: 'llamacpp:tokens_predicted_total 256\n')

    class Server:
        def __init__(self, root, work, slots, context):
            self.work, self.port, self.api_key = work, len(servers) + 10000, 'local-test-only'
            self.props = dict(total_slots=slots, context=context, model_alias=bench.MODEL)
            assert slots == 8 and context == 32768
            servers.append(self)
            self.closed = False

        def __enter__(self):
            assert all(os.environ[k] == '8' for k in bench.CPU_ENV)
            return self

        def __exit__(self, *_):
            self.closed = True

    class Client:
        def __init__(self, port, context, timeout, api_key):
            assert timeout == 90 and context == 32768
            self.calls, self.preflight_http, self.completion_http, self.cache_hits = [], 0, 0, 0
            self.port, self.active, self.lock = port, 0, threading.Lock()
            clients.append(self)

        def call(self, wire, attempt, tag):
            assert attempt == 0
            with self.lock:
                self.active += 1
                peak[self.port] = max(peak.get(self.port, 0), self.active)
                self.preflight_http += 1
                self.completion_http += 1
            time.sleep(0.002)
            result = receipt(wire)
            with self.lock:
                self.active -= 1
                self.calls.append(result)
                requests.append((self.port, tag, copy.deepcopy(wire)))
            return result

    monkeypatch.setattr(bench, 'ModelServer', Server)
    monkeypatch.setattr(bench, 'LocalClient', Client)
    return dict(servers=servers, clients=clients, requests=requests, peak=peak, Client=Client)


def test_requests_are_fixed_shape_distinct_exact_wires_without_labels():
    wires = [bench.request(i) for i in range(8)]
    assert len({bench.sha(w) for w in wires}) == 8
    assert len({len(w['messages'][1]['content']) for w in wires}) == 1
    for wire in wires:
        assert wire['max_tokens'] == 256 and wire['temperature'] == 0 and wire['ignore_eos'] is True
        assert wire['cache_prompt'] is False and wire['chat_template_kwargs'] == {'enable_thinking': False}
        assert not ({'id', 'label', 'gold'} & wire.keys())


def test_complete_run_has_equal_work_fresh_servers_and_separate_warmup(tmp_path, offline):
    out = tmp_path / 'run'
    result = bench.run(tmp_path / 'root', out)
    assert result['status'] == 'COMPLETE' and len(offline['servers']) == len(offline['clients']) == 2
    assert all(s.closed for s in offline['servers'])
    assert len(offline['requests']) == 18  # 2 * (warmup + 8 measured), not 1 versus 8 total work
    by_port = {s.port: [r for p, tag, r in offline['requests'] if p == s.port and tag == 'scaling']
               for s in offline['servers']}
    assert [[bench.sha(r) for r in wires] for wires in by_port.values()][0] == [bench.sha(bench.request(i)) for i in range(8)]
    assert set(map(bench.sha, list(by_port.values())[0])) == set(map(bench.sha, list(by_port.values())[1]))
    for arm in result['arms']:
        assert arm['generated_tokens'] == 2048 and arm['completed_requests'] == 8
        assert arm['warmup_usage']['completion_tokens'] == 16
        assert arm['native_prompt_seconds_sum'] == .8 and arm['native_decode_seconds_sum'] == 1.6
        assert arm['completion_http'] == arm['preflight_http'] == 9 and arm['client_cache_hits'] == 0
        phase = out / f"rep1_concurrency{arm['concurrency']}"
        records = [json.loads(line) for line in (phase / 'receipts.jsonl').read_text().splitlines()]
        assert sorted(r['ordinal'] for r in records) == list(range(8))
        assert all(r['request'] == bench.request(r['ordinal']) and not r['errors'] for r in records)
        assert (phase / 'metrics_before_warmup.txt').is_file() and (phase / 'metrics_after_batch.txt').is_file()
    comparison = result['comparisons'][0]
    assert comparison['conclusion'] == 'OBSERVED_SYNTHETIC_SCALING_ONLY'
    assert comparison['observed_fixed_work_wall_speedup'] == pytest.approx(comparison['observed_aggregate_tps_ratio_8_vs_1'])
    assert 'ENGINE_DOES_NOT_BATCH' not in json.dumps(result)
    protocol = json.loads((out / 'protocol.json').read_text())
    assert protocol['maximum_completion_attempts'] == 18 and protocol['retries'] == 0
    assert 'External operator' in protocol['whole_run_timeout']


def test_reverse_second_repetition_is_bounded_and_owns_four_servers(tmp_path, offline):
    result = bench.run(tmp_path, tmp_path / 'repeat', repetitions=2)
    assert [a['concurrency'] for a in result['arms']] == [1, 8, 8, 1]
    assert len(offline['servers']) == 4 and len(offline['requests']) == 36
    assert len(result['comparisons']) == 2


@pytest.mark.parametrize('repetitions', [0, 3, True, '1'])
def test_invalid_repetitions_cannot_start_server(tmp_path, offline, repetitions):
    with pytest.raises(ValueError, match='REPETITIONS'):
        bench.run(tmp_path, tmp_path / 'bad', repetitions)
    assert not offline['servers']


def test_existing_output_refused_without_overwriting(tmp_path, offline):
    existing = tmp_path / 'existing'
    existing.mkdir()
    (existing / 'keep').write_text('original')
    with pytest.raises(FileExistsError):
        bench.run(tmp_path, existing)
    assert (existing / 'keep').read_text() == 'original' and not offline['servers']


def test_wrong_sha_stops_before_gpu_start_and_writes_failure(tmp_path, offline, monkeypatch):
    monkeypatch.setattr(bench, 'digest', lambda _: 'wrong-sha')
    out = tmp_path / 'wrong'
    with pytest.raises(ValueError, match='SHA_MISMATCH'):
        bench.run(tmp_path, out)
    assert not offline['servers'] and json.loads((out / 'STOPPED.json').read_text())['status'] == 'STOPPED'


@pytest.mark.parametrize('mutation,expected', [
    (lambda r: r.update(transport={'status': 'EXC'}), 'TRANSPORT_FAILURE'),
    (lambda r: r.update(finish_reason='stop'), 'UNEXPECTED_FINISH'),
    (lambda r: r['usage'].update(completion_tokens=255), 'GENERATED_TOKEN_COUNT_MISMATCH'),
    (lambda r: r['timings'].update(predicted_n=255), 'NATIVE_GENERATED_COUNT_MISMATCH'),
    (lambda r: r['timings'].update(predicted_ms=float('nan')), 'INVALID_NATIVE_TIMINGS'),
    (lambda r: r.update(input_tokens=32768), 'CONTEXT_BUDGET_EXCEEDED'),
    (lambda r: r.update(cached=True), 'UNEXPECTED_CLIENT_CACHE_HIT'),
    (lambda r: r.update(response_model='other-model'), 'RESPONSE_MODEL_MISMATCH'),
    (lambda r: r.update(request_sha256='other-request'), 'REQUEST_IDENTITY_MISMATCH'),
])
def test_fixed_work_checks_fail_closed(mutation, expected):
    wire = bench.request(0)
    value = receipt(wire)
    mutation(value)
    assert expected in bench.receipt_errors(value, wire)


def test_serial_failure_does_not_dispatch_rest_or_later_arm(tmp_path, offline, monkeypatch):
    original = offline['Client'].call

    def fail_first(self, wire, attempt, tag):
        result = original(self, wire, attempt, tag)
        if tag == 'scaling':
            result['transport'] = {'status': 'EXC'}
        return result

    monkeypatch.setattr(offline['Client'], 'call', fail_first)
    out = tmp_path / 'failed'
    with pytest.raises(RuntimeError, match='FIXED_WORK_ARM_FAILED'):
        bench.run(tmp_path, out)
    assert len(offline['servers']) == 1 and offline['servers'][0].closed
    assert len(offline['requests']) == 2  # One warmup and one failing measured request.
    assert json.loads((out / 'rep1_concurrency1/summary.json').read_text())['aggregate_output_tokens_per_second'] is None
    assert (out / 'STOPPED.json').is_file() and not (out / 'report.json').exists()


def test_warmup_failure_is_preserved_without_dispatching_batch(tmp_path, offline, monkeypatch):
    original = offline['Client'].call

    def truncated_warmup(self, wire, attempt, tag):
        result = original(self, wire, attempt, tag)
        result['usage']['completion_tokens'] = 1
        return result

    monkeypatch.setattr(offline['Client'], 'call', truncated_warmup)
    out = tmp_path / 'warmup_failure'
    with pytest.raises(RuntimeError, match='WARMUP_FAILED'):
        bench.run(tmp_path, out)
    assert len(offline['requests']) == len(offline['servers']) == 1
    assert (out / 'rep1_concurrency1/warmup.json').is_file() and (out / 'STOPPED.json').is_file()


def test_generated_tokens_from_incomplete_batch_do_not_become_scaling_result():
    wire = bench.request(0)
    records = [{'ordinal': 0, 'receipt': receipt(wire), 'errors': []}]
    summary = bench.summarize(records, 1)
    assert summary['status'] == 'FAILED' and summary['generated_tokens'] == 256
    assert summary['aggregate_output_tokens_per_second'] is None


def test_malformed_usage_is_an_explicit_failed_receipt_not_a_summation_crash():
    wire = bench.request(0)
    value = receipt(wire)
    value['usage'] = {'completion_tokens': '256', 'prompt_tokens': None}
    errors = bench.receipt_errors(value, wire)
    summary = bench.summarize([dict(ordinal=0, receipt=value, errors=errors)], 1)
    assert summary['invalid_usage_receipts'] == 1 and summary['generated_tokens'] == 0
    assert summary['status'] == 'FAILED' and summary['aggregate_output_tokens_per_second'] is None
    assert bench.receipt_errors([], wire) == ['INVALID_RECEIPT_SHAPE']


def test_after_batch_metrics_failure_keeps_all_completion_receipts(tmp_path, offline, monkeypatch):
    n = 0

    def metrics(_):
        nonlocal n
        n += 1
        if n == 3:
            raise RuntimeError('TELEMETRY_FAILURE')
        return 'metric 1\n'

    monkeypatch.setattr(bench, 'native_metrics', metrics)
    out = tmp_path / 'metrics_failed'
    with pytest.raises(RuntimeError, match='TELEMETRY_FAILURE'):
        bench.run(tmp_path, out)
    phase = out / 'rep1_concurrency1'
    assert len(json.loads((phase / 'calls.json').read_text())) == 9
    assert len((phase / 'receipts.jsonl').read_text().splitlines()) == 8
    assert len(offline['servers']) == 1 and offline['servers'][0].closed
    assert (out / 'STOPPED.json').is_file()
