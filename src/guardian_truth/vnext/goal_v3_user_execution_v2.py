"""Compile the completely recognized USER fragment against source-only traces.

Closure/freshness/paired-requestor fields are supplied by a trusted source
adapter, never an LLM. This controlled source format is not yet the external
competition trace adapter. Results remain local candidates, not Core proofs.
"""

from dataclasses import dataclass

from .goal_v3_semantics_v2 import (
    GoalAlignmentV2, GoalObligationV2, GoalUnknownV2, GoalWorldV2,
    ObligationKindV2, aggregate_worlds_v2,
)
from .goal_v3_user_contract_v2 import parse_user_contract_v2
from .types import Truth


@dataclass(frozen=True)
class SourcePrimitiveV2:
    rule_id: str
    query: str
    tool: str
    value: Truth
    evidence_ids: tuple[str, ...]
    absence_basis: str | None = None


def _history_valid(source):
    events = source.get("history_prefix")
    if not isinstance(events, list) or any(not isinstance(event, dict) for event in events):
        return False
    ids = [event.get("event_id") for event in events]
    return (all(isinstance(value, str) and value for value in ids)
        and len(set(ids)) == len(ids) and type(source.get("history_complete")) is bool
        and type(source.get("session_complete")) is bool
        and all(event.get("actor") in {"assistant", "user", "tool"}
            and isinstance(event.get("kind"), str)
            and type(event.get("before_target")) is bool
            and (event.get("kind") not in {"call", "result"}
                or all(isinstance(event.get(key), str) and event[key]
                    for key in ("tool", "entity", "provider", "version")))
            for event in events))


def _events(source, tool, entity):
    capability = source["tool_catalog"].get(tool, {})
    return [event for event in source["history_prefix"] if event.get("tool") == tool
        and event.get("entity") == entity and event.get("provider") == capability.get("provider")
        and event.get("version") == capability.get("version") and event.get("before_target") is True]


def _attempt(source, rule_id, tool, entity):
    qualifying = [event for event in _events(source, tool, entity)
        if event.get("kind") == "call" and event.get("actor") == "assistant"
        or event.get("kind") == "result" and event.get("actor") == "tool"
            and event.get("paired_requestor") == "assistant"]
    value = Truth.TRUE if qualifying else Truth.FALSE if source["history_complete"] else Truth.UNKNOWN
    return SourcePrimitiveV2(rule_id, "ASSISTANT_ATTEMPT_BEFORE_TARGET", tool, value,
        tuple(event["event_id"] for event in qualifying),
        "COMPLETE_TRUSTED_SOURCE_PREFIX" if value is Truth.FALSE else None)


def _boolean(source, rule_id, tool, entity, field):
    qualifying = [event for event in _events(source, tool, entity)
        if event.get("kind") == "result" and event.get("actor") == "tool"
        and event.get("paired_requestor") == "assistant" and event.get("fresh") is True
        and event.get("complete") is True and event.get("committed") is True
        and event.get("call_status") == "SUCCESS"
        and isinstance(event.get("result"), dict) and type(event["result"].get(field)) is bool]
    values = {event["result"][field] for event in qualifying}
    # Missing data does not establish a false guard or false business state.
    value = (Truth.BOTH if values == {True, False} else Truth.TRUE if values == {True}
        else Truth.FALSE if values == {False} else Truth.UNKNOWN)
    return SourcePrimitiveV2(rule_id, "FRESH_COMMITTED_BOOLEAN:" + field, tool, value,
        tuple(event["event_id"] for event in qualifying))


def _effect(source, rule_id, tool, entity):
    contract = source["tool_catalog"][tool].get("effect_contract", {})
    expected = contract.get("confirmed_when") if isinstance(contract, dict) else None
    if (not isinstance(expected, dict) or expected.get("call_status") != "SUCCESS"
            or expected.get("committed") is not True or expected.get("equals") is not True
            or not isinstance(expected.get("result_field"), str)):
        return SourcePrimitiveV2(rule_id, "CONFIRMED_EFFECT", tool, Truth.UNKNOWN, ())
    primitive = _boolean(source, rule_id, tool, entity, expected["result_field"])
    attempted = _attempt(source, rule_id, tool, entity)
    # False returned field/failure does not certify no effect without such a
    # tool contract. No qualifying attempts in a complete prefix proves absence.
    value = (Truth.TRUE if primitive.value is Truth.TRUE else Truth.BOTH
        if primitive.value is Truth.BOTH else Truth.FALSE
        if attempted.value is Truth.FALSE else Truth.UNKNOWN)
    return SourcePrimitiveV2(rule_id, "CONFIRMED_EFFECT", tool, value,
        primitive.evidence_ids, attempted.absence_basis if value is Truth.FALSE else None)


