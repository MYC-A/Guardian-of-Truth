import json

import pytest

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.vnext.persisted_wire_v2 import PersistedWireClient
from guardian_truth.vnext.semantic_v2 import DiagnosticSemanticBackend


SCHEMA = {'type': 'object', 'required': ['value'], 'additionalProperties': False,
    'properties': {'value': {'type': 'string', 'const': 'allowed'}}}
MESSAGES = [{'role': 'system', 'content': 'fixed original baseline instructions'}, {'role': 'user', 'content': 'source data'}]


class Clock:
    def __init__(self):
        self.time, self.sleeps = 0, []

    def now(self):
        return self.time

    def sleep(self, duration):
        self.sleeps.append(duration)
        self.time += duration


class Client:
    def __init__(self, content='{"value":"allowed"}', failure=False):
        self.content, self.failure, self.calls = content, failure, []

    def complete(self, messages, **kwargs):
        self.calls.append(messages)
        if self.failure:
            raise ChatClientError('timeout')
        return Completion(self.content, {'total_tokens': 3}, 'controlled-model')


def setup(tmp_path, client):
    clock, live = Clock(), []
    backend = DiagnosticSemanticBackend(client, clock=clock.now, sleep=clock.sleep, checkpoint=live.append)
    return backend, live, clock, PersistedWireClient(backend, tmp_path, 'policy_v1_p1', 'config', live)


def test_exact_baseline_wire_is_preserved_and_replay_does_not_call_api(tmp_path):
    client = Client()
    backend, live, clock, persisted = setup(tmp_path, client)
    assert persisted.complete(MESSAGES, schema=SCHEMA).content == client.content
    replay = PersistedWireClient(backend, tmp_path, 'policy_v1_p1', 'config', live)
    assert replay.complete(MESSAGES, schema=SCHEMA).content == client.content
    assert client.calls == [MESSAGES]


def test_wire_and_native_requests_share_one_throttle_and_one_live_stream(tmp_path):
    backend, live, clock, persisted = setup(tmp_path, Client())
    backend.propose('native', {}, SCHEMA)
    persisted.complete(MESSAGES, schema=SCHEMA)
    backend.propose('next-native', {}, SCHEMA)
    assert clock.sleeps == [10, 10]
    assert len(live) == 3


def test_invalid_baseline_content_is_not_persisted_even_if_it_looks_like_a_secret(tmp_path):
    forbidden = 'SYNTHETIC_SECRET_MUST_NOT_BE_RETAINED'
    backend, live, clock, persisted = setup(tmp_path, Client(forbidden))
    assert persisted.complete(MESSAGES, schema=SCHEMA).content == ''
    assert forbidden not in ''.join(path.read_text(encoding='utf-8') for path in tmp_path.glob('*.json'))
    assert persisted.records[0]['schema_issues'][0]['code'] == 'JSON_INVALID'


def test_transport_failure_is_durable_and_not_hidden_retried(tmp_path):
    client = Client(failure=True)
    backend, live, clock, persisted = setup(tmp_path, client)
    with pytest.raises(ChatClientError):
        persisted.complete(MESSAGES, schema=SCHEMA)
    replay = PersistedWireClient(backend, tmp_path, 'policy_v1_p1', 'config', live)
    with pytest.raises(ChatClientError):
        replay.complete(MESSAGES, schema=SCHEMA)
    assert len(client.calls) == 1


def test_replay_in_a_fresh_backend_still_throttles_next_live_request(tmp_path):
    backend, live, clock, persisted = setup(tmp_path, Client())
    persisted.complete(MESSAGES, schema=SCHEMA)
    resumed, resumed_live, resumed_clock, replay = setup(tmp_path, Client())
    replay.complete(MESSAGES, schema=SCHEMA)
    resumed.propose('new-native', {}, SCHEMA)
    assert resumed_clock.sleeps == [10]
    assert len(resumed_live) == 1


def test_unfinished_wire_request_is_not_resent(tmp_path):
    from guardian_truth.vnext.integrity import digest, write_new
    backend, live, clock, persisted = setup(tmp_path, Client())
    request = {'configuration_sha256': 'config', 'ordinal': 0, 'messages': MESSAGES,
        'schema': SCHEMA, 'reasoning_effort': None,
        'prompt_sha256': digest(MESSAGES), 'schema_sha256': digest(SCHEMA)}
    write_new(tmp_path / 'policy_v1_p1_request_000.json', request)
    with pytest.raises(ChatClientError) as error:
        persisted.complete(MESSAGES, schema=SCHEMA)
    assert error.value.category == 'abandoned_request_capture'
    assert not backend.client.calls
    assert persisted.records[0]['remote_outcome'] == 'UNKNOWN_NO_AUTOMATIC_RETRY'
