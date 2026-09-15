"""E2E V1 integration tests with a deterministic scripted semantic backend.

Covers the cross-layer examples of the specification (126-128), the world
composition semantics (96, 97, 100, 101, 125), the goal firewall metamorphic
property (56), world budget fail-safe (93) and certificate gating (107).
"""

import pytest

from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend
from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1
from guardian_truth.vnext.e2e.e2e_types_v1 import E2EArmConfig, E2ECaseInput
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.semantic import Proposal

POLICY_PASSENGERS = "Do not modify the number of passengers."
USER_SEAT = "Change seat 12A to 14C."
CALL_SEAT_PAX3 = '⟦ASSISTANT_TOOL_CALL name="update_booking" call_id="target"⟧\n{"seat":"14C","passengers":3}'
CALL_SEAT_PAX2 = '⟦ASSISTANT_TOOL_CALL name="update_booking" call_id="target"⟧\n{"seat":"14C","passengers":2}'


def encoded(value):
    return canonical(value).decode("utf-8")


def h0_prohibition(policy_text, key, quote):
    return {"modality": "PROHIBITION", "actor": "assistant", "regulated_kind": "ACTION",
            "facet": "PRIMARY", "relation": "NONE",
            "target_clauses": [{"kind": "ACTION", "polarity": "POSITIVE", "normalized_key": key, "quote": quote}],
            "condition_clauses": [], "exception_clauses": [],
            "condition_mode": "ALL", "exception_mode": "ALL", "quantification": "ALL",
            "source_quotes": [policy_text], "unresolved_terms": []}


def goal_frame_desired(key, quotes, scope=None):
    return {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": key, "actor": "UNKNOWN",
            "scope_entries": scope or [], "conditions": [], "exceptions": [], "temporal": "NONE",
            "coordination": "NONE", "choice": "NONE", "alternatives": [], "quotes": quotes, "unresolved": []}


def rf_frame_desired(key, user_request, scope=None):
    support = [{"start": 0, "end": len(user_request), "quote": user_request}]
    return {"kind": "DESIRED_OUTCOME", "target_level": "ACTION", "content_key": key,
            "actor_ref": None, "entity_ref": None,
            "content_ref": support[0], "scope_entries": scope or [],
            "conditions": [], "exceptions": [], "temporal": "NONE", "coordination": "NONE",
            "choice": "NONE", "alternatives": [], "support": support, "unresolved_fields": []}


def nonverifiable_claims(payload, schema):
    spans = payload["span_inventory"]
    if payload.get("task") or True:
        fields = {"claim_disposition": {"disposition": "NON_VERIFIABLE"},
                  "claim_kind": {"kind": "NON_VERIFIABLE"},
                  "claim_actor": {"actor": "assistant"},
                  "claim_predicate": {"predicate": "greet"},
                  "claim_object_entities": {"object": "greeting", "entity_refs": []},
                  "claim_modality_polarity": {"polarity": "POSITIVE", "modality": "ASSERTED"},
                  "claim_time": {"time_anchor": "NOW"},
                  "claim_source": {"source_refs": ["ASSISTANT"]},
                  "claim_explicit_causality": {"explicit_causality": False}}
        if "relations" in schema.get("properties", {}):
            return {"relations": []}
        return {"spans": [{"span_id": span["span_id"], **fields[task_of(schema)]} for span in spans]}
    return None


def task_of(schema):
    return "claim_disposition"


class ScriptedBackend:
    """Deterministic scripted proposals keyed by task name."""

    def __init__(self, responses=None):
        self.responses = responses or {}
        self.seen = []

    def propose(self, task, payload, schema):
        self.seen.append((task, payload))
        handler = self.responses.get(task)
        if handler is None:
            return Proposal(None, "ERROR", "NOT_RUN", "scripted_missing:" + task)
        value = handler(payload, schema) if callable(handler) else handler
        if value is None:
            return Proposal(None, "ERROR", "NOT_RUN", "scripted_failure:" + task)
        return Proposal(encoded(value), "SUCCESS", "VALID")


