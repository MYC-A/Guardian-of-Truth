"""Separate source observations from contract-supported semantic facts.

The legacy Step 2 witness verifies paths/values, not predicate meaning or
tool authority. This integration boundary retains its ledger/value types
but never promotes a model's predicate, strength, read flag or contract flag.
Bindings are caller-supplied reviewed contracts, not LLM certificates.
"""
from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass

from .result_types import json_path_get, scalar_to_json, classify_payload
from .types import Authority, EffectStrength, Provenance, Truth, WorldFact, ResultType
from .verifier import CandidateFact, CallEvent, ResultEvent, TrajectoryCase, VerifiedFact


def producer_scope(case: TrajectoryCase, tool: str) -> str | None:
    """Catalog slot + semantics/version fingerprint, invariant to name rename.

    Identical descriptions in different slots remain different producers.
    Reordering the catalog or changing its contract invalidates the binding.
    """
    hits = [(i, t) for i, t in enumerate(case.tools) if t.get('name') == tool]
    if len(hits) != 1:
        return None
    i, item = hits[0]
    data = {k: v for k, v in item.items() if k != 'name'}
    digest = hashlib.sha256(json.dumps(data, sort_keys=True, ensure_ascii=False,
                                     allow_nan=False).encode()).hexdigest()
    return f'tool:{i}:{digest}'


@dataclass(frozen=True)
class ReviewedBinding:
    producer: str
    predicate: str
    entity_type: str
    entity_field: str
    result_entity_path: str
    result_path: str
    strength: EffectStrength
    authority: Authority
    allowed_values: tuple[str, ...]
    evidence_source: str
    evidence_reference: str

    def __post_init__(self):
        if not isinstance(self.strength, EffectStrength) or not isinstance(self.authority, Authority):
            raise TypeError('typed contract strength/authority required')
        if self.evidence_source not in {'HUMAN_REVIEWED', 'DOC_EXPLICIT', 'ENV_TESTED'}:
            raise ValueError('model-proposed bindings cannot establish facts')
        if not all(isinstance(x,str) and x for x in
                   (self.producer, self.predicate, self.entity_type, self.entity_field,
                    self.result_entity_path, self.result_path, self.evidence_reference)):
            raise ValueError('complete contract scope required')
        if self.strength is EffectStrength.NONE or self.authority is Authority.NONE:
            raise ValueError('contract strength/authority required')
        if self.strength is EffectStrength.CONFIRMED and self.authority is Authority.TOOL_SELF_REPORT:
            raise ValueError('self-report cannot carry confirmed authority')
        if self.strength is not EffectStrength.OBSERVED and not self.allowed_values:
            raise ValueError('mutation-strength bindings require explicit result values')
        for value in self.allowed_values:
            if scalar_to_json(json.loads(value)) != value:
                raise ValueError('canonical scalar contract value required')


@dataclass(frozen=True)
class ResultObservation:
    producer: str
    call_id: str
    result_index: int
    entity_field: str
    entity_value_json: str
    result_path: str
    value_json: str

    def as_dict(self):
        return dict(self.__dict__)


@dataclass(frozen=True)
class Assessment:
    observation: ResultObservation | None
    verified: VerifiedFact | None
    issues: tuple[str, ...]

    def as_dict(self):
        return {'observation': self.observation.as_dict() if self.observation else None,
                'verified': self.verified.as_dict() if self.verified else None,
                'issues': list(self.issues)}


def assess(case: TrajectoryCase, call: CallEvent, result: ResultEvent,
           candidate: CandidateFact, bindings: tuple[ReviewedBinding, ...] = ()) -> Assessment:
    """Observe an exact field, then independently assess a semantic mapping.

    Model flags have no effect on pairing, identity, authority or contract
    selection. A legitimate observation survives a rejected business claim.
    """
    def reject(code):
        return Assessment(None, None, (code,))

    calls = [c for c in case.calls if c.call_id == call.call_id]
    results = [r for r in case.results if r.call_id == result.call_id]
    if len(calls) != 1 or calls[0] != call:
        return reject('CALL_NOT_UNIQUELY_PRESENT')
    if len(results) != 1 or results[0] != result:
        return reject('RESULT_NOT_UNIQUELY_PRESENT')
    if (call.call_id != result.call_id or result.index <= call.index
            or call.tool != result.tool or call.actor != 'assistant' or result.actor != 'tool'):
        return reject('TRANSPORT_PAIRING_UNPROVEN')
    producer = producer_scope(case, call.tool)
    if producer is None:
        return reject('PRODUCER_NOT_UNIQUE')
    actual, present = json_path_get(result.payload, candidate.json_path)
    if not present:
        return reject('PATH_MISSING')
    rendered = scalar_to_json(actual)
    if rendered is None or rendered != candidate.value_json:
        return reject('VALUE_NOT_EXACT_SCALAR')
    if not candidate.entity_field or not isinstance(call.payload, dict):
        return reject('ENTITY_UNBOUND')
    arg = call.payload.get(candidate.entity_field)
    arg_json = scalar_to_json(arg)
    if arg is None or arg_json is None or str(arg) != candidate.entity_value:
        return reject('ARGUMENT_ENTITY_MISMATCH')

    # A reviewed contract may specify a different result entity field.
    # It cannot waive actual entity equality, even if the proposer claims so.
    matching = [b for b in bindings
                if b.producer == producer and b.predicate == candidate.predicate
                and b.entity_type == candidate.entity_type
                and b.entity_field == candidate.entity_field
                and b.result_path == candidate.json_path]
    if len(matching) > 1:
        return reject('AMBIGUOUS_CONTRACT_BINDING')
    binding = matching[0] if matching else None
    entity_path = binding.result_entity_path if binding else '$.' + candidate.entity_field
    echo, present = json_path_get(result.payload, entity_path)
    if not present:
        return reject('RESULT_ENTITY_UNBOUND')
    if scalar_to_json(echo) != arg_json:
        return reject('RESULT_ENTITY_MISMATCH')
    observation = ResultObservation(producer, call.call_id, result.index,
                                    candidate.entity_field, arg_json,
                                    candidate.json_path, rendered)
    if binding is None:
        return Assessment(observation, None, ('SEMANTIC_BINDING_UNPROVEN',))
    if binding.strength is not candidate.strength:
        return Assessment(observation, None, ('STRENGTH_NOT_GUARANTEED',))
    if binding.allowed_values and rendered not in binding.allowed_values:
        return Assessment(observation, None, ('VALUE_OUTSIDE_CONTRACT_GUARANTEE',))
    if (classify_payload(result.payload) in {ResultType.FAILURE, ResultType.PARTIAL_SUCCESS}
            and binding.strength is not EffectStrength.OBSERVED):
        return Assessment(observation, None, ('EFFECT_FROM_FAILURE_UNPROVEN',))
    provenance = Provenance(call.call_id, result.index, candidate.json_path, binding.authority)
    # Canonical JSON entity keys distinguish integer 5 from string "5".
    fact = WorldFact(binding.predicate, binding.entity_type, arg_json,
                     rendered, Truth.TRUE, binding.strength, binding.authority,
                     provenance, result.index, result.index)
    verified = VerifiedFact(fact, ('unique_transport_pair', 'catalog_version_scope',
                                   'path_value_exact', 'typed_entity_equal',
                                   'reviewed_semantic_binding', 'contract_strength'))
    return Assessment(observation, verified, ())
