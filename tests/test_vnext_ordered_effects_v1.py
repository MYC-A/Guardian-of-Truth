"""State-backed paired controls for source-bound tool effects and event order."""

import json
from dataclasses import replace

import pytest

from guardian_truth.vnext.bound_tool_effects_v2 import (
    BoundContract, BoundRegistry, FieldEquality, evaluate_bound_t1,
)
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.normalize import tool_identity
from guardian_truth.vnext.ordered_effects_v1 import (
    EffectRequirement, OrderedEffectQuery, check_ordered_effects,
)
from guardian_truth.vnext.source_envelope_v4 import SourceEnvelope, SourceFrame, normalize_envelope
from guardian_truth.vnext.tools import (
    ConditionalGuarantee, ContractRegistry, EffectSpec, FieldCondition, TrustedContract, evaluate_t1,
)
from guardian_truth.vnext.types import EffectStatus, Span, Truth


IDENTITIES = {name: tool_identity(name, {"case_id": "string"}, provider="state-fixture", version="1")
              for name in ("approve_case", "replace_item", "record_audit")}


def contract(name, field, value, predicate, *, causal=False):
    expected = canonical(value).decode()
    return TrustedContract(IDENTITIES[name], (), (), (predicate,),
        (ConditionalGuarantee((FieldCondition("result", (field,), expected),),
                              (EffectSpec("case_id", predicate, expected, causal),)),),
        (), (), "unknown on failure", "event order", "not assumed", "authored fixture simulator")


REGISTRY = BoundRegistry((
    BoundContract(contract("approve_case", "approved", True, "approved"),
                  (FieldEquality(("case_id",), ("case_id",)),)),
    BoundContract(contract("replace_item", "replacement_state", "replaced", "replacement_state", causal=True),
                  (FieldEquality(("case_id",), ("case_id",)),)),
    BoundContract(contract("record_audit", "audited", True, "audited"),
                  (FieldEquality(("case_id",), ("case_id",)),)),
))
QUERY_ACTION = EffectRequirement(IDENTITIES["replace_item"], ("case_id",),
                                  "replacement_state", '"replaced"', True)
QUERY_APPROVAL = EffectRequirement(IDENTITIES["approve_case"], ("case_id",), "approved", "true")


def step(name, case_id="SD-101", *, tid=None, result=None, result_case=None, result_tid=None):
    return (name, case_id, tid or name, result, result_case, result_tid)


APPROVAL = step("approve_case", result={"approved": True, "status": "completed"})
REPLACEMENT = step("replace_item", result={"replacement_state": "replaced", "status": "completed"})
AUDIT = step("record_audit", result={"audited": True, "status": "completed"})


def replay(steps):
    """Application-owned frames; generic completed status has no business meaning."""
    prompt, frames = "", []
    for name, case_id, tid, result, result_case, result_tid in steps:
        identity = IDENTITIES[name]
        messages = [("assistant", "call", {"case_id": case_id}, tid, None)]
        if result is not None:
            messages.append(("tool", "result", {"case_id": result_case or case_id, **result},
                             result_tid or tid, "assistant"))
        for actor, kind, payload, transport, requestor in messages:
            body = json.dumps(payload, separators=(",", ":"))
            begin = len(prompt)
            prompt += body + "\n"
            span = Span("prompt", begin, begin + len(body))
            frames.append(SourceFrame(span, span, actor, kind, identity, transport, requestor))
    envelope = SourceEnvelope(prompt, "", tuple(frames), "state-fixture", "1",
                              "controlled source simulator", True, "complete supplied fixture trace")
    return normalize_envelope(envelope).ledger


