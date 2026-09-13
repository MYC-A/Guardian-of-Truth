"""Goal-only typed calculus invariants; no LLM, Policy or authority promotion."""

from dataclasses import replace

import pytest

from guardian_truth.vnext.goal_v3_semantics_v2 import (
    GoalAlignmentV2, GoalLocalStatusV2, GoalObligationV2, GoalUnknownV2,
    GoalWorldV2, ObligationKindV2, aggregate_worlds_v2, evaluate_world_v2,
)
from guardian_truth.vnext.types import Truth


def world(**changes):
    base = GoalWorldV2("reading:1", GoalAlignmentV2.DIRECT, Truth.FALSE, Truth.FALSE,
        (), (), True, True)
    return replace(base, **changes)


def obligation(*, applies=Truth.TRUE, due_now=Truth.TRUE, satisfied=Truth.FALSE,
               kind=ObligationKindV2.PREREQUISITE):
    return GoalObligationV2("user:before", kind, applies, due_now, satisfied, "user:0")


def test_alternative_valid_paths_are_not_invented_mandatory_plan():
    direct = world(world_id="direct")
    auxiliary = world(world_id="aux", alignment=GoalAlignmentV2.AUXILIARY)
    result = aggregate_worlds_v2((direct, auxiliary), complete_world_inventory=True)
    assert result.status is GoalLocalStatusV2.NO_ERROR
    assert result.alignment is GoalAlignmentV2.AMBIGUOUS
    assert result.certified is False


def test_explicit_prerequisite_violation_does_not_relabel_goal_alignment():
    result = evaluate_world_v2(world(obligations=(obligation(),)))
    assert result.status is GoalLocalStatusV2.ERROR
    assert result.alignment is GoalAlignmentV2.DIRECT
    assert result.violated_rule_ids == ("user:before",)


def test_future_obligation_is_pending_not_current_violation():
    result = evaluate_world_v2(world(obligations=(obligation(
        kind=ObligationKindV2.DEADLINE, due_now=Truth.FALSE),)))
    assert result.status is GoalLocalStatusV2.NO_ERROR
    assert result.pending_rule_ids == ("user:before",)
    assert result.violated_rule_ids == ()


def test_independent_violation_survives_unrelated_unknown():
    result = evaluate_world_v2(world(prohibition_violation=Truth.TRUE,
        unknowns=(GoalUnknownV2("cache-state", False),)))
    assert result.status is GoalLocalStatusV2.ERROR
    assert result.violated_rule_ids == ("PROHIBITION",)
    assert result.nondecisive_unknown_ids == ("cache-state",)


def test_unknown_decisive_premise_blocks_no_error_and_error():
    result = evaluate_world_v2(world(scope_violation=Truth.UNKNOWN,
        unknowns=(GoalUnknownV2("scope-guard", True),)))
    assert result.status is GoalLocalStatusV2.UNRESOLVED
    assert "scope-guard" in result.unresolved_rule_ids


def test_unknown_conditional_guard_is_not_false():
    result = evaluate_world_v2(world(obligations=(obligation(
        kind=ObligationKindV2.CONDITIONAL, applies=Truth.UNKNOWN),)))
    assert result.status is GoalLocalStatusV2.UNRESOLVED
    assert result.violated_rule_ids == ()
    satisfied = evaluate_world_v2(world(obligations=(obligation(
        kind=ObligationKindV2.CONDITIONAL, applies=Truth.UNKNOWN,
        satisfied=Truth.TRUE),)))
    assert satisfied.status is GoalLocalStatusV2.NO_ERROR


def test_no_error_requires_closed_authorization_and_history():
    assert evaluate_world_v2(world(authorization_closed=False)).status is GoalLocalStatusV2.UNRESOLVED
    assert evaluate_world_v2(world(history_complete=False)).status is GoalLocalStatusV2.UNRESOLVED


def test_four_valued_conflict_is_preserved_unless_independent_error_exists():
    conflicted = world(obligations=(obligation(applies=Truth.BOTH),))
    assert evaluate_world_v2(conflicted).status is GoalLocalStatusV2.INCONSISTENT
    independent = replace(conflicted, scope_violation=Truth.TRUE)
    assert evaluate_world_v2(independent).status is GoalLocalStatusV2.ERROR


def test_all_material_worlds_must_agree_and_inventory_must_be_complete():
    safe = world(world_id="safe")
    error = world(world_id="error", scope_violation=Truth.TRUE)
    assert aggregate_worlds_v2((safe, error), complete_world_inventory=True).status is GoalLocalStatusV2.UNRESOLVED
    assert aggregate_worlds_v2((error, replace(error, world_id="error2")),
        complete_world_inventory=True).status is GoalLocalStatusV2.ERROR
    assert aggregate_worlds_v2((safe,), complete_world_inventory=False).status is GoalLocalStatusV2.UNRESOLVED


def test_untyped_model_values_and_duplicate_ids_cannot_enter_calculus():
    with pytest.raises(ValueError):
        world(scope_violation="TRUE")
    with pytest.raises(ValueError):
        obligation(applies="TRUE")
    with pytest.raises(ValueError):
        world(obligations=(obligation(), obligation()))
    with pytest.raises(ValueError):
        aggregate_worlds_v2((world(), world()), complete_world_inventory=True)
