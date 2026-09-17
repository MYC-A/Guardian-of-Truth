"""Version/hash-bound T1 conditional guarantees and explicitly nontrusted T2."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Mapping

from .integrity import canonical, digest
from .semantic import SemanticBackend, schema_valid
from .types import EffectRecord, EffectStatus, EntityRef, LedgerEvent, Reason, ToolIdentity


@dataclass(frozen=True)
class FieldCondition:
    source: str  # arguments, result, prior_state
    path: tuple[str, ...]
    equals_json: str


@dataclass(frozen=True)
class EffectSpec:
    argument_entity_field: str
    predicate: str
    value_json: str
    causal_action_confirmed: bool = False


@dataclass(frozen=True)
class ConditionalGuarantee:
    conditions: tuple[FieldCondition, ...]
    effects: tuple[EffectSpec, ...]


@dataclass(frozen=True)
class TrustedContract:
    identity: ToolIdentity
    preconditions: tuple[FieldCondition, ...]
    reads: tuple[str, ...]
    writes: tuple[str, ...]
    guarantees: tuple[ConditionalGuarantee, ...]
    possible_effects: tuple[EffectSpec, ...]
    no_effect_conditions: tuple[FieldCondition, ...]
    failure_semantics: str
    freshness: str
    idempotence: str
    provenance: str
    possibilities: tuple[ConditionalGuarantee, ...] = ()

    def __post_init__(self):
        if (not self.identity.provider or not self.identity.version
                or not self.identity.schema_sha256 or len(self.identity.schema_sha256) != 64
                or not self.provenance):
            raise ValueError("T1 requires version/hash-bound authoritative contract identity")

    @property
    def sha256(self):
        return digest(asdict(self))


@dataclass(frozen=True)
class ToolSemantics:
    effects: tuple[EffectRecord, ...]
    status: EffectStatus
    reasons: tuple[Reason, ...] = ()
    no_effect_proved: bool = False


class ContractRegistry:
    """Only application-supplied trusted contracts. No LLM promotion operation.

    `schemas` (optional): tool name -> schema dict supplied by the application
    (e.g. the prompt-derived [AVAILABLE TOOLS] typed catalog). Schemas feed
    ONLY deterministic catalog-conformance atoms (CALL_IN_CATALOG /
    ARGUMENT_CONFORMS_SCHEMA); they never promote a tool into a trusted
    effects contract."""

    def __init__(self, contracts: tuple[TrustedContract, ...], *, schemas: dict | None = None):
        if any(not isinstance(contract, TrustedContract) for contract in contracts):
            raise TypeError("only trusted contract objects can enter T1 registry")
        if len({contract.identity for contract in contracts}) != len(contracts):
            raise ValueError("conflicting trusted identity")
        self.contracts = contracts
        self.schemas = {name: value for name, value in (schemas or {}).items()
                        if isinstance(name, str) and isinstance(value, dict)}

    def lookup(self, identity: ToolIdentity) -> TrustedContract | None:
        return next((contract for contract in self.contracts if contract.identity == identity), None)

    def same_name(self, identity: ToolIdentity) -> bool:
        return any(contract.identity.name == identity.name for contract in self.contracts)


def read_path(value, path: tuple[str, ...]):
    for part in path:
        if not isinstance(value, dict) or part not in value:
            return None, False
        value = value[part]
    return value, True


def conditions_hold(conditions: tuple[FieldCondition, ...], sources: dict) -> bool:
    for condition in conditions:
        value, present = read_path(sources.get(condition.source), condition.path)
        if not present or canonical(value).decode("utf-8") != condition.equals_json:
            return False
    return True


def evaluate_t1(registry: ContractRegistry, call: LedgerEvent, result: LedgerEvent, *,
                prior_state: Mapping | None = None) -> ToolSemantics:
    if (call.kind != "call" or result.kind != "result" or call.call_id is None
            or result.call_id != call.call_id or result.call_candidates != (call.call_id,)
            or result.tool != call.tool or result.requestor != call.actor):
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.TOOL_EFFECT_UNKNOWN,))
    contract = registry.lookup(call.tool) if call.tool else None
    if contract is None:
        reason = Reason.TOOL_VERSION_MISMATCH if call.tool and registry.same_name(call.tool) else Reason.TOOL_EFFECT_UNKNOWN
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (reason,))
    if call.payload_json is None or result.payload_json is None:
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.EVIDENCE_INCOMPLETE,))
    sources = {"arguments": call.payload, "result": result.payload,
               "prior_state": dict(prior_state) if prior_state is not None else {}}
    if not conditions_hold(contract.preconditions, sources):
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.TOOL_EFFECT_UNKNOWN,))
    effects = []
    for rule in contract.guarantees:
        if not conditions_hold(rule.conditions, sources):
            continue
        for spec in rule.effects:
            entity, present = read_path(call.payload, tuple(spec.argument_entity_field.split(".")))
            if not present or type(entity) not in {str, int}:
                continue
            effects.append(EffectRecord(f"t1:{result.event_id}:{len(effects)}", result.event_id, call.call_id,
                EntityRef(spec.argument_entity_field, str(entity)), spec.predicate, spec.value_json,
                EffectStatus.TRUSTED_EFFECT, contract.sha256, contract.provenance, spec.causal_action_confirmed))
    no_effect = bool(contract.no_effect_conditions) and conditions_hold(contract.no_effect_conditions, sources)
    if effects or no_effect:
        return ToolSemantics(tuple(effects), EffectStatus.TRUSTED_EFFECT, (), no_effect)
    # Failure alone does NOT trigger no-effect; possible effects stay possibilities.
    possible = []
    possible_specs = list(contract.possible_effects)
    for possibility in contract.possibilities:
        if conditions_hold(possibility.conditions, sources):
            possible_specs.extend(possibility.effects)
    for spec in possible_specs:
        entity, present = read_path(call.payload, tuple(spec.argument_entity_field.split(".")))
        if present and type(entity) in {str, int}:
            possible.append(EffectRecord(f"possible:{result.event_id}:{len(possible)}", result.event_id, call.call_id,
                EntityRef(spec.argument_entity_field, str(entity)), spec.predicate, spec.value_json,
                EffectStatus.POSSIBLE_EFFECT, contract.sha256, contract.provenance, False))
    return ToolSemantics(tuple(possible), EffectStatus.POSSIBLE_EFFECT if possible else EffectStatus.UNKNOWN_EFFECT,
                         (Reason.TOOL_EFFECT_UNKNOWN,))


T2_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["hypotheses"],
    "properties": {"hypotheses": {"type": "array", "maxItems": 4, "items": {
        "type": "object", "additionalProperties": False,
        "required": ["argument_entity_field", "predicate", "value_json", "result_grounding_fields"],
        "properties": {"argument_entity_field": {"type": "string"}, "predicate": {"type": "string"},
            "value_json": {"type": "string"}, "result_grounding_fields": {"type": "array", "minItems": 1,
                "items": {"type": "string"}, "uniqueItems": True}}}}}}


def propose_t2(call: LedgerEvent, result: LedgerEvent, backend: SemanticBackend, *,
               schema: dict, authoritative_docs: str | None = None) -> ToolSemantics:
    from guardian_truth.parsing import decode_json
    if result.call_id != call.call_id or call.call_id is None or result.pairing_issue:
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.TOOL_EFFECT_UNKNOWN,))
    payload = {"tool_identity": asdict(call.tool) if call.tool else None, "schema": schema,
               "arguments": call.payload, "result": result.payload, "authoritative_docs": authoritative_docs,
               "instructions": "Propose at most four conditional candidate effects. These are NEVER observed facts or guaranteed effects. Ground entity field in actual arguments and cited result fields in actual result. Return empty hypotheses for unknown."}
    proposal = backend.propose("tool_conditional_effect_hypotheses", payload, T2_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.TRANSPORT_ERROR,))
    value = proposal.value
    if proposal.schema_status != "VALID" or not schema_valid(value, T2_SCHEMA):
        return ToolSemantics((), EffectStatus.UNKNOWN_EFFECT, (Reason.SCHEMA_ERROR,))
    effects = []
    for hypothesis in value["hypotheses"]:
        entity, present = read_path(call.payload, tuple(hypothesis["argument_entity_field"].split(".")))
        decoded, valid = decode_json(hypothesis["value_json"])
        grounded = all(read_path(result.payload, tuple(path.split(".")))[1]
                       for path in hypothesis["result_grounding_fields"])
        if not present or type(entity) not in {str, int} or not valid or not grounded or not hypothesis["predicate"]:
            continue
        effects.append(EffectRecord(f"t2:{result.event_id}:{len(effects)}", result.event_id, call.call_id,
            EntityRef(hypothesis["argument_entity_field"], str(entity)), hypothesis["predicate"], canonical(decoded).decode("utf-8"),
            EffectStatus.POSSIBLE_EFFECT, None, "UNTRUSTED_T2_SEMANTIC_PROPOSAL", False))
    status = EffectStatus.UNKNOWN_EFFECT if not effects else EffectStatus.POSSIBLE_EFFECT
    if len({(effect.entity, effect.predicate, effect.value_json) for effect in effects}) > 1:
        status = EffectStatus.AMBIGUOUS_EFFECT
    return ToolSemantics(tuple(effects), status, () if effects else (Reason.TOOL_EFFECT_UNKNOWN,))
