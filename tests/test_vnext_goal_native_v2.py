import json

import pytest

from guardian_truth.vnext.goal_native import GoalClause, GoalOperator, parse_native_goal, source_inventory
from guardian_truth.vnext.goal_formula import compile_goal_clause, evaluate_compiled_clause
from guardian_truth.vnext.proof_records import AtomKind, ProofAtom, TimeMode, disjunction, negate
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import CoverageStatus, EntityRef, Reason, Truth


class Backend:
    def __init__(self, overrides=None, failed_task=None, ids=("r0",)):
        self.overrides, self.failed_task, self.ids = overrides or {}, failed_task, ids
        self.tasks = []

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        if task == self.failed_task:
            return Proposal(None, "ERROR", "NOT_EVALUATED", "timeout")
        if task.endswith("reading_inventory"):
            value = {"readings": [{"reading_id": rid, "basis": "candidate", "source_ids": ["goal:0"]} for rid in self.ids]}
        else:
            field = task.removeprefix("goal_v2_")
            defaults = {"declared_goal_source": "goal:0", "actor": "assistant", "expected_step": 0,
                "expected_action_source": "plan:0", "target_action_kind": "CALL_ATTEMPTED",
                "allowed_scope_sources": ["scope:0", "scope:1"], "drift_type": "NO_DRIFT",
                "extra_constraints": [{"operator": "NO_EXTRA_CONSTRAINT", "source_ids": ["goal:0"],
                                       "operands": [], "unresolved_terms": []}]}
            output_field = "clauses" if field == "extra_constraints" else field
            value = {"readings": [{"reading_id": rid, output_field: self.overrides.get(field, defaults[field])} for rid in self.ids]}
        return Proposal(json.dumps(value), "SUCCESS", "VALID")


def parse(backend):
    return parse_native_goal("Read and send report", ("Read report", "Send report"), backend,
                             allowed_scope={"path": ["/report"], "recipient": ["owner", "auditor"]})


def test_sources_and_all_scope_values_are_exact_not_generated_offsets():
    text, sources = source_inventory("GOAL", ("step",), {"recipient": ["a", "b"]})
    assert all(text[source.span.start:source.span.end] == source.text for source in sources)
    assert sources[-1].allowed_json == ('"a"', '"b"')


def test_narrow_passes_keep_all_order_scope_and_readings():
    backend = Backend(ids=("r0", "r1"))
    result = parse(backend)
    assert len(result.readings) == 2 and len(backend.tasks) == 9
    assert result.coverage.status is CoverageStatus.EMPIRICALLY_COVERED
    for reading in result.readings:
        assert result.expected_action(reading) == "Read report"
        assert [clause.operator for clause in reading.clauses].count(GoalOperator.SCOPE) == 2
        assert [clause.operator for clause in reading.clauses].count(GoalOperator.PLAN_STEP) == 2
        assert [clause.operator for clause in reading.clauses].count(GoalOperator.BEFORE) == 1


@pytest.mark.parametrize("field,value,unknown", [
    ("declared_goal_source", None, "declared_goal_source"),
    ("expected_step", None, "step_or_action"),
    ("expected_step", 1, "step_action_conflict"),
    ("expected_step", 2, "terminal_action_conflict"),
    ("allowed_scope_sources", ["scope:0"], "scope_coverage"),
    ("actor", "UNKNOWN", "actor"),
    ("extra_constraints", [{"operator": "IF", "source_ids": ["goal:0"], "operands": [], "unresolved_terms": []}], "constraint_arity"),
])
def test_unknown_or_conflicting_fields_do_not_disappear(field, value, unknown):
    result = parse(Backend({field: value}))
    assert unknown in result.readings[0].unknown_fields
    assert result.coverage.status is CoverageStatus.OPEN_SEMANTICS


def test_invalid_backend_value_is_rechecked_not_trusted():
    result = parse(Backend({"expected_step": 99}))
    assert ("goal_v2_expected_step", Reason.SCHEMA_ERROR) in result.failures
    assert result.readings[0].expected_step is None


def test_failed_inventory_keeps_placeholder_and_failed_field_keeps_all_readings():
    empty = parse(Backend(failed_task="goal_v2_reading_inventory"))
    assert len(empty.readings) == 1 and empty.coverage.status is CoverageStatus.OPEN_SEMANTICS
    result = parse(Backend(ids=("r0", "r1"), failed_task="goal_v2_actor"))
    assert len(result.readings) == 2
    assert all("actor" in reading.unknown_fields for reading in result.readings)
    assert ("goal_v2_actor", Reason.TRANSPORT_ERROR) in result.failures


