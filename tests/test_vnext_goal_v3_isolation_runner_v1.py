"""Offline invariants for the durable, one-inference-per-case Goal runner."""

import json

import pytest

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.vnext.integrity import digest, write_new
from scripts import evaluate_goal_v3_isolation_v1 as runner


SOURCE = {"user_messages": [{"message_id": "user:0", "text": "Read order A"}],
    "history_prefix": [], "target_action": {}, "tool_catalog": {}}


class FakeClient:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    def complete(self, messages, *, schema, reasoning_effort):
        self.calls.append({"messages": messages, "schema": schema, "reasoning_effort": reasoning_effort})
        value = self.responses.pop(0)
        if isinstance(value, Exception):
            raise value
        return value


def test_schema_invalid_completion_does_not_retry(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "OUT", tmp_path)
    client = FakeClient([Completion("{}", usage={"total_tokens": 7}, model="fixture")])
    result = runner.run_case("fixture:a", SOURCE, client, "frozen")
    assert len(client.calls) == result["physical_requests"] == 1
    assert result["telemetry"]["transport_status"] == "SUCCESS"
    assert result["telemetry"]["postrepair_schema_valid"] is False
    assert result["grounding"] is None


def test_transport_retries_once_with_identical_payload(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "OUT", tmp_path)
    monkeypatch.setattr(runner.time, "sleep", lambda _: None)
    client = FakeClient([ChatClientError("timeout", retryable=True), Completion("{}")])
    result = runner.run_case("fixture:b", SOURCE, client, "frozen")
    assert result["physical_requests"] == len(client.calls) == 2
    assert client.calls[0] == client.calls[1]
    first = json.loads(runner._request_paths("fixture:b", 0)[0].read_text(encoding="utf-8"))
    second = json.loads(runner._request_paths("fixture:b", 1)[0].read_text(encoding="utf-8"))
    assert first["messages"] == second["messages"]
    assert first["source_sha256"] == second["source_sha256"] == digest(SOURCE)


def test_admitted_request_without_result_is_not_sent_again(tmp_path, monkeypatch):
    monkeypatch.setattr(runner, "OUT", tmp_path)
    messages = runner.prompt_messages(SOURCE)
    request = runner._request_artifact("fixture:c", 0, SOURCE, messages, "frozen")
    write_new(runner._request_paths("fixture:c", 0)[0], request)
    client = FakeClient([])
    result = runner.run_case("fixture:c", SOURCE, client, "frozen")
    assert client.calls == []
    assert result["telemetry"]["remote_outcome"] == "UNKNOWN_NO_AUTOMATIC_RETRY"
    assert result["physical_requests"] == 1


def test_immutable_stage_artifacts_resume_without_overwrite(tmp_path):
    target = tmp_path / "sealed.json"
    runner.write_immutable(target, {"a": 1})
    runner.write_immutable(target, {"a": 1})
    with pytest.raises(ValueError, match="immutable"):
        runner.write_immutable(target, {"a": 2})
