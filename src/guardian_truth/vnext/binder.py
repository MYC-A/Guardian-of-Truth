"""Indexed explicit-identity Binder. No confidence-based forced binding."""

from __future__ import annotations

from dataclasses import dataclass

from .ledger import CandidateSet, EvidenceLedger, LedgerIndex
from .types import ClaimKind, EffectStatus, EntityRef, Reason, TypedClaim


@dataclass(frozen=True)
class BindingAlternative:
    entity: EntityRef
    event_ids: tuple[str, ...]
    evidence_ids: tuple[str, ...]
    effect_ids: tuple[str, ...]


@dataclass(frozen=True)
class ClaimBinding:
    claim_id: str
    alternatives: tuple[BindingAlternative, ...]
    candidate_search: CandidateSet
    reasons: tuple[Reason, ...]
    time_index: int | None


def bind_claim(claim: TypedClaim, ledger: EvidenceLedger, index: LedgerIndex, *,
                target_index: int | None = None) -> ClaimBinding:
    target_index = len(ledger.events) - 1 if target_index is None else target_index
    if index.ledger is not ledger:
        raise ValueError("stale indexes cannot bind a different ledger snapshot")
    reasons = []
    entities = set()
    for ref in claim.entity_refs:
        entities.update(index.value_entities.get(ref, ()))
    if not entities:
        reasons.append(Reason.ENTITY_UNBOUND)
    if len(entities) > 1:
        # Same-name/different-ID possibilities are never collapsed by confidence.
        reasons.append(Reason.ENTITY_AMBIGUOUS)
    time = target_index if claim.time_anchor == "NOW" else None
    if claim.time_anchor and claim.time_anchor.startswith("event:"):
        try:
            time = int(claim.time_anchor.removeprefix("event:"))
        except ValueError:
            pass
    if claim.time_anchor in {None, "UNKNOWN", "YESTERDAY", "FUTURE"}:
        reasons.append(Reason.TIME_UNBOUND)
    if not claim.source_refs or "UNKNOWN" in claim.source_refs:
        reasons.append(Reason.SOURCE_UNBOUND)
    alternatives, all_ids = [], set()
    searched, unresolved = set(), []
    event_by_id = index.events_by_id
    for entity in sorted(entities, key=lambda e: (e.namespace, e.key, e.value)):
        candidates = index.search(entity=entity, time_range=(0, target_index))
        searched.update(candidates.searched_indexes)
        ids = set(candidates.event_ids)
        # Explicit paired results and calls are a deterministic expansion, not top-k.
        for eid in candidates.event_ids:
            event = event_by_id[eid]
            if event.call_id:
                ids.update(item.event_id for item in index.events_by_call.get(event.call_id, ()) if item.index <= target_index)
        entity_effects = index.effects_by_entity.get(entity, ())
        effects = tuple(effect.effect_id for effect in entity_effects
                        if event_by_id[effect.event_id].index <= target_index)
        ids.update(effect.event_id for effect in entity_effects if effect.effect_id in effects)
        evidences = tuple(item.evidence_id for eid in sorted(ids, key=index.positions.__getitem__)
                          for item in index.observations_by_event.get(eid, ()))
        ordered = tuple(sorted(ids, key=index.positions.__getitem__))
        alternatives.append(BindingAlternative(entity, ordered, evidences, effects))
        all_ids.update(ids)
    if not entities:
        # A failed identity lookup does not certify that relevant evidence is absent.
        unresolved.append("unbound semantic entity")
    if len(entities) > 1:
        unresolved.append("ambiguous entity identity")
    complete = ledger.history_complete and not unresolved
    candidate_set = CandidateSet(tuple(sorted(all_ids, key=index.positions.__getitem__)), complete,
        ledger.completeness_basis or "UNCERTIFIED_SUPPLIED_TRACE", tuple(sorted(searched)), tuple(unresolved))
    if not complete:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    return ClaimBinding(claim.claim_id, tuple(alternatives), candidate_set, tuple(dict.fromkeys(reasons)), time)
