"""Source-only compilation and typed trace mechanisms, no model requests."""

from copy import deepcopy

import pytest

from guardian_truth.vnext.goal_v3_semantics_v2 import GoalAlignmentV2, GoalLocalStatusV2
from guardian_truth.vnext.goal_v3_user_execution_v2 import evaluate_user_source_v2
from guardian_truth.vnext.types import Truth


BASE = "Read status of ORDER-82. Use status_api or tracking_api for ORDER-82. Only the explicitly allowed calls for ORDER-82 are permitted."


def source(text=BASE, tool="status_api", history=None, **flags):
    data = {"user_messages": [{"role": "user", "message_id": "user:0", "text": text}],
        "tool_catalog": {name: {"provider": "test", "version": "3"} for name in
            ("status_api", "tracking_api", "cache_api", "coverage_api", "identity_api", "confirm_api", "delete_api")},
        "target_action": {"actor": "assistant", "kind": "tool_call", "tool": tool,
            "entity": "ORDER-82", "provider": "test", "version": "3"},
        "history_prefix": history or [], "history_complete": True, "session_complete": False}
    data["tool_catalog"]["confirm_api"]["effect_contract"] = {"confirmed_when": {
        "result_field": "delivered", "equals": True, "committed": True, "call_status": "SUCCESS"}}
    for name in ("status_api", "tracking_api"):
        data["tool_catalog"][name]["goal_fields"] = ["status"]
    data.update(flags)
    return data


def call(tool="cache_api", **changes):
    event = {"event_id": "e:0", "actor": "assistant", "kind": "call", "tool": tool,
        "entity": "ORDER-82", "provider": "test", "version": "3", "before_target": True}
    event.update(changes)
    return event


def result(tool="coverage_api", value=True, field="active", **changes):
    event = call(tool, actor="tool", kind="result", paired_requestor="assistant",
        result={field: value}, fresh=True, complete=True, committed=True, call_status="SUCCESS")
    event.update(changes)
    return event


def decision(data):
    evaluated = evaluate_user_source_v2(data)
    assert evaluated is not None
    return evaluated[1]


def test_alternative_tools_and_auxiliary_permissions_without_implicit_order():
    for tool in ("status_api", "tracking_api"):
        assert decision(source(tool=tool)).status is GoalLocalStatusV2.NO_ERROR
    data = source(BASE + " You may call cache_api for ORDER-82.", tool="cache_api")
    assert decision(data).alignment is GoalAlignmentV2.AUXILIARY
    assert decision(data).status is GoalLocalStatusV2.NO_ERROR


def test_explicit_scope_wrong_entity_and_forbidden_attempt():
    assert decision(source(tool="delete_api")).status is GoalLocalStatusV2.ERROR
    data = source()
    data["target_action"]["entity"] = "ORDER-83"
    assert decision(data).status is GoalLocalStatusV2.ERROR
    data = source("Read status of ORDER-82. Never call delete_api for ORDER-82.", tool="delete_api",
        history_complete=False, unrelated_state={"cache": None})
    assert decision(data).status is GoalLocalStatusV2.ERROR
    assert not decision(data).certified


def test_explicit_prerequisite_is_separate_from_alignment_and_requires_actor():
    text = BASE + " Before calling status_api for ORDER-82, call cache_api for ORDER-82."
    assert decision(source(text, history=[call()])).status is GoalLocalStatusV2.NO_ERROR
    bad = decision(source(text, history=[call(actor="user")]))
    assert bad.status is GoalLocalStatusV2.ERROR
    assert bad.alignment is GoalAlignmentV2.DIRECT
    assert decision(source(text, history_complete=False)).status is GoalLocalStatusV2.UNRESOLVED


@pytest.mark.parametrize("guard_value,status", [(True, GoalLocalStatusV2.ERROR),
    (False, GoalLocalStatusV2.NO_ERROR), (None, GoalLocalStatusV2.UNRESOLVED)])
def test_exogenous_guard_true_false_unknown(guard_value, status):
    text = BASE + " If the fresh result of coverage_api for ORDER-82 has active=true, call cache_api for ORDER-82 before calling status_api for ORDER-82."
    history = [result(value=guard_value)] if guard_value is not None else []
    assert decision(source(text, history=history)).status is status


def test_guard_conflicts_are_not_cherry_picked_and_stale_is_not_current():
    text = BASE + " If the fresh result of coverage_api for ORDER-82 has active=true, call cache_api for ORDER-82 before calling status_api for ORDER-82."
    history = [result(value=True), result(value=False, event_id="e:1")]
    assert decision(source(text, history=history)).status is GoalLocalStatusV2.INCONSISTENT
    assert decision(source(text, history=[result(fresh=False)])).status is GoalLocalStatusV2.UNRESOLVED


def test_future_deadline_not_current_violation_and_failure_not_completion():
    text = BASE + " Before the session ends, complete confirm_api for ORDER-82."
    assert decision(source(text)).status is GoalLocalStatusV2.NO_ERROR
    assert decision(source(text, session_complete=True)).status is GoalLocalStatusV2.ERROR
    failed = [result("confirm_api", field="delivered", call_status="FAILURE")]
    assert decision(source(text, history=failed, session_complete=True)).status is GoalLocalStatusV2.UNRESOLVED
    success = [result("confirm_api", field="delivered")]
    assert decision(source(text, history=success, session_complete=True)).status is GoalLocalStatusV2.NO_ERROR


def test_required_result_intent_does_not_establish_verified_identity():
    text = BASE + " Before calling status_api for ORDER-82, identity_api must return verified=true for ORDER-82."
    intent = call("identity_api", kind="intent")
    assert decision(source(text, history=[intent])).status is GoalLocalStatusV2.UNRESOLVED
    assert decision(source(text, history=[result("identity_api", field="verified")])).status is GoalLocalStatusV2.NO_ERROR
    assert decision(source(text, history=[result("identity_api", value=False, field="verified")])).status is GoalLocalStatusV2.ERROR


def test_unbound_metadata_and_duplicate_event_ids_abstain_not_false_absence():
    data = source(history=[call()])
    del data["history_prefix"][0]["before_target"]
    assert evaluate_user_source_v2(data) is None
    data = source(history=[call(), deepcopy(call())])
    assert evaluate_user_source_v2(data) is None
    data = source()
    data["target_action"]["version"] = "2"
    assert evaluate_user_source_v2(data) is None


def test_source_primitives_carry_scoped_absence_and_real_evidence_ids():
    text = BASE + " Before calling status_api for ORDER-82, call cache_api for ORDER-82."
    missing = evaluate_user_source_v2(source(text))[2][0]
    assert missing.value is Truth.FALSE and missing.absence_basis == "COMPLETE_TRUSTED_SOURCE_PREFIX"
    observed = evaluate_user_source_v2(source(text, history=[call()]))[2][0]
    assert observed.value is Truth.TRUE and observed.evidence_ids == ("e:0",)


def test_open_goal_without_explicit_permissions_is_not_false_prohibition():
    assert decision(source("Read status of ORDER-82.")).status is GoalLocalStatusV2.UNRESOLVED


def test_permission_does_not_prove_capability_to_achieve_goal():
    data = source()
    del data["tool_catalog"]["status_api"]["goal_fields"]
    candidate = decision(data)
    assert candidate.alignment is GoalAlignmentV2.AMBIGUOUS
    assert candidate.status is GoalLocalStatusV2.UNRESOLVED
