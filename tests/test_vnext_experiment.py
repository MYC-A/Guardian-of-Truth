import pytest

from guardian_truth.vnext.experiment import PersistedSemanticBackend, ProviderPause, quota_pause_reason
from guardian_truth.vnext.integrity import digest
from guardian_truth.vnext.semantic import Proposal, SYSTEM
from guardian_truth.vnext.stage_goal import normalized_text, score_goal_case, stage_input
from guardian_truth.vnext.stage_results import confusion


class Delegate:
    def __init__(self, records):
        self.records, self.calls = records, 0

    def propose(self, task, payload, schema):
        from guardian_truth.vnext.integrity import canonical
        self.calls += 1
        messages = [{"role": "system", "content": SYSTEM}, {"role": "user",
            "content": "TASK: " + task + "\nDATA_JSON: " + canonical(payload).decode()
                + "\nOUTPUT_JSON_SCHEMA: " + canonical(schema).decode()}]
        self.records.append({"task": task, "transport_status": "SUCCESS", "schema_status": "VALID",
            "error_category": None, "input_sha256": digest(payload), "schema_sha256": digest(schema),
            "prompt_sha256": digest(messages), "latency_ms": 1, "usage": {}, "served_model": "fixture"})
        return Proposal('{"value":"ok"}', "SUCCESS", "VALID")


def test_request_frozen_before_call_and_replayed_without_network(tmp_path):
    records = []
    delegate = Delegate(records)
    first = PersistedSemanticBackend(delegate, tmp_path, "goal_v1_case_0", configuration_sha256="a" * 64, live_records=records)
    payload = {"field": ("one", "two")}
    original = first.propose("field", payload, {"type": "object"})
    second = PersistedSemanticBackend(delegate, tmp_path, "goal_v1_case_0", configuration_sha256="a" * 64, live_records=records)
    assert second.propose("field", payload, {"type": "object"}) == original
    assert delegate.calls == 1
    assert len(list(tmp_path.glob("*_result.json"))) == 1
    changed = PersistedSemanticBackend(delegate, tmp_path, "goal_v1_case_0", configuration_sha256="b" * 64, live_records=records)
    with pytest.raises(ValueError, match="changed"):
        changed.propose("field", payload, {"type": "object"})


def test_lost_response_capture_is_unknown_not_automatic_retry(tmp_path):
    records = []
    delegate = Delegate(records)
    backend = PersistedSemanticBackend(delegate, tmp_path, "case_0", configuration_sha256="a" * 64, live_records=records)
    # Let the delegate fail after the pre-request artifact is safely persisted.
    def lost(*args):
        raise RuntimeError("fixture process capture stopped")
    delegate.propose = lost
    with pytest.raises(RuntimeError):
        backend.propose("field", {}, {"type": "object"})
    resumed = PersistedSemanticBackend(Delegate(records), tmp_path, "case_0",
        configuration_sha256="a" * 64, live_records=records)
    proposal = resumed.propose("field", {}, {"type": "object"})
    assert proposal.transport_status == "ERROR"
    assert proposal.error_category == "abandoned_request_capture"
    assert resumed.delegate.calls == 0


def test_quota_policy_stops_before_admitting_another_request(tmp_path):
    records = [{"transport_status": "ERROR", "error_category": "rate_limit"}] * 2
    delegate = Delegate(records)
    backend = PersistedSemanticBackend(delegate, tmp_path, "case", configuration_sha256="a" * 64, live_records=records)
    with pytest.raises(ProviderPause, match="RATE_LIMIT"):
        backend.propose("field", {}, {})
    assert delegate.calls == 0
    assert not list(tmp_path.iterdir())


@pytest.mark.parametrize("records,expected", [
    ([{"transport_status": "ERROR", "error_category": "timeout"}] * 3, "THREE_CONSECUTIVE_TRANSPORT_ERRORS"),
    ([{"transport_status": "ERROR", "error_category": "timeout"}] * 2 +
        [{"transport_status": "SUCCESS", "error_category": None}] * 14, "LAST_16_TRANSPORT_BELOW_90_PERCENT"),
    ([{"transport_status": "SUCCESS", "error_category": None}] * 16, None)])
def test_quota_policy_has_predeclared_denominators(records, expected):
    assert quota_pause_reason(records) == expected


def test_goal_stage_adapter_does_not_take_gold_as_input():
    value = {"declared_goal": "Read report.", "declared_plan": ["read report"], "history": [],
        "allowed_scope": {"paths": ["/report"]}, "target_action": {"name": "send", "args": {"path": "/report"}},
        "gold": {"expected_action": "delete secret"}}
    source = stage_input(value)
    assert "delete secret" not in source.prompt
    assert "delete secret" not in source.response
    assert {row["name"] for row in source.tool_schemas} == {"read", "send"}
    assert source.target_action == value["target_action"]


def test_goal_field_scoring_reports_all_candidates_and_never_selects_one():
    case = {"case_id": "g0", "family": "fixture", "input": {"declared_goal": "Read report.", "allowed_scope": {"paths": ["/r"]}},
        "gold": {"expected_step": 0, "expected_action": "read report", "drift": "NO_DRIFT", "verdict": "PROVED_NO_ERROR"}}
    right = {"declared_goal": "Read the report.", "expected_step": 0, "expected_action": "Read the report",
        "allowed_scope": ["/r"], "drift_type": "NO_DRIFT"}
    wrong = {**right, "expected_step": 1}
    prediction = {"goal_plan": {"readings": [right, wrong], "failures": []}, "core_result": {"status": "UNRESOLVED"},
        "product_decision": {"binary_label": 0}}
    score = score_goal_case(case, prediction)
    assert score["fields"]["step"]["any_correct"]
    assert not score["fields"]["step"]["all_correct"]
    assert score["fields"]["step"]["candidate_correct"] == 1
    assert score["binary_label"] == 0
    assert not score["core_status_correct"]
    assert normalized_text("Read the report") == normalized_text("read report")


def test_transport_failure_is_excluded_from_conditional_semantics():
    case = {"case_id": "g0", "family": "fixture", "input": {"declared_goal": "Read report.", "allowed_scope": {}},
        "gold": {"expected_step": 0, "expected_action": "read report", "drift": "NO_DRIFT", "verdict": "PROVED_NO_ERROR"}}
    prediction = {"goal_plan": {"readings": [], "failures": ["TRANSPORT_ERROR"]},
        "core_result": {"status": "UNRESOLVED"}, "product_decision": {"binary_label": 0}}
    score = score_goal_case(case, prediction)
    assert not score["fields"]["step"]["semantic_case_eligible"]


def test_confusion_reports_zero_f1_and_missing_denominators_without_invention():
    metrics = confusion([(1, 0), (0, 0)])
    assert metrics["FN"] == 1
    assert metrics["TN"] == 1
    assert metrics["F1"] == 0
    assert metrics["precision"] is None


def test_stage_x0_uses_actual_protected_incumbent_without_network():
    from scripts.evaluate_vnext_goal import baseline_x0
    value = {"declared_goal": "Read report.", "declared_plan": ["read report"], "history": [],
        "allowed_scope": {"paths": ["/report"]}, "target_action": {"name": "read", "args": {"path": "/report"}}}
    result = baseline_x0(value)
    assert result["binary_label"] in {0, 1}
    assert result["status"] in {"unknown", "violation"}
    assert isinstance(result["unresolved"], list)
