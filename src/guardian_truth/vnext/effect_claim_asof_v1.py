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
    claim_status: str  # SUPPORTED or NOT_ESTABLISHED
    answer_before_index: int
    matching_call_ids: tuple[str, ...]
    observed_result_ids: tuple[str, ...]
    proving_result_ids: tuple[str, ...]
    contract_registry_sha256: str
    scope: str = "TYPED_EFFECT_CLAIM_TRACE_PREFIX_AND_AUTHORITATIVE_CONTRACTS_ONLY"


def prove_effect_claim_asof(ledger: EvidenceLedger, registry: BoundRegistry,
                           requirement: EffectRequirement, entity_value: str,
                           *, answer_before_index: int) -> EffectClaimEvidence:
    """Establish a positive effect, requiring an exact entity and proven result.

    `answer_before_index` is exclusive. The caller must derive it from the
    target answer's source position, never from the last event in the trace.
    """
    if (not isinstance(ledger, EvidenceLedger) or not isinstance(registry, BoundRegistry)
            or not isinstance(requirement, EffectRequirement)):
        raise TypeError("typed ledger, contracts and effect proposition required")
    if (not isinstance(entity_value, str) or not entity_value
            or type(answer_before_index) is not int
            or not 0 <= answer_before_index <= len(ledger.events)):
        raise ValueError("explicit entity and exclusive answer cutoff required")
    calls, observed, proving = [], [], []
    for call in ledger.events[:answer_before_index]:
        if call.kind != "call" or call.actor != "assistant" or call.tool != requirement.identity:
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
            if any(effect.status is EffectStatus.TRUSTED_EFFECT
                   and effect.entity.key == ".".join(requirement.argument_entity_path)
                   and effect.entity.value == entity_value
                   and effect.predicate == requirement.predicate
                   and effect.value_json == requirement.value_json
                   and (not requirement.causal_action_required or effect.causal_action_confirmed)
                   for effect in semantics.effects):
                proving.append(result.event_id)
    return EffectClaimEvidence(
        Truth.TRUE if proving else Truth.UNKNOWN,
        "SUPPORTED" if proving else "NOT_ESTABLISHED", answer_before_index,
        tuple(calls), tuple(observed), tuple(proving), registry.sha256)
