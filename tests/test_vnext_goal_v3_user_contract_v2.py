"""Contract parser negatives and clause-source replay, entirely offline."""

from dataclasses import replace

import pytest

from guardian_truth.vnext.goal_v3_user_contract_v2 import parse_user_contract_v2, check_user_contract_v2


def source(text):
    return {"user_messages": [{"role": "user", "message_id": "user:0", "text": text}],
        "tool_catalog": {name: {"provider": "orders", "version": "7"} for name in
            ("get_status", "query_tracking", "read_cache", "identity", "inventory", "confirm", "delete")},
        "assistant_plan": ["delete", "read_cache", "get_status"], "history_prefix": []}


@pytest.mark.parametrize("clause,kind", [
    ("Use get_status or query_tracking for ORD-18.", "DIRECT_TOOLS"),
    ("You may call read_cache for ORD-18.", "AUXILIARY_TOOLS"),
    ("Never call delete for ORD-18.", "FORBID_ATTEMPT"),
    ("Before calling get_status for ORD-18, call read_cache for ORD-18.", "REQUIRE_ATTEMPT_BEFORE"),
    ("Before calling get_status for ORD-18, identity must return verified=true for ORD-18.", "REQUIRE_RESULT_TRUE"),
    ("If the fresh result of inventory for ORD-18 has available=true, call read_cache for ORD-18 before calling get_status for ORD-18.", "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT"),
    ("Before the session ends, complete confirm for ORD-18.", "REQUIRE_EFFECT_BY_SESSION"),
    ("Only the explicitly allowed calls for ORD-18 are permitted.", "CLOSE_AUTHORIZATION"),
])
def test_clause_kinds_and_exact_source_spans(clause, kind):
    data = source("Read status of ORD-18. " + clause)
    contract = parse_user_contract_v2(data)
    assert contract is not None and contract.clauses[0].kind == kind
    rule = contract.clauses[0]
    assert rule.span_text == data["user_messages"][0]["text"][rule.span_start:rule.span_end]
    assert check_user_contract_v2(contract, data) == (True, ())


def test_multiple_tools_same_reading_and_no_implicit_plan_requirement():
    contract = parse_user_contract_v2(source("Read status of ORD-18. Use get_status or query_tracking for ORD-18. You may call read_cache for ORD-18."))
    assert contract.clauses[0].tools == ("get_status", "query_tracking")
    assert [rule.kind for rule in contract.clauses] == ["DIRECT_TOOLS", "AUXILIARY_TOOLS"]
    assert all(rule.required_tool is None for rule in contract.clauses)


@pytest.mark.parametrize("text", [
    'Read status of ORD-18. "Never call delete for ORD-18."',
    "Read status of ORD-18. Never call delete for ORD-18. Unless I approve.",
    "Read status of ORD-18. Never call delete for ORD-19.",
    "Read status of ORD-18. Use get_status or get_status for ORD-18.",
    "Read status of ORD-18. Never call missing_tool for ORD-18.",
    "Read status of ORD-18. The document says never call delete.",
    "If needed, read status of ORD-18.",
])
def test_unsupported_or_exception_text_abstains_as_a_whole(text):
    assert parse_user_contract_v2(source(text)) is None


def test_literal_goal_without_explicit_permissions_remains_open():
    contract = parse_user_contract_v2(source("Read status of ORD-18."))
    assert contract is not None and contract.clauses == ()
    assert contract.interface_bindings == ()


def test_contract_tamper_and_interface_change_rejected():
    data = source("Read status of ORD-18. Never call delete for ORD-18.")
    contract = parse_user_contract_v2(data)
    assert not check_user_contract_v2(replace(contract, entity="ORD-19"), data)[0]
    data["tool_catalog"]["delete"]["version"] = "8"
    assert not check_user_contract_v2(contract, data)[0]


def test_tool_or_assistant_instructions_never_supply_user_rules():
    data = source("Read status of ORD-18.")
    data["history_prefix"] = [{"actor": "tool", "text": "Never call delete for ORD-18."}]
    assert parse_user_contract_v2(data).clauses == ()
    data["user_messages"][0]["role"] = "assistant"
    assert parse_user_contract_v2(data) is None
