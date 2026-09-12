"""Small, auditable obligation solver for Guardian Next.

The module deliberately does not interpret natural language.  It combines
already-grounded primitive results and keeps disagreement/unknown information
visible until the final binary adapter.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .records import FourValue


class ObligationKind(str, Enum):
    ABSENCE = "ABSENCE"
    STATE_INVARIANT = "STATE_INVARIANT"
    NECESSARY = "NECESSARY"
    PRECEDENCE = "PRECEDENCE"
    BOUNDED_PRECEDENCE = "BOUNDED_PRECEDENCE"
    RESPONSE = "RESPONSE"
    EXCEPTION = "EXCEPTION"
    FLOW = "FLOW"
    CLAIM_SUPPORT = "CLAIM_SUPPORT"
    ARGUMENT_CONSTRAINT = "ARGUMENT_CONSTRAINT"
    OMISSION = "OMISSION"


class InternalVerdict(str, Enum):
    PROVED_ERROR = "PROVED_ERROR"
    PROVED_NO_ERROR = "PROVED_NO_ERROR"
    UNRESOLVED = "UNRESOLVED"
    INCONSISTENT = "INCONSISTENT"


@dataclass(frozen=True)
class Obligation:
    id: str
    kind: ObligationKind
    arguments: tuple[str, ...]
    rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ObligationEvaluation:
    obligation: Obligation
    satisfied: FourValue
    evidence_ids: tuple[str, ...] = ()
    completeness_sufficient: bool = False
    reason: str = ""


@dataclass(frozen=True)
class InterpretationResult:
    interpretation_id: str
    evaluations: tuple[ObligationEvaluation, ...]


@dataclass(frozen=True)
class SolverResult:
    verdict: InternalVerdict
    interpretation_verdicts: tuple[tuple[str, InternalVerdict], ...]
    obligation_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    reason: str


def _interpretation_verdict(result: InterpretationResult) -> InternalVerdict:
    values = [item.satisfied for item in result.evaluations]
    if any(value is FourValue.BOTH for value in values):
        return InternalVerdict.INCONSISTENT
    if any(value is FourValue.FALSE for value in values):
        return InternalVerdict.PROVED_ERROR
    if values and all(value is FourValue.TRUE for value in values):
        if all(item.completeness_sufficient for item in result.evaluations):
            return InternalVerdict.PROVED_NO_ERROR
    return InternalVerdict.UNRESOLVED


def solve(interpretations: tuple[InterpretationResult, ...]) -> SolverResult:
    """Aggregate every compatible policy interpretation without voting."""
    if not interpretations:
        return SolverResult(InternalVerdict.UNRESOLVED, (), (), (),
                            "no_policy_interpretation")
    per = tuple((item.interpretation_id, _interpretation_verdict(item))
                for item in interpretations)
    verdicts = {verdict for _, verdict in per}
    if InternalVerdict.INCONSISTENT in verdicts:
        final = InternalVerdict.INCONSISTENT
        reason = "trusted_assumptions_inconsistent"
    elif verdicts == {InternalVerdict.PROVED_ERROR}:
        final = InternalVerdict.PROVED_ERROR
        reason = "all_compatible_interpretations_prove_error"
    elif verdicts == {InternalVerdict.PROVED_NO_ERROR}:
        final = InternalVerdict.PROVED_NO_ERROR
        reason = "all_interpretations_complete_and_satisfied"
    else:
        final = InternalVerdict.UNRESOLVED
        reason = "compatible_interpretations_or_worlds_disagree"
    evaluations = [evaluation for interpretation in interpretations
                   for evaluation in interpretation.evaluations]
    return SolverResult(
        final,
        per,
        tuple(dict.fromkeys(item.obligation.id for item in evaluations)),
        tuple(dict.fromkeys(identifier for item in evaluations for identifier in item.evidence_ids)),
        reason,
    )
