"""Durable injected batch tests; no credentials or network access."""

from copy import deepcopy
from dataclasses import asdict
import json
from types import SimpleNamespace

import pytest

from guardian_truth.llm_client import ChatClientError
from guardian_truth.vnext.goal_v3_isolation_runner_v2 import CONFIG, StageRunnerV2, repair_v2
from guardian_truth.vnext.integrity import digest, prediction_seal, write_new
from test_vnext_goal_v3_isolation_frontend_v2 import proposal
from test_vnext_goal_v3_user_execution_v2 import source


class FakeClient:
    def __init__(self, outcomes):
        self.outcomes = list(outcomes)
        self.calls = []

    def complete(self, messages, **kwargs):
        self.calls.append((deepcopy(messages), deepcopy(kwargs)))
        outcome = self.outcomes.pop(0)
        if isinstance(outcome, Exception):
            raise outcome
        return outcome


def completion(text=None, usage=None):
    return SimpleNamespace(content=json.dumps(proposal()) if text is None else text,
        usage={"prompt_tokens": 100, "completion_tokens": 50, "total_tokens": 150} if usage is None else usage,
        model=CONFIG["model"])


def runner(tmp_path, outcomes, ids=None):
    freeze = {"architecture_commit": "a" * 40, "configuration": deepcopy(CONFIG),
        "stages": {"S1": ids or ["p1:a", "p2:a"]}}
    client = FakeClient(outcomes)
    return StageRunnerV2(tmp_path, freeze, client, sleeper=lambda _: None)


def test_exact_once_batch_seal_and_network_free_resume(tmp_path):
    run = runner(tmp_path, [completion(), completion()])
    inputs = {cid: source() for cid in run.freeze["stages"]["S1"]}
    boundary = run.run("S1", inputs)
    assert boundary["complete"] and len(run.client.calls) == 2
    predictions = json.loads(run.path("S1_predictions").read_text(encoding="utf-8"))
    seal = json.loads(run.path("S1_prediction_seal").read_text(encoding="utf-8"))
    assert seal == prediction_seal(predictions, boundary["attempted_case_ids"],
        architecture_commit="a" * 40, configuration_sha256=run.configuration_hash)
    assert run.run("S1", inputs) == boundary
    assert len(run.client.calls) == 2
    assert not run.path("S1_run_lock").exists()


def test_transport_retry_is_one_identical_payload_then_stops_missing_usage(tmp_path):
    run = runner(tmp_path, [ChatClientError("timeout", retryable=True), completion()])
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert len(run.client.calls) == 2 and run.client.calls[0] == run.client.calls[1]
    assert not boundary["complete"]
    assert boundary["budget"]["stop_reason"] == "USAGE_UNVERIFIABLE"
    assert boundary["not_run_case_ids"] == ["p2:a"]


def test_two_transport_failures_never_get_third_attempt(tmp_path):
    run = runner(tmp_path, [ChatClientError("server", retryable=True)] * 2)
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert len(run.client.calls) == 2 and not boundary["complete"]
    assert json.loads(run.path("S1_predictions").read_text(encoding="utf-8"))[0]["proposal"] is None


@pytest.mark.parametrize("text", ["not json", '{"status":"PROVED_ERROR"}',
    json.dumps(dict(proposal(), status="PROVED_ERROR"))])
def test_semantic_or_schema_disagreement_never_causes_retry(tmp_path, text):
    run = runner(tmp_path, [completion(text)], ["p1:a"])
    assert run.run("S1", {"p1:a": source()})["complete"]
    assert len(run.client.calls) == 1


def test_crash_after_request_admission_never_resends_uncaptured_request(tmp_path):
    run = runner(tmp_path, [RuntimeError("injected capture interruption")])
    with pytest.raises(RuntimeError):
        run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert not run.path("S1_run_lock").exists()
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert len(run.client.calls) == 1
    assert boundary["budget"]["stop_reason"] == "USAGE_UNVERIFIABLE"
    captured = json.loads(run.path("S1_predictions").read_text(encoding="utf-8"))[0]
    assert captured["telemetry"]["remote_outcome"] == "UNKNOWN_NO_AUTOMATIC_RETRY"


def test_live_or_stale_lock_is_not_removed_or_interpreted_as_failed_request(tmp_path):
    run = runner(tmp_path, [])
    write_new(run.path("S1_run_lock"), {"pid": 12345})
    with pytest.raises(FileExistsError):
        run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert run.path("S1_run_lock").exists() and not run.client.calls


def test_token_circuit_seals_prefix_and_does_not_launch_next_case(tmp_path):
    run = runner(tmp_path, [completion(usage={"total_tokens": 24000})])
    run.config["enforce_token_ceilings"] = True
    run.configuration_hash = digest(run.freeze)
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert boundary["budget"]["stop_reason"] == "TOKEN_CEILING_REACHED"
    assert boundary["attempted_case_ids"] == ["p1:a"] and len(run.client.calls) == 1


def test_user_relaxed_cost_policy_does_not_stop_at_old_ceiling(tmp_path):
    run = runner(tmp_path, [completion(usage={"total_tokens": 30000})] * 2)
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert boundary["complete"] and boundary["budget"]["reported_tokens"] == 60000
    assert boundary["budget"]["stop_reason"] is None and len(run.client.calls) == 2


def test_cached_result_lineage_or_changed_source_fails_closed(tmp_path):
    run = runner(tmp_path, [completion()], ["p1:a"])
    run.run("S1", {"p1:a": source()})
    changed = source(history_complete=False)
    with pytest.raises(ValueError, match="changed"):
        run.run("S1", {"p1:a": changed})
    assert len(run.client.calls) == 1


def test_only_value_preserving_exact_fences_are_repaired():
    text = json.dumps(proposal())
    assert repair_v2(text)[1:4] == (True, True, "NONE")
    assert repair_v2("```json\n" + text + "\n```")[1:4] == (False, True, "EXACT_JSON_FENCE")
    assert repair_v2("explanation " + text)[0] is None
    assert repair_v2(text + text)[0] is None
    assert repair_v2('{"status":"PROVED_ERROR","status":"PROVED_NO_ERROR"}')[0] is None