def binding_response(tool, checks, quotes, required):
    return {"candidates": [{"tool": tool, "mode": "TARGET_INVOCATION", "checks": checks,
                           "covered_clauses": required, "source_quotes": quotes}],
            "unresolved_terms": []}


def scope_check(clause, path, values):
    return {"clause_id": clause, "path": path, "allowed_json": [encoded(value) for value in values]}


@pytest.fixture
def passengers_case():
    return E2ECaseInput(
        case_id="t-pax", family="cross_layer_policy_preservation",
        system_policy=POLICY_PASSENGERS, user_request=USER_SEAT,
        history=(), target_response="⟦ASSISTANT⟧\nDone.\n" + CALL_SEAT_PAX3,
        tool_metadata=({"name": "update_booking"},), tool_schemas=({"name": "update_booking"},),
        state_contract={"passengers": [2]}, history_complete=True,
        completeness_basis="controlled complete history",
        gold_core_status="PROVED_ERROR", gold_binary=1)


def passengers_backend():
    return ScriptedBackend({
        "policy_h0_flat_structure": lambda payload, schema: h0_prohibition(
            payload["policy"], "modify_passenger_count", "modify the number of passengers"),
        "policy_grs_grounder": lambda payload, schema: {
            "facts": [{"id": "F1", "kind": "ACTION", "meaning": "modify_passenger_count",
                       "quote": "modify the number of passengers"}],
            "modality_markers": [{"id": "M1", "surface": "Do not", "quote": "Do not"}],
            "relation_markers": []},
        "policy_grs_synth": lambda payload, schema: {"ruleset_dsl": "RULESET(RULE(FORBID, F1))"},
        "goal_conservative_frames": lambda payload, schema: {
            "frames": [goal_frame_desired("update_booking", ["Change seat 12A to 14C."],
                                          [{"field": "seat", "values": ["14C"], "quote": "seat 12A to 14C"}])]},
        "goal_rule_frames": lambda payload, schema: {
            "frames": [rf_frame_desired("update_booking", payload["user_request"],
                                        [{"field": "seat", "values": ["14C"],
                                          "ref": {"start": 14, "end": 28, "quote": "seat 12A to 14C"}}])]},
        "operational_action_binding": lambda payload, schema: _pax_binding(payload),
    })


def _pax_binding(payload):
    hypothesis = payload["hypothesis"]
    scope = payload["explicit_allowed_scope"]
    required = payload["required_clause_ids"]
    normative = payload["normative_source"]
    if hypothesis["action_or_state"] == "update_booking" and not scope:
        return binding_response("update_booking", [], [normative], required)
    checks = [scope_check("scope:" + key, [key], values) for key, values in scope.items()]
    return binding_response("update_booking", checks, [normative], required)


def claim_nonverifiable(payload, schema):
    spans = payload["span_inventory"]
    if not spans:
        return {"spans": []}
    if "relations" in schema.get("properties", {}):
        return {"relations": []}
    fields = {"claim_disposition": {"disposition": "NON_VERIFIABLE"},
              "claim_kind": {"kind": "NON_VERIFIABLE"}, "claim_actor": {"actor": "assistant"},
              "claim_predicate": {"predicate": "greet"},
              "claim_object_entities": {"object": "greeting", "entity_refs": []},
              "claim_modality_polarity": {"polarity": "POSITIVE", "modality": "ASSERTED"},
              "claim_time": {"time_anchor": "NOW"},
              "claim_source": {"source_refs": ["ASSISTANT"]},
              "claim_explicit_causality": {"explicit_causality": False}}
    key = next((task for task in fields if task.replace("claim_", "") in str(schema)) or
               [k for k, v in schema.get("properties", {}).items() if "enum" not in v][0:1], "claim_disposition")
    # Robust dispatch: inspect which property the schema demands beyond span_id.
    props = [p for p in schema["properties"]["spans"]["items"]["properties"] if p != "span_id"]
    field = props[0] if props else "disposition"
    return {"spans": [{"span_id": span["span_id"], field: fields["claim_disposition"][field] if field == "disposition" else fields.get("claim_" + field, {}).get(field, "assistant")} for span in spans]}


