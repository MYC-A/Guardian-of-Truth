"""Offline format/transport intervention regressions; no external calls."""

from copy import deepcopy
import json
import pytest

from guardian_truth.llm_client import ChatClientError
from guardian_truth.vnext.goal_v3_isolation_frontend_v2 import SCHEMA as OLD_SCHEMA, proposal_issues_v2
from guardian_truth.vnext.goal_v3_isolation_frontend_v3 import SCHEMA, SYSTEM_PROMPT, prompt_messages_v3, proposal_issues_v3
from guardian_truth.vnext.goal_v3_isolation_runner_v3 import CONFIG, StageRunnerV3, repair_v3
from guardian_truth.vnext.goal_v3_isolation_stage_gates_v3 import experiment_budget_v3
from guardian_truth.vnext.integrity import digest, write_new
from test_vnext_goal_v3_isolation_runner_v2 import FakeClient, completion
from test_vnext_goal_v3_isolation_frontend_v2 import proposal
from test_vnext_goal_v3_user_execution_v2 import source


def runner(tmp_path, outcomes, ids=("p1:a", "p2:a")):
    freeze = {"architecture_commit": "a" * 40, "configuration": deepcopy(CONFIG), "stages": {"S1": list(ids)}}
    return StageRunnerV3(tmp_path, freeze, FakeClient(outcomes), sleeper=lambda _: None)


def test_full_schema_unchanged_and_source_not_instruction():
    assert SCHEMA == OLD_SCHEMA
    schema_text = SYSTEM_PROMPT.split("JSON_SCHEMA:\n", 1)[1]
    assert json.loads(schema_text) == SCHEMA
    assert prompt_messages_v3(source())[0]["content"] == SYSTEM_PROMPT
    assert proposal_issues_v3(proposal()) == ()
    for key in ("policy", "gold", "reference"):
        with pytest.raises(ValueError):
            prompt_messages_v3(dict(source(), **{key: {}}))


@pytest.mark.parametrize("path,bad", [("authorization_closed", "TRUE"), ("history_complete", 1), ("scope_violation", False)])
def test_realistic_type_failures_have_paths_without_values(path, bad):
    value = proposal()
    value["worlds"][0][path] = bad
    issues = proposal_issues_v3(value)
    assert bool(issues) == bool(proposal_issues_v2(value))
    assert any(issue["path"] == "/worlds/0/" + path for issue in issues)
    assert all(set(issue) == {"code", "path", "expected_type", "actual_type"} for issue in issues)


def test_dynamic_key_and_bad_value_are_not_logged():
    value = proposal()
    value["effects"]["SENSITIVE_FAKE_KEY"] = "SENSITIVE_FAKE_VALUE"
    issues = json.dumps(proposal_issues_v3(value))
    assert "SENSITIVE" not in issues and "/effects/*" in issues


def test_exact_once_seal_and_offline_replay(tmp_path):
    run = runner(tmp_path, [completion(), completion()])
    inputs = {cid: source() for cid in run.freeze["stages"]["S1"]}
    boundary = run.run("S1", inputs)
    assert boundary["complete"] and len(run.client.calls) == 2
    assert run.run("S1", inputs) == boundary and len(run.client.calls) == 2
    assert all("JSON_SCHEMA" in call[0][0]["content"] for call in run.client.calls)
    assert not run.path("S1_run_lock").exists()


def test_transport_retry_then_next_case_even_with_unknown_failed_usage(tmp_path):
    run = runner(tmp_path, [ChatClientError("rate_limit", retryable=True), completion(), completion()])
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert boundary["complete"] and boundary["budget"]["reported_tokens"] == 300
    assert len(run.client.calls) == 3 and run.client.calls[0] == run.client.calls[1]


def test_two_failures_no_third_attempt_then_move_on(tmp_path):
    run = runner(tmp_path, [ChatClientError("server", retryable=True)] * 2 + [completion()])
    assert run.run("S1", {"p1:a": source(), "p2:a": source()})["complete"]
    assert len(run.client.calls) == 3
    row = json.loads(run.path("case_p1_a").read_text())
    assert row["physical_requests"] == 2 and row["proposal"] is None and row["certificate"] is None


def test_success_without_usage_still_stops(tmp_path):
    run = runner(tmp_path, [completion(usage={})])
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert boundary["budget"]["stop_reason"] == "USAGE_UNVERIFIABLE"
    assert boundary["not_run_case_ids"] == ["p2:a"]


def test_abandoned_request_no_resend(tmp_path):
    run = runner(tmp_path, [RuntimeError("injected crash")])
    with pytest.raises(RuntimeError):
        run.run("S1", {"p1:a": source(), "p2:a": source()})
    boundary = run.run("S1", {"p1:a": source(), "p2:a": source()})
    assert boundary["budget"]["stop_reason"] == "USAGE_UNVERIFIABLE" and len(run.client.calls) == 1


def test_schema_failure_is_captured_not_repaired_or_retried(tmp_path):
    value = proposal()
    value["worlds"][0]["history_complete"] = "TRUE"
    run = runner(tmp_path, [completion(json.dumps(value))], ("p1:a",))
    assert run.run("S1", {"p1:a": source()})["complete"] and len(run.client.calls) == 1
    row = json.loads(run.path("case_p1_a").read_text())
    assert row["proposal"] is None and row["telemetry"]["schema_issues"][0]["path"] == "/worlds/0/history_complete"
    assert "raw_completion" not in row["telemetry"]


def test_repair_is_value_preserving_only():
    text = json.dumps(proposal())
    assert repair_v3(text)[1:4] == (True, True, "NONE")
    assert repair_v3("```json\n" + text + "\n```")[1:4] == (False, True, "EXACT_JSON_FENCE")
    assert repair_v3("explanation " + text)[0] is None
    assert repair_v3("not json")[4][0]["code"] == "JSON_INVALID"


def test_no_ceiling_stop_and_no_false_accounting_claim():
    result = experiment_budget_v3([{"usage": {"total_tokens": 999999}, "transport_status": "SUCCESS"}],
        ceiling=24000, enforce_token_ceiling=False)
    assert result.admit_next_request and result.reported_tokens == 999999
