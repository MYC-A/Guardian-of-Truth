"""Offline checks for prospective v2 stage and token circuit breakers."""

import pytest

from guardian_truth.vnext.goal_v3_isolation_stage_gates_v2 import (
    budget_after_case, smoke_decision,
)


def rows(*, failures=0, status_failures=0, schema_failures=0, unsafe=False, n=12):
    return [{"case_id": f"C{i}", "pair_id": f"P{i}",
        "behavioral_correct": i >= failures,
        "status_correct": i >= status_failures,
        "postrepair_schema_valid": i >= schema_failures,
        "unsafe_definitive": unsafe and i == 0} for i in range(n)]


def usage_records(n=12, tokens=100):
    return [{"usage": {"total_tokens": tokens}} for _ in range(n)]


def test_pair_upper_bound_rejects_before_wasting_remaining_core_requests():
    decision = smoke_decision(rows(failures=12), usage_records())
    assert decision.verdict == "REJECT_EARLY"
    assert decision.optimistic_max_correct_pairs == 12
    assert decision.required_correct_pairs == 22
    assert "PAIR_GATE_MATHEMATICALLY_UNREACHABLE" in decision.failed_gates


def test_pair_upper_bound_accepts_exact_threshold_only():
    assert smoke_decision(rows(failures=2), usage_records()).verdict == "ADMIT_S2"
    assert smoke_decision(rows(failures=3), usage_records()).verdict == "REJECT_EARLY"


def test_cost_circuit_breaks_after_case_before_another_request():
    partial = rows(n=1)
    decision = smoke_decision(partial, usage_records(n=1, tokens=30_000))
    assert decision.verdict == "BUDGET_STOP"
    assert decision.attempted_cases == 1
    assert decision.budget.reported_tokens == 30_000
    assert decision.budget.stop_reason == "TOKEN_CEILING_REACHED"


def test_missing_provider_usage_fails_closed():
    decision = smoke_decision(rows(n=1), [{"usage": {}}])
    assert decision.verdict == "BUDGET_STOP"
    assert decision.budget.stop_reason == "USAGE_UNVERIFIABLE"


def test_schema_status_and_unsafe_gates_remain_separate():
    decision = smoke_decision(rows(schema_failures=3, status_failures=7, unsafe=True), usage_records())
    assert decision.verdict == "REJECT_EARLY"
    assert set(decision.failed_gates) == {"SCHEMA_USABILITY", "SCOPED_STATUS", "UNSAFE_DEFINITIVE"}


def test_only_one_or_two_captured_requests_per_case_and_unique_pairs():
    with pytest.raises(ValueError, match="physical requests"):
        smoke_decision(rows(n=1), [])
    duplicate = rows(n=2)
    duplicate[1]["pair_id"] = duplicate[0]["pair_id"]
    with pytest.raises(ValueError, match="distinct"):
        smoke_decision(duplicate, usage_records(n=2))


def test_budget_counts_transport_retry_usage_too():
    budget = budget_after_case(usage_records(n=2, tokens=12_000))
    assert budget.physical_requests == 2
    assert budget.reported_tokens == 24_000
    assert not budget.admit_next_request
