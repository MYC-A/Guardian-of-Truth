"""Frozen final conversion from internal proof status to benchmark binary."""

from __future__ import annotations

from dataclasses import dataclass

from .solver import InternalVerdict, SolverResult


@dataclass(frozen=True)
class BinaryDecision:
    label: int
    internal_verdict: InternalVerdict
    used_fallback: bool
    mapping_version: str
    reason: str


def to_binary(result: SolverResult, *, unresolved_label: int = 0,
              inconsistent_label: int = 0) -> BinaryDecision:
    if unresolved_label not in (0, 1) or inconsistent_label not in (0, 1):
        raise ValueError("binary fallback labels must be 0 or 1")
    if result.verdict is InternalVerdict.PROVED_ERROR:
        return BinaryDecision(1, result.verdict, False, "strict-v1", result.reason)
    if result.verdict is InternalVerdict.PROVED_NO_ERROR:
        return BinaryDecision(0, result.verdict, False, "strict-v1", result.reason)
    label = (inconsistent_label if result.verdict is InternalVerdict.INCONSISTENT
             else unresolved_label)
    return BinaryDecision(label, result.verdict, True, "strict-v1", result.reason)