def test_duplicate_reading_ids_are_schema_error_not_silent_deduplication():
    result = parse(Backend(ids=("r0", "r0")))
    assert result.readings[0].unknown_fields == ("reading_inventory",)
    assert ("goal_v2_reading_inventory", Reason.SCHEMA_ERROR) in result.failures


def atom(name, *, kind=AtomKind.RESULT_FIELD, time=0):
    return ProofAtom(name, kind, EntityRef("entity", "x"), "value", "true", "assistant",
                     TimeMode.THROUGH if kind is AtomKind.HISTORICAL_ACTION else TimeMode.AT, time)


@pytest.mark.parametrize("operator", [GoalOperator.IF, GoalOperator.ONLY_IF, GoalOperator.UNLESS])
@pytest.mark.parametrize("left", list(Truth))
@pytest.mark.parametrize("right", list(Truth))
def test_conditionals_exhaust_four_valued_truth_without_confidence(operator, left, right):
    clause = GoalClause("c", "r0", operator, ("goal:0",), ("a", "b"))
    compiled = compile_goal_clause(clause, {("a", "proposition"): atom("a"), ("b", "proposition"): atom("b")})
    expected = disjunction((left, negate(right))) if operator is GoalOperator.UNLESS else disjunction((negate(left), right))
    assert evaluate_compiled_clause(compiled, lambda item: {"a": left, "b": right}[item.atom_id]) is expected


def test_missing_scope_binding_is_unknown_even_with_false_applicability():
    compiled = compile_goal_clause(GoalClause("c", "r", GoalOperator.SCOPE, ("s",), ("s",)),
                                   {("s", "scope_applicable"): atom("guard")})
    assert evaluate_compiled_clause(compiled, lambda item: Truth.FALSE) is Truth.UNKNOWN


@pytest.mark.parametrize("kind,time", [(AtomKind.CALL_ATTEMPTED, 0), (AtomKind.ACTION_COMPLETED, 2)])
def test_order_rejects_attempt_as_completion_and_nonprior_event(kind, time):
    compiled = compile_goal_clause(GoalClause("c", "r", GoalOperator.BEFORE, ("a", "b"), ("a", "b")),
        {("a", "prior_completion"): atom("a", kind=kind, time=time),
         ("b", "current_attempt"): atom("b", kind=AtomKind.CALL_ATTEMPTED, time=2)})
    assert "unproved_order_binding" in compiled.unresolved_terms
    assert evaluate_compiled_clause(compiled, lambda item: Truth.TRUE) is Truth.UNKNOWN


def test_prior_completion_is_still_proved_by_evidence_not_binding_alone():
    compiled = compile_goal_clause(GoalClause("c", "r", GoalOperator.BEFORE, ("a", "b"), ("a", "b")),
        {("a", "prior_completion"): atom("a", kind=AtomKind.ACTION_COMPLETED, time=1),
         ("b", "current_attempt"): atom("b", kind=AtomKind.CALL_ATTEMPTED, time=2)})
    assert evaluate_compiled_clause(compiled, lambda item: Truth.TRUE if item.atom_id == "b" else Truth.UNKNOWN) is Truth.UNKNOWN


def test_no_extra_constraint_is_not_a_proof_of_semantic_completeness():
    compiled = compile_goal_clause(GoalClause("c", "r", GoalOperator.NO_EXTRA_CONSTRAINT, ("g",), ()), {})
    assert evaluate_compiled_clause(compiled, lambda item: Truth.TRUE) is Truth.TRUE
    assert compiled.coverage_upper_bound is CoverageStatus.EMPIRICALLY_COVERED


def test_order_cannot_credit_user_completion_to_assistant():
    from dataclasses import replace
    compiled = compile_goal_clause(GoalClause("c", "r", GoalOperator.BEFORE, ("a", "b"), ("a", "b")),
        {("a", "prior_completion"): replace(atom("a", kind=AtomKind.ACTION_COMPLETED, time=1), actor="user"),
         ("b", "current_attempt"): atom("b", kind=AtomKind.CALL_ATTEMPTED, time=2)})
    assert "unproved_order_binding" in compiled.unresolved_terms


def test_goal_progress_is_not_manufactured_from_expected_step_prediction():
    reading = parse(Backend()).readings[0]
    step = next(clause for clause in reading.clauses if clause.operator is GoalOperator.PLAN_STEP)
    compiled = compile_goal_clause(step, {("plan:0", "step_satisfied"): atom("matching_call")})
    assert "unbound:plan:0:active_step" in compiled.unresolved_terms
    assert evaluate_compiled_clause(compiled, lambda item: Truth.TRUE) is Truth.UNKNOWN
