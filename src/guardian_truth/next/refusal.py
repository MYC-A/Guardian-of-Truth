"""Conservative false-refusal proof gate."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .records import FourValue


class RefusalVerdict(str, Enum):
    PROVED_FALSE_REFUSAL = "PROVED_FALSE_REFUSAL"
    POSSIBLE_FALSE_REFUSAL = "POSSIBLE_FALSE_REFUSAL"
    NOT_PROVED = "NOT_PROVED"
    INCONSISTENT = "INCONSISTENT"


@dataclass(frozen=True)
class FeasibilityCertificate:
    request_identified: FourValue
    policy_permits: FourValue
    capability_exists: FourValue
    feasible_plan_exists: FourValue
    preconditions_satisfied: FourValue
    contradicted_refusal_reason: FourValue
    system_requires_attempt: FourValue = FourValue.FALSE
    plan_is_verified: bool = False
    evidence_ids: tuple[str, ...] = ()


def assess_false_refusal(certificate: FeasibilityCertificate) -> RefusalVerdict:
    fields = (certificate.request_identified, certificate.policy_permits,
              certificate.capability_exists, certificate.feasible_plan_exists,
              certificate.preconditions_satisfied)
    grounds = (certificate.contradicted_refusal_reason,
               certificate.system_requires_attempt)
    if any(item is FourValue.BOTH for item in (*fields, *grounds)):
        return RefusalVerdict.INCONSISTENT
    if all(item is FourValue.TRUE for item in fields) and any(
            item is FourValue.TRUE for item in grounds):
        return (RefusalVerdict.PROVED_FALSE_REFUSAL if certificate.plan_is_verified
                else RefusalVerdict.POSSIBLE_FALSE_REFUSAL)
    return RefusalVerdict.NOT_PROVED
