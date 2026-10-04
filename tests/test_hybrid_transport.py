"""Focused transport regression probes; all network/credentials are mocked."""
import hashlib
import json
from pathlib import Path
from unittest.mock import Mock
import urllib.error

import pytest

from experiments.hybrid_mechanisms import transport as t
from guardian_truth.source_search.store import digest


def protocol(tokens=280000, http=36):
    p = {'providers': {k: {'model': 'test-' + k, 'context_limit': 262144, 'endpoint': endpoint}
                       for k, endpoint in t.ENDPOINTS.items()}, 'limits': {'http': http, 'tokens': tokens}}
    p['protocol_sha256'] = digest(p)
    return p


def body(provider='mistral', content='some original evidence'):
    return {'model': 'test-' + provider, 'max_tokens': 100, 'messages': [{'role': 'user', 'content': content}]}


def provider_response(total=30, completion=10, model='test-mistral'):
    return {'model': model, 'choices': [{'finish_reason': 'stop', 'message': {'content': '{"decision":"UNKNOWN"}'}}],
            'usage': {'total_tokens': total, 'prompt_tokens': total - completion, 'completion_tokens': completion}}


@pytest.fixture
def network(monkeypatch):
    response = Mock()
    response.__enter__ = Mock(return_value=response)
    response.__exit__ = Mock(return_value=False)
    response.read.return_value = json.dumps(provider_response()).encode()
    opener = Mock()
    opener.open.return_value = response
    monkeypatch.setattr(t.urllib.request, 'build_opener', Mock(return_value=opener))
    monkeypatch.setattr(t, 'credentials', Mock(return_value='fake-secret'))
    return opener, response


def test_reservation_durable_before_network_and_cache_offline(tmp_path, network):
    opener, response = network
    p, b = protocol(), body()
    def opening(request, timeout):
        ledger = t.read(tmp_path / 'ledger.json')
        assert len(ledger) == 1
        item = next(iter(ledger.values()))
        assert item['status'] == 'RESERVED'
        assert item['charged_tokens'] == t.bound(b)
        assert request.data == t.serialized(b)
        assert 'fake-secret' not in (tmp_path / 'ledger.json').read_text()
        return response
    opener.open.side_effect = opening
    c = t.Client(tmp_path, p, live=True)
    record, failure = c.ask('I1', 'mistral', b)
    assert failure is None and record['known_tokens'] == record['charged_tokens'] == 30
    assert c.summary()['attempts'] == c.new_http == 1
    before = (tmp_path / 'ledger.json').read_bytes()
    t.credentials.side_effect = AssertionError('OFFLINE_CREDENTIALS')
    opener.open.side_effect = AssertionError('OFFLINE_HTTP')
    saved, failure = t.Client(tmp_path, p).ask('same-request-replay', 'mistral', b)
    assert saved == record and failure is None
    assert (tmp_path / 'ledger.json').read_bytes() == before


def test_global_budget_shared_across_providers(tmp_path, network):
    reserve = t.bound(body('ollama'))
    c = t.Client(tmp_path, protocol(tokens=reserve + 29), live=True)
    assert c.ask('a', 'mistral', body())[0]['charged_tokens'] == 30
    assert c.ask('b', 'ollama', body('ollama')) == (None, 'BUDGET_STOP')
    assert network[0].open.call_count == 1
    assert c.summary()['attempts'] == 1


def test_global_http_limit_across_providers(tmp_path, network):
    c = t.Client(tmp_path, protocol(http=1), live=True)
    c.ask('a', 'mistral', body())
    assert c.ask('b', 'ollama', body('ollama')) == (None, 'BUDGET_STOP')


def test_provider_qualification_prevents_cache_collision(tmp_path, network):
    c = t.Client(tmp_path, protocol(), live=True)
    c.ask('a', 'mistral', body())
    network[1].read.return_value = json.dumps(provider_response(model='test-ollama')).encode()
    c.ask('b', 'ollama', body('ollama'))
    assert len(list((tmp_path / 'raw').glob('*.json'))) == 2
    assert c.summary()['attempts'] == 2


