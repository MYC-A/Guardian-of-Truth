"""Deterministic primitive premises shared by solver and independent verifier.

Only evidence interpretation lives here. World aggregation and certificate
validation are separate algorithms; this module never interprets natural language.
"""

from __future__ import annotations

import json

from .ledger import EvidenceLedger, LedgerIndex
from .proof_records import AbsenceScope, AtomKind, PrimitiveProof, ProofAtom, TimeMode, conjunction, negate
from .tools import ContractRegistry, evaluate_t1
from .types import EffectStatus, Reason, Truth


def effect_is_verified(effect, ledger: EvidenceLedger, index: LedgerIndex,
                       registry: ContractRegistry) -> bool:
    if effect.status is not EffectStatus.TRUSTED_EFFECT or not effect.contract_sha256:
        return False
    result = index.events_by_id.get(effect.event_id)
    if result is None or not result.call_id or result.pairing_issue:
        return False
    calls = [event for event in index.events_by_call.get(result.call_id, ()) if event.kind == "call"]
    if len(calls) != 1:
        return False
    # No prior state is invented. Rules requiring it remain unproved unless a
    # separately grounded prior-state extension is supplied in a new version.
    regenerated = evaluate_t1(registry, calls[0], result)
    return effect in regenerated.effects and any(contract.sha256 == effect.contract_sha256 for contract in registry.contracts)


def absence_is_verified(atom: ProofAtom, scope: AbsenceScope, ledger: EvidenceLedger,
                        index: LedgerIndex, registry: ContractRegistry) -> bool:
    if (not ledger.history_complete or not ledger.completeness_basis or not scope.universe_source
            or (scope.entity, scope.predicate, scope.actor, scope.through_index)
            != (atom.entity, atom.predicate, atom.actor, atom.time_index)
            or atom.time_mode is not TimeMode.THROUGH
            or atom.kind not in {AtomKind.CALL_ATTEMPTED, AtomKind.ACTION_COMPLETED, AtomKind.HISTORICAL_ACTION}
            or scope.predicate not in scope.closed_action_universe
            or atom.time_index >= len(ledger.events) or atom.time_index < 0):
        return False
    # Complete source history is not automatically a complete action universe.
    # Unmodelled user mutation, malformed/truncated results or unknown effects
    # block an absence proof even if exact retrieval returned an empty set.
    for event in ledger.events[:atom.time_index + 1]:
        if event.actor == "unknown" or event.pairing_issue:
            return False
        if event.kind == "call":
            if not event.tool or event.tool.name not in scope.closed_action_universe or registry.lookup(event.tool) is None:
                return False
            if event.payload_json is None:
                return False
            results = [item for item in index.events_by_call.get(event.call_id, ())
                       if item.kind == "result" and item.index <= atom.time_index]
            if len(results) != 1:
                return False
            if atom.kind is not AtomKind.CALL_ATTEMPTED:
                semantics = evaluate_t1(registry, event, results[0])
                if semantics.status is not EffectStatus.TRUSTED_EFFECT:
                    return False
        elif event.kind == "result" and (not event.call_id or event.payload_json is None):
            return False
        elif event.kind == "text" and event.actor in {"user", "unknown"}:
            # Plain text is not a closed record of externally completed user actions.
            return False
    return True