def evaluate_user_source_v2(source):
    """Return (contract, candidate, primitives), or None on unsupported source."""
    contract = parse_user_contract_v2(source)
    if contract is None or not _history_valid(source):
        return None
    target = source.get("target_action")
    if not isinstance(target, dict):
        return None
    tool = target.get("tool")
    capability = source["tool_catalog"].get(tool) if isinstance(tool, str) else None
    if (target.get("actor") != "assistant" or target.get("kind") != "tool_call"
            or not isinstance(capability, dict) or not isinstance(capability.get("provider"), str)
            or not capability["provider"] or not isinstance(capability.get("version"), str)
            or not capability["version"] or target.get("provider") != capability["provider"]
            or target.get("version") != capability["version"]
            or not isinstance(target.get("entity"), str) or not target["entity"]):
        return None
    direct = {name for rule in contract.clauses if rule.kind == "DIRECT_TOOLS" for name in rule.tools}
    # USER permission to use a tool does not prove its semantic ability to
    # achieve the requested outcome. That mapping needs trusted tool metadata.
    goal_fields = capability.get("goal_fields")
    direct_support = tool in direct and isinstance(goal_fields, list) and contract.desired_field in goal_fields
    auxiliary = {name for rule in contract.clauses if rule.kind == "AUXILIARY_TOOLS" for name in rule.tools}
    # Mandatory prior steps are legitimate auxiliaries, not mandatory plans.
    auxiliary.update(rule.required_tool for rule in contract.clauses if rule.kind in
        {"REQUIRE_ATTEMPT_BEFORE", "REQUIRE_RESULT_TRUE", "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT",
         "REQUIRE_EFFECT_BY_SESSION"})
    auxiliary.update(rule.guard_tool for rule in contract.clauses if rule.guard_tool)
    closed = any(rule.kind == "CLOSE_AUTHORIZATION" for rule in contract.clauses)
    entity_matches = target["entity"] == contract.entity
    permitted = entity_matches and tool in direct | auxiliary
    scope = Truth.FALSE if permitted or not closed else Truth.TRUE
    forbidden = entity_matches and any(rule.kind == "FORBID_ATTEMPT" and rule.required_tool == tool
        for rule in contract.clauses)
    alignment = (GoalAlignmentV2.OUT_OF_SCOPE if scope is Truth.TRUE or forbidden
        else GoalAlignmentV2.DIRECT if entity_matches and direct_support
        else GoalAlignmentV2.AUXILIARY if entity_matches and tool in auxiliary
        else GoalAlignmentV2.AMBIGUOUS)
    obligations, primitives = [], []
    for rule in contract.clauses:
        if rule.kind not in {"REQUIRE_ATTEMPT_BEFORE", "REQUIRE_RESULT_TRUE",
                "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT", "REQUIRE_EFFECT_BY_SESSION"}:
            continue
        deadline = rule.kind == "REQUIRE_EFFECT_BY_SESSION"
        applicable = Truth.TRUE if deadline or rule.trigger_tool == tool and entity_matches else Truth.FALSE
        due = Truth.TRUE if not deadline or source["session_complete"] else Truth.FALSE
        if rule.kind == "REQUIRE_RESULT_TRUE":
            primitive = _boolean(source, rule.rule_id, rule.required_tool, contract.entity, rule.result_field)
        elif deadline:
            primitive = _effect(source, rule.rule_id, rule.required_tool, contract.entity)
        else:
            primitive = _attempt(source, rule.rule_id, rule.required_tool, contract.entity)
        primitives.append(primitive)
        if rule.kind == "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT" and applicable is Truth.TRUE:
            guard = _boolean(source, rule.rule_id, rule.guard_tool, contract.entity, rule.result_field)
            primitives.append(guard)
            applicable = guard.value
        obligations.append(GoalObligationV2(rule.rule_id, ObligationKindV2.DEADLINE if deadline
            else ObligationKindV2.CONDITIONAL if rule.guard_tool else ObligationKindV2.PREREQUISITE,
            applicable, due, primitive.value, rule.message_id))
    unknowns = (() if source.get("unrelated_state") is None else
        (GoalUnknownV2("unrelated_state", False),))
    world = GoalWorldV2("user-fragment:0", alignment, scope,
        Truth.TRUE if forbidden else Truth.FALSE, tuple(obligations), unknowns,
        closed, source["history_complete"])
    return contract, aggregate_worlds_v2((world,), complete_world_inventory=True), tuple(primitives)