@pytest.mark.parametrize('code', [429, 402])
def test_no_http_error_retry_after_restart(tmp_path, network, code):
    network[0].open.side_effect = urllib.error.HTTPError('https://safe.invalid', code, 'test', {}, None)
    p, b = protocol(), body()
    r, failure = t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    assert r['http_status'] == code and r['charged_tokens'] == t.bound(b)
    restarted = t.Client(tmp_path, p, live=True)
    assert restarted.ask('a', 'mistral', b)[0] == r
    assert restarted.ask('other', 'mistral', body(content='different')) == (None, 'PROVIDER_BREAKER_NO_RETRY')
    assert network[0].open.call_count == 1


def test_unknown_usage_preserves_reservation_and_stops_provider(tmp_path, network):
    data = provider_response(); data.pop('usage')
    network[1].read.return_value = json.dumps(data).encode()
    c = t.Client(tmp_path, protocol(), live=True)
    r, _ = c.ask('a', 'mistral', body())
    assert r['unknown_usage'] and r['known_tokens'] == 0 and r['charged_tokens'] == t.bound(body())
    assert t.Client(tmp_path, protocol(), live=True).ask('b', 'mistral', body(content='new')) == (None, 'PROVIDER_BREAKER_NO_RETRY')


def test_pending_reservation_survives_interrupted_network(tmp_path, network):
    network[0].open.side_effect = KeyboardInterrupt
    p, b = protocol(), body()
    with pytest.raises(KeyboardInterrupt):
        t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    c = t.Client(tmp_path, p, live=True)
    assert c.ask('a', 'mistral', b) == (None, 'PRIOR_RESERVED_NO_RETRY')
    assert c.summary()['charged_tokens'] == t.bound(b)
    assert c.ask('b', 'mistral', body(content='new')) == (None, 'PROVIDER_BREAKER_NO_RETRY')
    assert network[0].open.call_count == 1


def test_uncommitted_raw_does_not_refund_reserved_call(tmp_path, network, monkeypatch):
    original_save = t.save
    def crash_after_raw(path, value):
        original_save(path, value)
        if Path(path).parent.name == 'raw':
            raise KeyboardInterrupt
    monkeypatch.setattr(t, 'save', crash_after_raw)
    p, b = protocol(), body()
    with pytest.raises(KeyboardInterrupt):
        t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    c = t.Client(tmp_path, p, live=True)
    assert c.ask('a', 'mistral', b) == (None, 'PRIOR_RESERVED_NO_RETRY')
    assert c.summary()['charged_tokens'] == t.bound(b)


@pytest.mark.parametrize('usage', [None, {}, {'total_tokens': True, 'prompt_tokens': 0, 'completion_tokens': 1},
                                  {'total_tokens': 5, 'prompt_tokens': 1, 'completion_tokens': 3},
                                  {'total_tokens': 110, 'prompt_tokens': 1, 'completion_tokens': 109}])
def test_unverified_usage_never_refunds(usage):
    assert t.valid_usage({'usage': usage}, output_cap=100) is None


def test_context_stop_without_silent_trimming(tmp_path, network):
    p = protocol(); p['providers']['mistral']['context_limit'] = 10
    p['protocol_sha256'] = digest({k: v for k, v in p.items() if k != 'protocol_sha256'})
    assert t.Client(tmp_path, p, live=True).ask('a', 'mistral', body()) == (None, 'CONTEXT_STOP')
    network[0].open.assert_not_called()
    t.credentials.assert_not_called()


def test_offline_missing_cache_never_accesses_credentials(tmp_path, network):
    assert t.Client(tmp_path, protocol()).ask('a', 'mistral', body()) == (None, 'CACHE_MISS_OFFLINE')
    network[0].open.assert_not_called(); t.credentials.assert_not_called()


def test_raw_and_request_integrity_checked(tmp_path, network):
    p, b = protocol(), body()
    t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    raw = next((tmp_path / 'raw').glob('*.json'))
    raw.write_text('{}')
    with pytest.raises(ValueError, match='RAW_CHANGED'):
        t.Client(tmp_path, p).ask('a', 'mistral', b)


