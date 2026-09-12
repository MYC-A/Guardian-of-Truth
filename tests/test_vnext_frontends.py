import json

import pytest

from guardian_truth.vnext.goals import parse_goal_plan
from guardian_truth.vnext.policy import ClosedUniverse, parse_policy
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.types import CoverageStatus, EvaluationHypothesis, Reason, Span


def reading(**changes):
    item = {"behavioral_relation": "PROHIBITION", "actor": "assistant", "action_or_state": "archive",
        "resource": "records", "conditions": [], "exceptions": [],
        "source_quotes": ["Do not archive records."], "unresolved_terms": []}
    item.update(changes)
    return item


class Backend:
    def __init__(self, first, challenger=None):
        self.first, self.challenger = first, challenger or {"interpretations": [], "unresolved_terms": []}
        self.tasks = []

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        assert "gold" not in payload
        value = self.challenger if task == "policy_missing_interpretation_challenger" else self.first
        return Proposal(json.dumps(value), "SUCCESS", "VALID")


def test_policy_challenger_is_separate_and_empty_challenge_is_not_closed():
    backend = Backend({"interpretations": [reading()], "unresolved_terms": []})
    result = parse_policy("Do not archive records.", backend, context={"finite_schema": ["archive"]})
    assert backend.tasks == ["policy_behavioral_hypotheses", "policy_missing_interpretation_challenger"]
    assert result.coverage.status is CoverageStatus.EMPIRICALLY_COVERED
    assert not result.coverage.enumeration_complete


def test_policy_retains_distinct_challenger_reading_without_vote():
    backend = Backend({"interpretations": [reading()], "unresolved_terms": []},
        {"interpretations": [reading(behavioral_relation="PERMISSION")], "unresolved_terms": []})
    result = parse_policy("Do not archive records.", backend)
    assert len(result.hypotheses) == 2
    assert len(result.coverage.challenger_alternatives) == 1


def test_open_undefined_term_is_not_guessed_away():
    item = reading(source_quotes=["Archive old records."], unresolved_terms=["old"])
    result = parse_policy("Archive old records.", Backend({"interpretations": [item], "unresolved_terms": ["old"]}))
    assert result.coverage.status is CoverageStatus.OPEN_SEMANTICS
    assert "old" in result.coverage.unresolved_terms


def test_unsupported_quote_is_discarded_and_records_reason():
    result = parse_policy("Archive records.", Backend({"interpretations": [reading()], "unresolved_terms": []}))
    assert result.hypotheses == ()
    assert result.coverage.discarded_hypotheses
    assert Reason.POLICY_NO_INTERPRETATION in result.failures


def test_closed_authoritative_mappings_are_fully_enumerated_not_model_vote():
    text = "Do not archive records."
    trusted = EvaluationHypothesis("authoritative:0", "policy", "PROHIBITION", "assistant", "archive", "records",
                                   (), (), (Span("policy", 0, len(text)),))
    universe = ClosedUniverse("EXPLICIT_CLOSED_DEFINITION", "fixture:explicit-definition", (trusted,), True)
    result = parse_policy(text, Backend({"interpretations": [], "unresolved_terms": []}), universe=universe)
    assert result.hypotheses == (trusted,)
    assert result.coverage.status is CoverageStatus.PROVABLY_CLOSED
    assert result.coverage.enumeration_complete


@pytest.mark.parametrize("basis", ["FINITE_SCHEMA", "LLM_CONFIDENCE", "CHALLENGER_FOUND_NOTHING"])
def test_non_authoritative_universes_cannot_close_policy(basis):
    with pytest.raises(ValueError):
        ClosedUniverse(basis, "source", (), True)


def goal_reading(**changes):
    item = {"declared_goal": "Read the report", "expected_step": 0, "expected_action": "read report",
        "allowed_scope": ["report"], "target_action_state": "read report", "drift_type": "NO_DRIFT",
        "constraints": ["report only"], "source_quotes": ["Read the report"], "unresolved_terms": []}
    item.update(changes)
    return item


def test_goal_plan_uses_separate_task_and_common_downstream_hypothesis():
    backend = Backend({"hypotheses": [goal_reading()]})
    result = parse_goal_plan("Read the report", ("read report",), backend, target_action={"name": "read"})
    assert backend.tasks == ["goal_plan_semantic_hypotheses"]
    assert result.readings[0].hypothesis.frontend == "goal_plan"
    assert result.readings[0].expected_step == 0
    assert result.coverage.status is CoverageStatus.EMPIRICALLY_COVERED


def test_goal_plan_ambiguity_retains_all_readings_not_confidence_selection():
    backend = Backend({"hypotheses": [goal_reading(), goal_reading(expected_step=None, drift_type="AMBIGUOUS")]})
    result = parse_goal_plan("Read the report", ("read report",), backend)
    assert len(result.readings) == 2
    assert result.coverage.status is CoverageStatus.OPEN_SEMANTICS


def test_goal_plan_cannot_invent_out_of_range_step():
    result = parse_goal_plan("Read the report", ("read report",), Backend({"hypotheses": [goal_reading(expected_step=8)]}))
    assert result.readings == ()
    assert result.coverage.discarded_hypotheses
