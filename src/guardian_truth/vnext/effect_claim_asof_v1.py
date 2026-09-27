"""Proof of a typed business-effect claim from the trace prefix at answer time.

The caller must supply the claim meaning and a source cutoff. A generic
completed tool call, an audit, or a later result cannot establish the effect.
No negative world fact is inferred from missing proof.
"""
from __future__ import annotations

from dataclasses import dataclass

from .bound_tool_effects_v2 import BoundRegistry, evaluate_bound_t1
from .ledger import EvidenceLedger
from .ordered_effects_v1 import EffectRequirement
from .tools import read_path
from .types import EffectStatus, Truth


@dataclass(frozen=True)
class EffectClaimEvidence:
    fact: Truth
    claim_status: str  # SUPPORTED, REFUTED, INCONSISTENT, NOT_ESTABLISHED
    action_call_event_id: str
    answer_before_index: int
    matching_call_ids: tuple[str, ...]
    observed_result_ids: tuple[str, ...]
    proving_result_ids: tuple[str, ...]
    refuting_result_ids: tuple[str, ...]
    contract_registry_sha256: str
    scope: str = "EXACT_CALL_EFFECT_TRACE_PREFIX_AND_AUTHORITATIVE_CONTRACTS_ONLY"


def prove_effect_claim_asof(ledger: EvidenceLedger, registry: BoundRegistry,
                           requirement: EffectRequirement, entity_value: str,
                           *, action_call_event_id: str, answer_before_index: int,
                           explicit_counter: EffectRequirement | None = None) -> EffectClaimEvidence:
    """Establish a positive effect, requiring an exact entity and proven result.

    The claim must already be grounded to ONE exact assistant call. This is a
    proof about that call's outcome, not an unqualified current-world state.
    `answer_before_index` is exclusive and comes from the target answer's
    source position, never from the last event in the trace.
    """
    if (not isinstance(ledger, EvidenceLedger) or not isinstance(registry, BoundRegistry)
            or not isinstance(requirement, EffectRequirement)):
        raise TypeError("typed ledger, contracts and effect proposition required")
    if (not isinstance(entity_value, str) or not entity_value
            or not isinstance(action_call_event_id, str) or not action_call_event_id
            or type(answer_before_index) is not int
            or not 0 <= answer_before_index <= len(ledger.events)):
        raise ValueError("explicit entity and exclusive answer cutoff required")
    if explicit_counter is not None and (
            not isinstance(explicit_counter, EffectRequirement)
            or explicit_counter.identity != requirement.identity
            or explicit_counter.argument_entity_path != requirement.argument_entity_path
            or explicit_counter.predicate != requirement.predicate
            or {explicit_counter.value_json, requirement.value_json} != {"true", "false"}):
        raise ValueError("counter requires authoritative opposite Boolean values of the same typed proposition")
    calls, observed, proving, refuting = [], [], [], []
    for call in ledger.events[:answer_before_index]:
        if (call.event_id != action_call_event_id or call.kind != "call"
                or call.actor != "assistant" or call.tool != requirement.identity):
            continue
        actual, present = read_path(call.payload, requirement.argument_entity_path)
        if not present or type(actual) not in {str, int} or str(actual) != entity_value:
            continue
        calls.append(call.event_id)
        for result in ledger.results_of(call.call_id):
            if result.index <= call.index or result.index >= answer_before_index:
                continue
            observed.append(result.event_id)
            semantics = evaluate_bound_t1(registry, call, result)
            for proposition, witnesses in ((requirement, proving), (explicit_counter, refuting)):
                if proposition is not None and any(
                        effect.status is EffectStatus.TRUSTED_EFFECT
                        and effect.entity.key == ".".join(proposition.argument_entity_path)
                        and effect.entity.value == entity_value
                        and effect.predicate == proposition.predicate
                        and effect.value_json == proposition.value_json
                        and (not proposition.causal_action_required or effect.causal_action_confirmed)
                        for effect in semantics.effects):
                    witnesses.append(result.event_id)
    fact = (Truth.BOTH if proving and refuting else Truth.TRUE if proving
            else Truth.FALSE if refuting else Truth.UNKNOWN)
    status = {Truth.TRUE: "SUPPORTED", Truth.FALSE: "REFUTED",
              Truth.BOTH: "INCONSISTENT", Truth.UNKNOWN: "NOT_ESTABLISHED"}[fact]
    return EffectClaimEvidence(
        fact, status, action_call_event_id, answer_before_index, tuple(calls), tuple(observed),
        tuple(proving), tuple(refuting), registry.sha256)