def test_request_mutation_detected(tmp_path, network):
    p, b = protocol(), body()
    t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    request = next((tmp_path / 'requests').glob('*.json'))
    data = t.read(request); data['body']['messages'][0]['content'] = 'changed'
    t.save(request, data)
    with pytest.raises(ValueError, match='REQUEST_CHANGED'):
        t.Client(tmp_path, p).ask('a', 'mistral', b)


def test_unplanned_model_and_provider_blocked(tmp_path, network):
    c = t.Client(tmp_path, protocol(), live=True)
    with pytest.raises(ValueError, match='UNPLANNED_PROVIDER'):
        c.ask('a', 'third-party', body())
    with pytest.raises(ValueError, match='UNPLANNED_MODEL'):
        c.ask('a', 'mistral', body('ollama'))
    network[0].open.assert_not_called()


def test_protocol_and_ledger_corruption_fail_closed(tmp_path):
    p = protocol(); p['limits']['http'] = 35
    with pytest.raises(ValueError, match='PROTOCOL_CHANGED'):
        t.Client(tmp_path, p)
    t.save(tmp_path / 'ledger.json', {'bad-key': {}})
    with pytest.raises(ValueError, match='LEDGER_INVALID'):
        t.Client(tmp_path, protocol())


def test_completed_ledger_cannot_claim_unverified_refund(tmp_path, network):
    p = protocol()
    t.Client(tmp_path, p, live=True).ask('a', 'mistral', body())
    ledger = t.read(tmp_path / 'ledger.json')
    next(iter(ledger.values()))['charged_tokens'] = 31
    t.save(tmp_path / 'ledger.json', ledger)
    with pytest.raises(ValueError, match='LEDGER_VERIFIED_CHARGE_INVALID'):
        t.Client(tmp_path, p)


def test_conservative_bounds_include_full_utf8_schema_and_output():
    b = body(content='данные'); b['response_format'] = {'type': 'json_schema', 'schema': {'some': 'large-schema'}}
    assert t.bound(b) == len(t.serialized(b)) + 100 + 2048
    assert t.bound(b, lambda x: 500) == 500 + 100 + 2048


def test_field_order_is_wire_identity_not_sorted_json_identity(tmp_path, network):
    first, last = body(), body()
    first['schema'] = {'properties': {'decision': {}, 'reason': {}}}
    last['schema'] = {'properties': {'reason': {}, 'decision': {}}}
    assert digest(first) == digest(last)
    c = t.Client(tmp_path, protocol(), live=True)
    a, _ = c.ask('decision-first', 'mistral', first)
    b, _ = c.ask('decision-last', 'mistral', last)
    assert a['request_sha256'] != b['request_sha256']
    assert a['body_sha256'] != b['body_sha256']
    assert network[0].open.call_count == 2


def test_reordered_saved_body_detected_even_when_dict_equal(tmp_path, network):
    p, b = protocol(), body()
    b['schema'] = {'properties': {'decision': {}, 'reason': {}}}
    t.Client(tmp_path, p, live=True).ask('a', 'mistral', b)
    path = next((tmp_path / 'requests').glob('*.json'))
    saved = t.read(path)
    saved['body']['schema']['properties'] = {'reason': {}, 'decision': {}}
    t.save(path, saved)
    with pytest.raises(ValueError, match='REQUEST_CHANGED'):
        t.Client(tmp_path, p).ask('a', 'mistral', b)


def test_metadata_preflight_is_get_and_zero_inference(network):
    network[1].read.return_value = b'{"data":[{"id":"test-mistral","max_context_length":262144}]}'
    result = t.preflight('mistral', 'test-mistral')
    request = network[0].open.call_args.args[0]
    assert request.get_method() == 'GET' and request.full_url.endswith('/models')
    assert result['status'] == 'READY' and result['inference_http'] == 0


def test_invalid_provider_json_charged_and_preserved(tmp_path, network):
    network[1].read.return_value = b'{"usage":1,"usage":2}'
    r, _ = t.Client(tmp_path, protocol(), live=True).ask('a', 'mistral', body())
    assert r['status'] == 'PROVIDER_JSON_INVALID' and r['provider_response_text'] == '{"usage":1,"usage":2}'
    assert r['unknown_usage'] and r['charged_tokens'] == t.bound(body())
