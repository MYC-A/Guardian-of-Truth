"""Exact numerical boundaries before any v2 inference freeze."""

from copy import deepcopy

import pytest

from guardian_truth.vnext.goal_v3_isolation_stage_gates_v2 import (
    CORE_GATES, core_decision_v2, stress_decision_v2,
)


def passing():
    return {"attempted_cases": 48, "pair_complete_count": 24,
        **{name: threshold for name, (_, threshold) in CORE_GATES.items()}}


def test_exact_core_boundaries_pass_and_nonzero_certificate_floor_exists():
    assert core_decision_v2(passing())["verdict"] == "ADMIT_S3"
    assert CORE_GATES["correct_certified_resolution_rate"] == (">=", 0.50)


@pytest.mark.parametrize("name", list(CORE_GATES))
def test_every_gate_independently_blocks_admission(name):
    metrics = passing()
    direction, threshold = CORE_GATES[name]
    metrics[name] = threshold - 0.0001 if direction == ">=" else threshold + 0.0001
    assert core_decision_v2(metrics)["failed_gates"] == [name]


@pytest.mark.parametrize("bad", [None, True, "0.99", float("nan"), float("inf"), -0.1, 1.1])
def test_missing_or_nonfinite_metrics_fail_closed(bad):
    metrics = passing()
    metrics["postrepair_schema_rate"] = bad
    assert core_decision_v2(metrics)["verdict"] == "REJECT"


def test_all_unknown_safe_system_cannot_pass_coverage_gate():
    metrics = passing()
    metrics["correct_certified_resolution_rate"] = 0
    metrics["resolvable_behavioral_accuracy"] = 0
    assert core_decision_v2(metrics)["verdict"] == "REJECT"


def test_incomplete_core_or_pairs_cannot_enter_stress():
    for key in ("attempted_cases", "pair_complete_count"):
        metrics = passing()
        metrics[key] -= 1
        assert "INCOMPLETE_CORE" in core_decision_v2(metrics)["failed_gates"]


def test_stress_readiness_signal_does_not_change_core_admission():
    metrics = {"attempted_cases": 12, "behavioral_accuracy": 0.8}
    assert stress_decision_v2(metrics)["passed"]
    metrics["behavioral_accuracy"] = 0.7999
    assert stress_decision_v2(metrics)["verdict"] == "STRESS_READINESS_BLOCKER"
    assert core_decision_v2(passing())["verdict"] == "ADMIT_S3"
