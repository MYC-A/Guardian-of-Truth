"""Narrow, source-scoped order check over authoritative T1 effects.

The caller supplies the action/prerequisite meanings. Missing evidence stays
UNKNOWN: a recorded trace does not close the world of external actions.
"""

from dataclasses import dataclass

from guardian_truth.parsing import decode_json

from .bound_tool_effects_v2 import BoundRegistry, evaluate_bound_t1
from .integrity import canonical
from .ledger import EvidenceLedger
from .tools import read_path
from .types import EffectStatus, ToolIdentity, Truth


@dataclass(frozen=True)
class EffectRequirement:
    identity: ToolIdentity
    argument_entity_path: tuple[str, ...]
    predicate: str
    value_json: str
    causal_action_required: bool = False

    def __post_init__(self):
        if (not self.argument_entity_path or not self.predicate
                or not self.value_json or any(not isinstance(part, str) or not part
                                                for part in self.argument_entity_path)):
            raise ValueError("exact entity path and effect proposition required")
        value, valid = decode_json(self.value_json)
        if not valid or canonical(value).decode() != self.value_json:
            raise ValueError("canonical typed effect value required")


@dataclass(frozen=True)
class OrderedEffectQuery:
    action_call_event_id: str
    action: EffectRequirement
    prerequisite: EffectRequirement


@dataclass(frozen=True)
class OrderedEffectEvidence:
    action: Truth
    prerequisite_before_action: Truth
    entity_value: str | None
    action_result_ids: tuple[str, ...] = ()
    prerequisite_result_ids: tuple[str, ...] = ()
    scope: str = "SUPPLIED_TRACE_AND_AUTHORITATIVE_T1_ONLY"
    bound_contracts_sha256: str | None = None


def _matching_results(ledger, registry, call, requirement, entity_value, *, before=None):
    if call.tool != requirement.identity or call.kind != "call" or call.actor != "assistant":
        return ()
    actual, present = read_path(call.payload, requirement.argument_entity_path)
    if not present or type(actual) not in {str, int} or str(actual) != entity_value:
        return ()
    matched = []
    for result in ledger.results_of(call.call_id):
        if before is not None and result.index >= before:
            continue
        semantics = evaluate_bound_t1(registry, call, result)
        if any(effect.status is EffectStatus.TRUSTED_EFFECT
               and effect.entity.key == ".".join(requirement.argument_entity_path)
               and effect.entity.value == entity_value
               and effect.predicate == requirement.predicate
               and effect.value_json == requirement.value_json
               and (not requirement.causal_action_required or effect.causal_action_confirmed)
               for effect in semantics.effects):
            matched.append(result.event_id)
    return tuple(matched)


def check_ordered_effects(ledger: EvidenceLedger, registry: BoundRegistry,
                          query: OrderedEffectQuery) -> OrderedEffectEvidence:
    """Prove each positive witness separately; never infer absence from silence."""
    if not isinstance(ledger, EvidenceLedger) or not isinstance(registry, BoundRegistry):
        raise TypeError("typed source ledger and bound T1 registry required")
    target = next((event for event in ledger.events
                   if event.event_id == query.action_call_event_id), None)
    if target is None or target.kind != "call" or target.actor != "assistant" or target.tool != query.action.identity:
        return OrderedEffectEvidence(Truth.UNKNOWN, Truth.UNKNOWN, None,
                                     bound_contracts_sha256=registry.sha256)
    entity, present = read_path(target.payload, query.action.argument_entity_path)
    if not present or type(entity) not in {str, int}:
        return OrderedEffectEvidence(Truth.UNKNOWN, Truth.UNKNOWN, None,
                                     bound_contracts_sha256=registry.sha256)
    entity_value = str(entity)
    action_results = _matching_results(ledger, registry, target, query.action, entity_value)
    prerequisite_results = tuple(event_id for call in ledger.events
        if call.kind == "call" and call.index < target.index
        for event_id in _matching_results(ledger, registry, call, query.prerequisite,
                                           entity_value, before=target.index))
    return OrderedEffectEvidence(
        Truth.TRUE if action_results else Truth.UNKNOWN,
        Truth.TRUE if prerequisite_results else Truth.UNKNOWN,
        entity_value, action_results, prerequisite_results,
        bound_contracts_sha256=registry.sha256)
