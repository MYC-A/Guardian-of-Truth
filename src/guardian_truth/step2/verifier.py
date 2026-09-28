"""Deterministic provenance verifier (sections 20-21).

Every candidate fact — whether proposed by an LLM, a contract, or a
structural rule — must pass this witness before it can enter the ledger.
The witness checks, in order:

1. the result is paired to the call (same call_id, result after call);
2. the payload decodes;
3. the cited json_path actually resolves in the result payload;
4. the value at that path equals the proposed value (typed equality);
5. the entity value equals the actual call argument at the entity field;
6. the result type supports the claimed strength
   (generic SUCCESS_ACK can never witness EXECUTED/CONFIRMED);
7. ordering: the fact's observation time is the result's index.

A rejected proposal is recorded with its reason and becomes UNKNOWN — it is
never silently dropped and never established.
"""

from __future__ import annotations

from dataclasses import dataclass

from .result_types import ResultType, classify_payload, json_path_get, scalar_to_json
from .types import (Authority, EffectClass, EffectStrength, Provenance, Truth,
                    WorldFact)

# Which result types can witness which mutation-side strength.
_STRENGTH_WITNESS: dict[EffectStrength, frozenset[ResultType]] = {
    EffectStrength.REQUESTED: frozenset({ResultType.ASYNC_ACCEPTED,
                                         ResultType.BUSINESS_STATE}),
    EffectStrength.INITIATED: frozenset({ResultType.ASYNC_ACCEPTED,
                                         ResultType.BUSINESS_STATE}),
    EffectStrength.EXECUTED: frozenset({ResultType.BUSINESS_STATE}),
    EffectStrength.CONFIRMED: frozenset({ResultType.BUSINESS_STATE,
                                         ResultType.OBSERVATION}),
    EffectStrength.OBSERVED: frozenset({ResultType.OBSERVATION,
                                        ResultType.BUSINESS_STATE}),
    EffectStrength.NONE: frozenset(),
}

REJECTION_CODES = (
    "CALL_NOT_FOUND", "RESULT_NOT_PAIRED", "PAYLOAD_UNDECODABLE",
    "PATH_MISSING", "VALUE_MISMATCH", "ENTITY_MISMATCH", "NOT_SCALAR",
    "STRENGTH_UNWITNESSED", "FAILURE_RESULT", "ORDER_VIOLATION",
)


@dataclass(frozen=True)
class CandidateFact:
    """An unverified proposal for one world fact."""

    predicate: str
    entity_type: str
    entity_field: str            # argument path in the call, e.g. "order_id"
    entity_value: str
    value_json: str              # canonical scalar JSON, e.g. '"cancelled"'
    json_path: str               # "$.status" in the RESULT
    strength: EffectStrength
    effect_class: EffectClass = EffectClass.UNKNOWN
    is_observation: bool = False
    contract_bound: bool = False  # documented contract joins call/result entities

    def as_dict(self) -> dict:
        return {"predicate": self.predicate, "entity_type": self.entity_type,
                "entity_field": self.entity_field, "entity_value": self.entity_value,
                "value_json": self.value_json, "json_path": self.json_path,
                "strength": self.strength.value, "effect_class": self.effect_class.value,
                "is_observation": self.is_observation}


@dataclass(frozen=True)
class VerifiedFact:
    fact: WorldFact
    witness_checks: tuple[str, ...]

    def as_dict(self) -> dict:
        return {"fact": self.fact.as_dict(), "witness_checks": list(self.witness_checks)}


@dataclass(frozen=True)
class Rejected:
    candidate: CandidateFact
    code: str
    detail: str

    def as_dict(self) -> dict:
        return {"candidate": self.candidate.as_dict(), "code": self.code,
                "detail": self.detail}


def _decode_value(value_json: str):
    import json
    try:
        return json.loads(value_json), True
    except (ValueError, TypeError):
        return None, False


def _result_id_echoes(payload: Any) -> list[str]:
    """Collect values of id-shaped fields in the result (bounded depth)."""
    out: list[str] = []

    def walk(node, depth=0):
        if depth > 3 or not isinstance(node, dict):
            return
        for key, value in node.items():
            if isinstance(value, str) and (key.endswith("_id") or key.endswith("_ids")
                                            or key in ("id", "ref", "reference")):
                out.append(value)
            elif isinstance(value, dict):
                walk(value, depth + 1)
            elif isinstance(value, list) and value and isinstance(value[0], str):
                out.extend(value[:8])

    walk(payload)
    return out


