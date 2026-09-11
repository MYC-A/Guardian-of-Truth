"""Entity-preserving claim/evidence binding."""

from __future__ import annotations

from .records import Binding, Claim, ClaimKind, EvidenceRecord, EvidenceStatus, FourValue


def _entity_map(items):
    return {key: value for key, value in items}


def _same_scope(claim: Claim, evidence: EvidenceRecord) -> bool:
    wanted = _entity_map(claim.entities)
    actual = _entity_map(evidence.entities)
    return all(key in actual and actual[key] == value for key, value in wanted.items())


def _same_predicate(claim: Claim, evidence: EvidenceRecord) -> bool:
    return (evidence.predicate == "effect_confirmed" and isinstance(evidence.object, str)
            and evidence.object.casefold() == claim.predicate.casefold())


def bind_claim(claim: Claim, evidence: list[EvidenceRecord]) -> Binding:
    scoped = [item for item in evidence if _same_scope(claim, item)]
    if claim.kind is ClaimKind.INTENT:
        return Binding(claim.id, (), FourValue.TRUE, "intent_is_not_execution_claim")
    if claim.kind is ClaimKind.ACTION:
        confirmed = [item for item in scoped
                     if item.status is EvidenceStatus.CONFIRMED and _same_predicate(claim, item)]
        if confirmed:
            return Binding(claim.id, tuple(item.id for item in confirmed), FourValue.TRUE,
                           "explicit_effect_confirmation")
        attempted = [item for item in scoped if item.status in {EvidenceStatus.ATTEMPTED, EvidenceStatus.FAILED}]
        return Binding(claim.id, tuple(item.id for item in attempted), FourValue.UNKNOWN,
                       "call_attempt_or_failure_does_not_establish_effect")
    if claim.kind is ClaimKind.ABSENCE:
        certified = [item for item in scoped if item.completeness_certificate]
        if not certified:
            return Binding(claim.id, (), FourValue.UNKNOWN,
                           "absence_requires_completeness_certificate")
    if claim.kind is ClaimKind.REFUSAL:
        return Binding(claim.id, (), FourValue.UNKNOWN,
                       "impossibility_requires_exhaustive_plan_certificate")
    return Binding(claim.id, (), FourValue.UNKNOWN, "no_exact_evidence_match")


def bind_claims(claims: list[Claim], evidence: list[EvidenceRecord]) -> list[Binding]:
    return [bind_claim(claim, evidence) for claim in claims]