def prove_atom(atom: ProofAtom, ledger: EvidenceLedger, index: LedgerIndex,
                registry: ContractRegistry, scopes: tuple[AbsenceScope, ...] = ()) -> PrimitiveProof:
    reasons, support, refute = [], [], []
    if index.ledger is not ledger:
        raise ValueError("proof indexes must match ledger snapshot")
    try:
        expected = json.loads(atom.expected_json)
    except (ValueError, TypeError):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.CLAIM_UNTYPED,))
    if atom.time_index < 0 or atom.time_index >= len(ledger.events):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.TIME_UNBOUND,))
    if atom.kind is AtomKind.TARGET_CALL_MATCH:
        return prove_target_call(atom, ledger)
    if atom.kind is AtomKind.TARGET_CALL_SCHEMA_VALID:
        return prove_target_call_schema(atom, ledger)
    exact = index.search(entity=atom.entity, time_range=(0, atom.time_index))
    evidence = [item for eid in exact.event_ids for item in index.observations_by_event.get(eid, ())
                if atom.entity in item.entity_refs and item.predicate == atom.predicate
                and (atom.kind is not AtomKind.RESULT_FIELD or atom.actor is None or item.actor == atom.actor)]
    effects = [effect for effect in index.effects_by_entity.get(atom.entity, ())
               if index.positions[effect.event_id] <= atom.time_index
               and effect_is_verified(effect, ledger, index, registry)]
    if atom.kind in {AtomKind.OBSERVED_STATE, AtomKind.RESULT_FIELD}:
        if atom.time_mode is TimeMode.THROUGH:
            # A state over an entire interval needs persistence semantics; samples
            # at a few times cannot prove it. Historical action is a different type.
            reasons.append(Reason.TEMPORAL_AMBIGUITY)
        else:
            matching = [(item.index, item.evidence_id, item.value_json) for item in evidence]
            if atom.kind is AtomKind.OBSERVED_STATE:
                matching.extend((index.positions[effect.event_id], effect.effect_id, effect.value_json)
                                for effect in effects if effect.predicate == atom.predicate)
            if atom.time_mode is TimeMode.LATEST_OBSERVATION:
                latest = max((position for position, _, _ in matching), default=-1)
                matching = [item for item in matching if item[0] == latest]
            else:
                matching = [item for item in matching if item[0] == atom.time_index]
            for _, eid, actual_json in matching:
                actual = json.loads(actual_json)
                if type(actual) is not type(expected):
                    continue
                (support if actual_json == atom.expected_json else refute).append(eid)
    else:
        if type(expected) is not bool:
            reasons.append(Reason.CLAIM_UNTYPED)
        else:
            calls = [index.events_by_id[eid] for eid in index.indexes["tool"].get(atom.predicate, ())
                     if index.events_by_id[eid].kind == "call"
                     and atom.entity in index.events_by_id[eid].entity_refs
                     and index.events_by_id[eid].actor == atom.actor
                     and index.positions[eid] <= atom.time_index
                     and (atom.kind is not AtomKind.CALL_ATTEMPTED or atom.time_mode is not TimeMode.AT or index.positions[eid] == atom.time_index)
                     and (atom.call_id is None or index.events_by_id[eid].call_id == atom.call_id)]
            if atom.kind is AtomKind.CALL_ATTEMPTED:
                occurrences = [call.event_id for call in calls]
            else:
                call_ids = {call.call_id for call in calls}
                occurrences = [effect.effect_id for effect in effects
                               if effect.call_id in call_ids and effect.causal_action_confirmed
                               and (atom.time_mode is not TimeMode.AT or index.positions[effect.event_id] == atom.time_index)]
                if atom.kind is AtomKind.CAUSAL_ATTRIBUTION:
                    if atom.call_id is None or len(calls) != 1 or not atom.effect_predicate or atom.effect_expected_json is None:
                        occurrences = []
                        reasons.append(Reason.CAUSALITY_UNPROVED)
                    else:
                        occurrences = [effect.effect_id for effect in effects if effect.effect_id in occurrences
                                       and effect.predicate == atom.effect_predicate and effect.value_json == atom.effect_expected_json]
                    if not occurrences and Reason.CAUSALITY_UNPROVED not in reasons:
                        reasons.append(Reason.CAUSALITY_UNPROVED)
            (support if expected else refute).extend(occurrences)
    scope_id = None
    if not support and not refute and atom.kind not in {AtomKind.OBSERVED_STATE, AtomKind.RESULT_FIELD, AtomKind.CAUSAL_ATTRIBUTION}:
        for scope in scopes:
            if absence_is_verified(atom, scope, ledger, index, registry):
                scope_id = scope.scope_id
                (refute if expected else support).append("absence:" + scope.scope_id)
                break
    value = Truth.BOTH if support and refute else Truth.TRUE if support else Truth.FALSE if refute else Truth.UNKNOWN
    if value is Truth.UNKNOWN and not reasons:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    return PrimitiveProof(atom, value, tuple(dict.fromkeys(support)), tuple(dict.fromkeys(refute)), scope_id, tuple(reasons))


def prove_target_call(atom: ProofAtom, ledger: EvidenceLedger) -> PrimitiveProof:
    """Compare ONE source invocation. No result, contract or effect is inferred."""
    event = ledger.events[atom.time_index]
    if (event.kind != "call" or event.source.document != "response" or event.tool is None
            or event.actor != atom.actor or event.actor == "unknown"
            or atom.entity.key != "event_id" or atom.entity.namespace != "ledger"
            or atom.entity.value != event.event_id
            or atom.call_id is not None and atom.call_id != event.call_id):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.ENTITY_UNBOUND,))
    values = [Truth.TRUE if event.tool.name == atom.predicate else Truth.FALSE]
    for constraint in atom.argument_constraints:
        actual = event.payload
        for key in constraint.path:
            if not isinstance(actual, dict) or key not in actual:
                values.append(Truth.UNKNOWN)
                break
            actual = actual[key]
        else:
            from .integrity import canonical
            encoded = canonical(actual).decode("utf-8")
            values.append(Truth.TRUE if encoded in constraint.allowed_json else Truth.FALSE)
    value = conjunction(tuple(values))
    if atom.expected_json == "false":
        value = negate(value)
    support = (event.event_id,) if value is Truth.TRUE else ()
    refute = (event.event_id,) if value is Truth.FALSE else ()
    return PrimitiveProof(atom, value, support, refute,
        reasons=(Reason.EVIDENCE_INCOMPLETE,) if value is Truth.UNKNOWN else ())


def prove_target_call_schema(atom: ProofAtom, ledger: EvidenceLedger) -> PrimitiveProof:
    """Validate one source invocation against the exact embedded declaration."""
    event = ledger.events[atom.time_index]
    if (event.kind != "call" or event.source.document != "response" or event.tool is None
            or event.actor != atom.actor or event.actor == "unknown"
            or atom.entity.key != "event_id" or atom.entity.namespace != "ledger"
            or atom.entity.value != event.event_id or atom.call_id != event.call_id
            or event.tool.name != atom.predicate):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.ENTITY_UNBOUND,))
    from .e2e.schema_validation_v1 import validate_declared_json
    schema = json.loads(atom.expected_json)
    valid, _diagnostics = validate_declared_json(event.payload, schema)
    if valid is None:
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.SCHEMA_ERROR,))
    return PrimitiveProof(atom, Truth.TRUE if valid else Truth.FALSE,
                          (event.event_id,) if valid else (),
                          () if valid else (event.event_id,))