@pytest.mark.parametrize("steps,action,prerequisite", [
    ([APPROVAL, REPLACEMENT], Truth.TRUE, Truth.TRUE),
    ([step("approve_case", "SD-999", result={"approved": True}), REPLACEMENT], Truth.TRUE, Truth.UNKNOWN),
    ([REPLACEMENT, APPROVAL], Truth.TRUE, Truth.UNKNOWN),
    ([APPROVAL, AUDIT, REPLACEMENT], Truth.TRUE, Truth.TRUE),
    ([APPROVAL, step("replace_item", result={"status": "completed"}), AUDIT], Truth.UNKNOWN, Truth.TRUE),
    ([APPROVAL, step("replace_item", result={"replacement_state": "replaced"}, result_case="SD-999")], Truth.UNKNOWN, Truth.TRUE),
    ([APPROVAL, step("replace_item", result={"replacement_state": "replaced"}, result_tid="wrong")], Truth.UNKNOWN, Truth.TRUE),
    ([APPROVAL, step("replace_item", result={"replacement_state": "failed", "status": "completed"})], Truth.UNKNOWN, Truth.TRUE),
    ([APPROVAL, step("replace_item"), AUDIT], Truth.UNKNOWN, Truth.TRUE),
    ([APPROVAL, step("replace_item", tid="duplicate"), step("replace_item", tid="duplicate",
                     result={"replacement_state": "replaced"}, result_tid="duplicate")], Truth.UNKNOWN, Truth.TRUE),
])
def test_ordered_effects_keep_action_entity_and_prerequisite_separate(steps, action, prerequisite):
    ledger = replay(steps)
    target = next(event for event in ledger.events
                  if event.kind == "call" and event.tool == IDENTITIES["replace_item"])
    evidence = check_ordered_effects(ledger, REGISTRY,
                                     OrderedEffectQuery(target.event_id, QUERY_ACTION, QUERY_APPROVAL))
    assert (evidence.action, evidence.prerequisite_before_action) == (action, prerequisite)
    assert bool(evidence.action_result_ids) == (action is Truth.TRUE)
    assert bool(evidence.prerequisite_result_ids) == (prerequisite is Truth.TRUE)


def test_audit_success_alone_cannot_prove_replacement_even_with_same_case_and_status():
    ledger = replay([APPROVAL, AUDIT])
    evidence = check_ordered_effects(ledger, REGISTRY,
        OrderedEffectQuery("missing-replacement-call", QUERY_ACTION, QUERY_APPROVAL))
    assert evidence.action is Truth.UNKNOWN
    assert evidence.prerequisite_before_action is Truth.UNKNOWN


def test_query_requires_a_typed_canonical_effect_value():
    with pytest.raises(ValueError, match="canonical typed"):
        EffectRequirement(IDENTITIES["replace_item"], ("case_id",),
                          "replacement_state", "replaced")


def test_bound_t1_blocks_wrong_entity_that_legacy_t1_would_accept():
    ledger = replay([step("replace_item", result={"replacement_state": "replaced"},
                          result_case="SD-999")])
    call, result = ledger.events
    legacy = evaluate_t1(ContractRegistry((REGISTRY.by_identity[call.tool].t1,)), call, result)
    bound = evaluate_bound_t1(REGISTRY, call, result)
    assert legacy.status is EffectStatus.TRUSTED_EFFECT  # historical behavior preserved
    assert bound.status is EffectStatus.UNKNOWN_EFFECT and bound.effects == ()
    assert REGISTRY.sha256 != REGISTRY.by_identity[call.tool].t1.sha256


def test_bound_t1_rejects_reversed_or_forged_tool_results():
    call, result = replay([REPLACEMENT]).events
    for altered in (replace(result, index=call.index),
                    replace(result, actor="assistant"),
                    replace(result, pairing_issue="AMBIGUOUS_CALL_IDENTITY"),
                    replace(result, source=Span("response", 0, 2))):
        assert evaluate_bound_t1(REGISTRY, call, altered).effects == ()


def test_bound_registry_requires_explicit_entity_join():
    with pytest.raises(ValueError, match="explicit call/result joins"):
        BoundContract(REGISTRY.by_identity[IDENTITIES["replace_item"]].t1, ())


def test_sandbox_post_state_oracle_distinguishes_completed_audit_from_replacement():
    def simulate(action):
        state = {"approved": set(), "replaced": set(), "audited": set()}
        state["approved"].add("SD-101")
        result = {"status": "completed"}
        if action == "replace_item":
            state["replaced"].add("SD-101")
            result["replacement_state"] = "replaced"
        else:
            state["audited"].add("SD-101")
            result["audited"] = True
        steps = [APPROVAL, step(action, result=result)]
        if action == "record_audit":
            steps.append(step("replace_item"))  # attempted, with no result
        return replay(steps), state

    for action in ("replace_item", "record_audit"):
        ledger, state = simulate(action)
        target = next(event for event in ledger.events
                      if event.kind == "call" and event.tool == IDENTITIES["replace_item"])
        evidence = check_ordered_effects(ledger, REGISTRY,
            OrderedEffectQuery(target.event_id, QUERY_ACTION, QUERY_APPROVAL))
        assert (evidence.action is Truth.TRUE) == ("SD-101" in state["replaced"])
        assert evidence.prerequisite_before_action is Truth.TRUE