def verify_candidate(case: "TrajectoryCase", call: "CallEvent", result: "ResultEvent",
                     candidate: CandidateFact) -> VerifiedFact | Rejected:
    """Run the full witness on one candidate fact. Pure, deterministic."""
    # 1. pairing
    if result.call_id != call.call_id or result.index <= call.index:
        return Rejected(candidate, "RESULT_NOT_PAIRED",
                        f"result {result.call_id}@{result.index} not after call {call.call_id}@{call.index}")
    # 2. payload
    if result.payload is None:
        return Rejected(candidate, "PAYLOAD_UNDECODABLE", "result payload missing/not JSON")
    result_type = classify_payload(result.payload)
    if result_type is ResultType.FAILURE:
        return Rejected(candidate, "FAILURE_RESULT", "result carries a failure marker")
    # 3. path resolves
    actual, present = json_path_get(result.payload, candidate.json_path)
    if not present:
        return Rejected(candidate, "PATH_MISSING", f"{candidate.json_path} absent in result")
    # 4. typed value equality
    proposed, valid = _decode_value(candidate.value_json)
    if not valid:
        return Rejected(candidate, "NOT_SCALAR", "value_json is not decodable JSON")
    rendered = scalar_to_json(actual)
    if rendered is None:
        return Rejected(candidate, "NOT_SCALAR", f"value at {candidate.json_path} is not a scalar")
    if rendered != candidate.value_json:
        return Rejected(candidate, "VALUE_MISMATCH",
                        f"path value {rendered} != proposed {candidate.value_json}")
    # 5. entity binding: argument must carry the entity value
    if candidate.entity_field:
        arg_value = call.payload.get(candidate.entity_field) if isinstance(call.payload, dict) else None
        if arg_value is None or str(arg_value) != candidate.entity_value:
            return Rejected(candidate, "ENTITY_MISMATCH",
                            f"call argument {candidate.entity_field}={arg_value!r} != {candidate.entity_value!r}")
    # 5b. result-side entity echo: if the result names entity ids explicitly,
    # the claimed entity must be among them; a same-key field carrying a
    # different id is an explicit contradiction. A result with no id-shaped
    # content leaves the entity unbound — honest UNKNOWN — unless a
    # documented contract already joins call and result entities.
    if not candidate.contract_bound:
        same_key = None
        if candidate.entity_field and isinstance(result.payload, dict):
            same_key = result.payload.get(candidate.entity_field)
        idish = _result_id_echoes(result.payload)
        if same_key is not None and str(same_key) != candidate.entity_value:
            return Rejected(candidate, "ENTITY_MISMATCH",
                            f"result {candidate.entity_field}={same_key!r} != claimed {candidate.entity_value!r}")
        if candidate.entity_value in idish:
            pass  # positive echo somewhere in the result
        elif idish:
            return Rejected(candidate, "ENTITY_MISMATCH",
                            f"result names other entities {idish[:3]!r}, not {candidate.entity_value!r}")
        elif candidate.entity_field:
            return Rejected(candidate, "ENTITY_UNBOUND",
                            "result carries no entity echo; entity binding unproven")
    # 6. strength witnessing
    allowed = _STRENGTH_WITNESS.get(candidate.strength, frozenset())
    if result_type not in allowed:
        return Rejected(candidate, "STRENGTH_UNWITNESSED",
                        f"{result_type.value} result cannot witness {candidate.strength.value}")
    authority = (Authority.READ_OBSERVATION if candidate.is_observation
                 or candidate.strength is EffectStrength.OBSERVED
                 else Authority.TOOL_SELF_REPORT)
    fact = WorldFact(
        predicate=candidate.predicate,
        entity_type=candidate.entity_type,
        entity_id=candidate.entity_value,
        value=candidate.value_json,
        truth=Truth.TRUE,
        strength=candidate.strength,
        authority=authority,
        provenance=Provenance(call_id=call.call_id, result_index=result.index,
                              json_path=candidate.json_path, authority=authority),
        observed_at=result.index,
        valid_from=result.index,
    )
    checks = ("paired", "decoded", "path_present", "value_equal",
              "entity_bound", "strength_witnessed")
    return VerifiedFact(fact, checks)


# --- trajectory value objects (shared with the dataset runner) -------------

@dataclass(frozen=True)
class CallEvent:
    index: int
    call_id: str
    tool: str                # catalog name (may be an opaque rename)
    payload: dict | None
    actor: str = "assistant"


@dataclass(frozen=True)
class ResultEvent:
    index: int
    call_id: str
    tool: str
    payload: dict | None
    raw_text: str | None = None
    actor: str = "tool"


@dataclass(frozen=True)
class TrajectoryCase:
    case_id: str
    category: str
    domain: str
    tools: tuple[dict, ...]        # catalog entries: name/description/fields
    calls: tuple[CallEvent, ...]
    results: tuple[ResultEvent, ...]
    oracle_contracts: dict | None = None   # contract per tool name (ORACLE track)
