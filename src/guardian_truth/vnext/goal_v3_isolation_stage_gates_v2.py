"""Offline stage/cost gates for a *future* Goal-only v2 freeze.

This module does not change the frozen v1 scorer or its results. It is not a
v2 preregistration until the complete v2 experiment is committed and sealed.
"""

from dataclasses import dataclass
import math
from typing import Sequence


S1_CASES = 12
CORE_PAIRS = 24
CORE_PAIR_RATE = 0.90
CORE_GATES = {
    "postrepair_schema_rate": (">=", 0.98),
    "resolvable_behavioral_accuracy": (">=", 0.90),
    "unsafe_unknown_definitive_rate": ("<=", 0.05),
    "unsafe_definitive_rate": ("<=", 0.05),
    "unsafe_certified_definitive_rate": ("<=", 0.0),
    "false_mandatory_plan_rate": ("<=", 0.05),
    "explicit_obligation_recall": (">=", 0.90),
    "future_false_violation_rate": ("<=", 0.05),
    "independent_violation_recall": (">=", 0.90),
    "pair_correct_rate": (">=", 0.90),
    "correct_certified_resolution_rate": (">=", 0.50),
}
S1_SCHEMA_MIN = 10
S1_STATUS_MIN = 6
S1_REPORTED_TOKEN_CEILING = 24_000


@dataclass(frozen=True)
class BudgetDecisionV2:
    reported_tokens: int
    physical_requests: int
    admit_next_request: bool
    stop_reason: str | None


def budget_after_case(physical_records: Sequence[dict], *,
                      ceiling: int = S1_REPORTED_TOKEN_CEILING) -> BudgetDecisionV2:
    """Circuit-break *after* a captured case, before another API request.

    This is not a strict provider spending cap: one request may exceed its
    advertised output limit, as observed in v1. Missing usage is fail-closed.
    Every retry is a physical request and must have its own usage record.
    """
    if type(ceiling) is not int or ceiling <= 0:
        raise ValueError("positive integer token ceiling required")
    total = 0
    for record in physical_records:
        if not isinstance(record, dict):
            raise ValueError("physical request record must be an object")
        usage = record.get("usage")
        tokens = usage.get("total_tokens") if isinstance(usage, dict) else None
        if type(tokens) is not int or tokens < 0:
            return BudgetDecisionV2(total, len(physical_records), False, "USAGE_UNVERIFIABLE")
        total += tokens
    if total >= ceiling:
        return BudgetDecisionV2(total, len(physical_records), False, "TOKEN_CEILING_REACHED")
    return BudgetDecisionV2(total, len(physical_records), True, None)


@dataclass(frozen=True)
class SmokeDecisionV2:
    verdict: str
    failed_gates: tuple[str, ...]
    attempted_cases: int
    failed_observed_pairs: tuple[str, ...]
    optimistic_max_correct_pairs: int | None
    required_correct_pairs: int
    budget: BudgetDecisionV2


def smoke_decision(rows: Sequence[dict], physical_records: Sequence[dict]) -> SmokeDecisionV2:
    """Preregisterable S1 rule; never open gold before a stage prediction seal."""
    if (any(not isinstance(row, dict) for row in rows)
            or len(physical_records) < len(rows)
            or len(physical_records) > 2 * len(rows)):
        raise ValueError("one or two captured physical requests required per scored case")
    budget = budget_after_case(physical_records)
    required = math.ceil(CORE_PAIR_RATE * CORE_PAIRS)
    if len(rows) > S1_CASES:
        raise ValueError("S1 contains more than 12 cases")
    ids = [row.get("case_id") for row in rows]
    pairs = [row.get("pair_id") for row in rows]
    if (any(not isinstance(value, str) or not value for value in ids + pairs)
            or len(set(ids)) != len(ids) or len(set(pairs)) != len(pairs)):
        raise ValueError("S1 must use distinct case IDs and distinct minimal pairs")
    for row in rows:
        if any(type(row.get(field)) is not bool for field in (
                "behavioral_correct", "status_correct", "postrepair_schema_valid", "unsafe_definitive")):
            raise ValueError("S1 scored flags must be booleans")
    failed_pairs = tuple(sorted(row["pair_id"] for row in rows if not row["behavioral_correct"]))
    optimistic = CORE_PAIRS - len(failed_pairs)
    failures = []
    if len(rows) == S1_CASES:
        if sum(row["postrepair_schema_valid"] for row in rows) < S1_SCHEMA_MIN:
            failures.append("SCHEMA_USABILITY")
        if sum(row["status_correct"] for row in rows) < S1_STATUS_MIN:
            failures.append("SCOPED_STATUS")
        if any(row["unsafe_definitive"] for row in rows):
            failures.append("UNSAFE_DEFINITIVE")
        if optimistic < required:
            failures.append("PAIR_GATE_MATHEMATICALLY_UNREACHABLE")
    if not budget.admit_next_request:
        verdict = "BUDGET_STOP"
    elif len(rows) < S1_CASES:
        verdict = "INCOMPLETE"
    else:
        verdict = "REJECT_EARLY" if failures else "ADMIT_S2"
    return SmokeDecisionV2(verdict, tuple(failures), len(rows), failed_pairs,
        optimistic, required, budget)


def core_decision_v2(metrics):
    """Require complete 48-case core and every safety/coverage gate for S3."""
    failures = []
    if (type(metrics.get("attempted_cases")) is not int or metrics["attempted_cases"] != 48
            or type(metrics.get("pair_complete_count")) is not int or metrics["pair_complete_count"] != 24):
        failures.append("INCOMPLETE_CORE")
    for name, (direction, threshold) in CORE_GATES.items():
        value = metrics.get(name)
        if (type(value) not in {int, float} or not math.isfinite(value) or not 0 <= value <= 1
                or (value < threshold if direction == ">=" else value > threshold)):
            failures.append(name)
    return {"verdict": "ADMIT_S3" if not failures else "REJECT",
        "failed_gates": failures, "gates": CORE_GATES}


def stress_decision_v2(metrics):
    """Stress informs readiness; failure cannot rewrite the passed core."""
    value = metrics.get("behavioral_accuracy")
    passed = (type(metrics.get("attempted_cases")) is int and metrics["attempted_cases"] == 12 and type(value) in {int, float}
        and math.isfinite(value) and 0.8 <= value <= 1)
    return {"verdict": "STRESS_READY_SIGNAL" if passed else "STRESS_READINESS_BLOCKER",
        "passed": passed, "threshold": 0.80}