def with_claims(backend):
    responses = dict(backend.responses)
    for task in ("claim_disposition", "claim_kind", "claim_actor", "claim_predicate",
                 "claim_object_entities", "claim_modality_polarity", "claim_time",
                 "claim_source", "claim_relations", "claim_explicit_causality"):
        responses[task] = claim_nonverifiable
    return ScriptedBackend(responses)


def test_cross_layer_passenger_modification_is_proved_error(passengers_case):
    guardian = GuardianE2EV1(with_claims(passengers_backend()))
    analysis = guardian.analyze_e2e_v1(passengers_case)
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.product_decision.binary_label == 1
    assert analysis.result.certificate_check.valid
    assert analysis.required_worlds == 1


def test_passenger_preserved_and_seat_changed_with_closure_is_no_error(passengers_case):
    from guardian_truth.vnext.e2e.core_v1 import extract_behavior_rows
    case = passengers_case
    case = E2ECaseInput(**{**case.__dict__, "target_response": "⟦ASSISTANT⟧\nDone.\n" + CALL_SEAT_PAX2})
    backend = with_claims(passengers_backend())
    guardian = GuardianE2EV1(backend)
    # Two-pass: author the authoritative behavioral closure from a known-good
    # run, then verify NO_ERROR is certified under that closure premise.
    first = guardian.analyze_e2e_v1(case)
    policy_behaviors = extract_behavior_rows(_policy_lowered(first))
    goal_behaviors = extract_behavior_rows(_goal_lowered(first))
    case = E2ECaseInput(**{**case.__dict__,
                           "authoritative_policy_behaviors": policy_behaviors,
                           "authoritative_goal_behaviors": goal_behaviors})
    analysis = GuardianE2EV1(with_claims(passengers_backend())).analyze_e2e_v1(case)
    assert analysis.result.status.value == "PROVED_NO_ERROR"
    assert analysis.product_decision.binary_label == 0
    assert analysis.result.certificate_check.valid


def _policy_lowered(analysis):
    return analysis.policy_lowered


def _goal_lowered(analysis):
    return analysis.goal_lowered


def test_no_closure_blocks_proved_no_error(passengers_case):
    case = passengers_case
    case = E2ECaseInput(**{**case.__dict__, "target_response": "⟦ASSISTANT⟧\nDone.\n" + CALL_SEAT_PAX2})
    analysis = GuardianE2EV1(with_claims(passengers_backend())).analyze_e2e_v1(case)
    assert analysis.result.status.value == "UNRESOLVED"
    assert "COMPLETENESS_UNPROVED" in analysis.result.diagnostics.missing_evidence


def test_goal_firewall_is_invariant_across_ten_futures(passengers_case):
    backend = with_claims(passengers_backend())
    guardian = GuardianE2EV1(backend)
    futures = [
        "⟦ASSISTANT⟧\nDone.\n" + CALL_SEAT_PAX3,
        "⟦ASSISTANT⟧\nAll set.\n" + CALL_SEAT_PAX2,
        "⟦ASSISTANT⟧\nImpossible.\n",
        "⟦ASSISTANT_TOOL_CALL name=\"update_booking\" call_id=\"t9\"⟧\n{\"seat\":\"12A\"}",
        "⟦ASSISTANT⟧\nI will check first.\n⟦ASSISTANT_TOOL_CALL name=\"get_status\" call_id=\"t2\"⟧\n{}",
        "⟦ASSISTANT⟧\nCannot comply.\n",
        "⟦ASSISTANT⟧\nUpdated.\n⟦ASSISTANT_TOOL_CALL name=\"update_booking\" call_id=\"t1\"⟧\n{\"seat\":\"99Z\"}",
        "⟦ASSISTANT⟧\nYour seat is 14C.\n",
        "⟦ASSISTANT⟧\nBooking changed and invoice sent.\n⟦ASSISTANT_TOOL_CALL name=\"send_invoice\" call_id=\"t4\"⟧\n{}",
        "⟦ASSISTANT⟧\nSorry, no changes made.\n",
    ]
    goal_payloads = []
    for future in futures:
        case = E2ECaseInput(**{**passengers_case.__dict__, "target_response": future})
        backend.seen.clear()
        GuardianE2EV1(backend).analyze_e2e_v1(case)
        goal_calls = [(task, payload) for task, payload in backend.seen
                      if task in {"goal_conservative_frames", "goal_rule_frames"}]
        assert goal_calls
        for task, payload in goal_calls:
            assert set(payload) == {"user_request", "instructions"}
            goal_payloads.append((task, canonical(payload).decode("utf-8")))
    # Every future produced byte-identical goal frontend inputs (firewall).
    per_task = {}
    for task, payload in goal_payloads:
        per_task.setdefault(task, set()).add(payload)
    assert all(len(values) == 1 for values in per_task.values())
    assert len(per_task) == 1  # E0 arm: conservative only


