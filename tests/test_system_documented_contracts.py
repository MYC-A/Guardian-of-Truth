"""Trust boundary controls for automatic structured contract acquisition."""
from __future__ import annotations

import sys
from dataclasses import replace
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.integration.contracts import acquire_documented, facts_from_documented
from guardian_truth.step2.types import EffectStrength
from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase


def case(state="queued", *, result_entity="X-7", contracts=True):
    tool = {"name": "opaque", "description": "Reports task status.",
            "parameters": {"task_id": "string"},
            "result_schema": {"task_id": "string", "state": "scalar"}}
    if contracts:
        base = {"entity_argument": "task_id", "result_entity_path": "$.task_id",
                "result_value_path": "$.state", "predicate": "task.state"}
        tool["documented_contracts"] = [
            {**base, "strength": "REQUESTED", "allowed_values": ["queued"]},
            {**base, "strength": "EXECUTED", "allowed_values": ["done"]},
        ]
    call = CallEvent(0, "q1", "opaque", {"task_id": "X-7"})
    result = ResultEvent(1, "q1", "opaque", {"task_id": result_entity,
                                             "state": state})
    return TrajectoryCase("x", "policy", "author", (tool,), (call,), (result,))


def test_disjoint_value_strength_contracts_are_not_ambiguous():
    queued, assessments, issues = facts_from_documented(case("queued"))
    assert not issues and len(queued) == 1
    assert queued[0].fact.strength is EffectStrength.REQUESTED
    assert all(a.verified for a in assessments)
    done, _, _ = facts_from_documented(case("done"))
    assert len(done) == 1 and done[0].fact.strength is EffectStrength.EXECUTED


def test_wrong_result_entity_never_establishes_fact():
    verified, assessments, _ = facts_from_documented(case(result_entity="X-8"))
    assert not verified and assessments
    assert assessments[0].issues == ("RESULT_ENTITY_MISMATCH",)


def test_prose_only_tool_does_not_acquire_business_semantics():
    verified, assessments, issues = facts_from_documented(case(contracts=False))
    assert not verified and not assessments and not issues


def test_invalid_declared_result_path_is_rejected():
    original = case()
    bad_tool = dict(original.tools[0])
    bad_tool["documented_contracts"] = [
        {**bad_tool["documented_contracts"][0],
         "result_value_path": "$.missing"}]
    acquired = acquire_documented(replace(original, tools=(bad_tool,)))
    assert not acquired.bindings
    assert acquired.issues == ("catalog:0:contract:0:result_path_unlicensed",)


def test_failure_payload_cannot_establish_even_observed_business_state():
    original = case("done")
    observed = dict(original.tools[0])
    observed["documented_contracts"] = [
        {**observed["documented_contracts"][0],
         "strength": "OBSERVED", "allowed_values": []}]
    bad_result = replace(original.results[0], payload={
        "task_id": "X-7", "state": "done", "error": "timeout"})
    altered = replace(original, tools=(observed,), results=(bad_result,))
    verified, assessments, _ = facts_from_documented(altered)
    assert not verified and assessments
    assert assessments[0].observation is not None
    assert assessments[0].issues == ("FACT_FROM_FAILURE_UNPROVEN",)
