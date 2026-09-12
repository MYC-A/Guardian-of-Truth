"""Deterministic PolicyMeaning-to-obligation compilation boundary."""

from __future__ import annotations

from dataclasses import dataclass

from .records import PolicyMeaning, PolicyModality, RegulatedKind, SemanticUncertainty
from .solver import Obligation, ObligationKind


@dataclass(frozen=True)
class MeaningCompilation:
    meaning_id: str
    obligations: tuple[Obligation, ...]
    strict_eligible: bool
    unsupported_reasons: tuple[str, ...]


def compile_meaning(meaning: PolicyMeaning, *, trusted_predicates: frozenset[str] = frozenset()
                    ) -> MeaningCompilation:
    """Compile structure while refusing to trust unregistered open vocabulary."""
    reasons = []
    if meaning.uncertainty is not SemanticUncertainty.CERTAIN:
        reasons.append("semantic_meaning_not_certain")
    if meaning.regulated.predicate not in trusted_predicates:
        reasons.append("regulated_predicate_not_in_trusted_registry")
    obligations = []
    prefix = (meaning.subject.identifier, meaning.regulated.predicate,
              meaning.regulated.object)
    if meaning.modality in {PolicyModality.REQUIREMENT, PolicyModality.PROHIBITION}:
        kind = (ObligationKind.RESPONSE if meaning.regulated.kind is RegulatedKind.ACTION
                and meaning.conditions else ObligationKind.STATE_INVARIANT)
        obligations.append(Obligation(
            f"{meaning.id}:norm", kind,
            (*prefix, meaning.modality.value), (meaning.id,),
        ))
    for index, condition in enumerate(meaning.conditions):
        obligations.append(Obligation(
            f"{meaning.id}:condition:{index}", ObligationKind.NECESSARY,
            (condition.text, meaning.regulated.predicate), (meaning.id,),
        ))
    for index, exception in enumerate(meaning.exceptions):
        obligations.append(Obligation(
            f"{meaning.id}:exception:{index}", ObligationKind.EXCEPTION,
            (f"{meaning.id}:norm", exception.text), (meaning.id,),
        ))
    for index, identity in enumerate(meaning.identity_constraints):
        obligations.append(Obligation(
            f"{meaning.id}:identity:{index}", ObligationKind.ARGUMENT_CONSTRAINT,
            (identity.entity_type, identity.key, identity.relation, identity.value),
            (meaning.id,),
        ))
    temporal = meaning.temporal
    if temporal.relation in {"before", "after"}:
        arguments = ((meaning.regulated.predicate, temporal.anchor)
                     if temporal.relation == "before"
                     else (temporal.anchor, meaning.regulated.predicate))
        obligations.append(Obligation(
            f"{meaning.id}:temporal", ObligationKind.PRECEDENCE, arguments,
            (meaning.id,),
        ))
    elif temporal.relation == "within":
        obligations.append(Obligation(
            f"{meaning.id}:temporal", ObligationKind.BOUNDED_PRECEDENCE,
            (meaning.regulated.predicate, temporal.anchor, temporal.duration),
            (meaning.id,),
        ))
    if meaning.modality in {PolicyModality.PERMISSION, PolicyModality.DEFINITION,
                            PolicyModality.CONTEXT}:
        reasons.append("meaning_does_not_by_itself_create_strict_violation_obligation")
    return MeaningCompilation(meaning.id, tuple(obligations), not reasons, tuple(reasons))