def test_policy_error_survives_unrelated_goal_unknown(passengers_case):
    # Policy violation (passengers=3) with a goal binding that fails: the
    # certified independent violation must NOT be masked (spec 96, 125).
    backend = with_claims(passengers_backend())
    responses = dict(backend.responses)
    original = responses["operational_action_binding"]

    def goal_binding_fails(payload, schema):
        if payload["hypothesis"]["frontend"] == "goal_plan":
            return None  # scripted transport failure for the goal binding
        return original(payload, schema)
    responses["operational_action_binding"] = goal_binding_fails
    analysis = GuardianE2EV1(ScriptedBackend(responses)).analyze_e2e_v1(passengers_case)
    assert analysis.result.status.value == "PROVED_ERROR"
    assert analysis.result.certificate_check.valid


def test_h0_unavailable_is_never_safe_and_blocks_definitives(passengers_case):
    backend = with_claims(passengers_backend())
    responses = dict(backend.responses)
    responses["policy_h0_flat_structure"] = None  # transport failure
    analysis = GuardianE2EV1(ScriptedBackend(responses)).analyze_e2e_v1(passengers_case)
    assert analysis.result.status.value == "UNRESOLVED"
    assert any(name == "policy_h0" and kind == "TRANSPORT" for name, kind, _ in analysis.frontend_statuses)


def test_world_budget_exceeded_is_unresolved_not_topk():
    backend = with_claims(passengers_backend())
    responses = dict(backend.responses)

    def two_bindings(payload, schema):
        import copy
        base = _pax_binding(payload)
        second = copy.deepcopy(base["candidates"][0])
        second["tool"] = "update_reservation"
        base["candidates"] = [base["candidates"][0], second]
        return base
    responses["operational_action_binding"] = two_bindings
    guardian = GuardianE2EV1(ScriptedBackend(responses), max_worlds=1)
    analysis = guardian.analyze_e2e_v1(passengers_case := E2ECaseInput(
        case_id="t-budget", family="world_growth",
        system_policy=POLICY_PASSENGERS, user_request=USER_SEAT,
        history=(), target_response="⟦ASSISTANT⟧\nDone.\n" + CALL_SEAT_PAX3,
        tool_metadata=({"name": "update_booking"}, {"name": "update_reservation"}),
        tool_schemas=({"name": "update_booking"}, {"name": "update_reservation"}),
        state_contract={"passengers": [2]}, history_complete=True,
        completeness_basis="controlled complete history"))
    assert analysis.result.status.value == "UNRESOLVED"
    assert any("WORLD_BUDGET_EXCEEDED" in item for item in analysis.result.diagnostics.missing_evidence)
    assert analysis.problem.worlds == ()


def test_grs_arm_proves_same_error(passengers_case):
    arm = E2EArmConfig("E1", ("grs",), ("conservative",))
    analysis = GuardianE2EV1(with_claims(passengers_backend()), arm=arm).analyze_e2e_v1(passengers_case)
    assert analysis.result.status.value == "PROVED_ERROR"


def test_e4_retains_both_frontends_deduped(passengers_case):
    arm = E2EArmConfig("E4", ("h0", "grs"), ("conservative", "rule_frames"))
    analysis = GuardianE2EV1(with_claims(passengers_backend()), arm=arm).analyze_e2e_v1(passengers_case)
    assert analysis.result.status.value == "PROVED_ERROR"
    # H0 and GRS produce canonically equivalent readings -> deduped to one.
    assert len(analysis.policy_readings) == 1
    assert len(analysis.goal_contracts) == 1
