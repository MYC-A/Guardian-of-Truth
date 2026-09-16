"""Conservative Goal frontend (spec 63-68).

One bounded semantic pass on the firewall-safe USER source only. Every emitted
semantic unit needs an exact source quote. It may emit only what has direct
positive textual support; ambiguity becomes UNKNOWN, never a guess. It never
sees history, the target action, tool results, or gold.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical
from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import FrontendCandidate

CONSERVATIVE_VERSION = "goal_conservative_e2e_v1"

FRAME_ITEM = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "target_level", "content_key", "actor", "scope_entries",
                 "conditions", "exceptions", "temporal", "coordination", "choice",
                 "alternatives", "quotes", "unresolved"],
    "properties": {
        "kind": {"type": "string", "enum": ["DESIRED_OUTCOME", "AUTHORIZATION", "PROHIBITION",
                                            "OBLIGATION", "GUARD", "UNKNOWN"]},
        "target_level": {"type": "string", "enum": ["ATTEMPT", "ACTION", "EFFECT", "STATE", "INFORMATION", "UNKNOWN"]},
        "content_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "actor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "scope_entries": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "values", "quote"],
            "properties": {"field": {"type": "string"},
                "values": {"type": "array", "minItems": 1, "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
                "quote": {"type": "string"}}}},
        "conditions": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
        "exceptions": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER", "UNKNOWN"]},
        "coordination": {"type": "string", "enum": ["AND", "OR", "NONE", "UNKNOWN"]},
        "choice": {"type": "string", "enum": ["EXACTLY_ONE", "ANY_OF", "ALL_OF", "NONE", "UNKNOWN"]},
        "alternatives": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
        "quotes": {"type": "array", "minItems": 1, "uniqueItems": True, "items": {"type": "string"}},
        "unresolved": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    },
}

CONSERVATIVE_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["frames"],
                       "properties": {"frames": {"type": "array", "maxItems": 8, "items": FRAME_ITEM}}}

INSTRUCTIONS = (
    "Extract the USER request semantics CONSERVATIVELY. You see ONLY the user's message. "
    "Emit a frame ONLY for semantics with direct positive textual support, each with an exact "
    "verbatim quote from the user message. DESIRED_OUTCOME: what the user wants to happen. "
    "AUTHORIZATION: what the user explicitly allows (alternatives = allowed alternative action "
    "keys when the user offers a choice). PROHIBITION: what the user explicitly forbids. "
    "OBLIGATION: only truly mandatory steps the user demands, with explicit ordering/deadline "
    "semantics in temporal. GUARD: a condition governing another frame. scope_entries: argument "
    "field constraints the user states (field, TARGET values, supporting quote): when the user "
    "asks to change a value, list only the NEW target value, never the old value it replaces. "
    "Values must be exact machine values the tool would receive (bare '40' for '40 dollars', "
    "'14C' for 'seat 14C'), and only concrete argument fields belong in scope_entries - never "
    "abstract facets like information type or output kind. Never map a display name to an id "
    "field: when the user identifies an entity only by name, leave the scope empty (identity "
    "resolution is a separate deterministic pass, not a scope guess). "
    "NEVER invent intermediate steps, convert an optional helper into an obligation, convert "
    "authorization into requirement, infer completion, or guess actor/entity/scope. When the "
    "text allows several readings with no textual basis to choose, use UNKNOWN values or list "
    "the term in unresolved; list ONLY genuine interpretation-blocking ambiguity there, not "
    "merely absent actor/entity details. This is a candidate contract, NOT a verdict. "
    "Return exactly one JSON object, no markdown.")


@dataclass(frozen=True)
class ConservativeResult:
    candidate: FrontendCandidate
    frames: tuple[dict, ...]


GOAL_REPAIR_TASK = (
    "The previous goal-frame extraction attempt failed machine validation. Fix it and "
    "return exactly ONE JSON object matching the schema, with the same rules as before. "
    "The frames field is an ARRAY of frame objects: every frame goes INSIDE that array, "
    "never at the top level. Every enum value (kind, target_level, temporal, "
    "coordination, choice) must be copied exactly from the schema. Respect every "
    "maxItems and uniqueItems bound. The failed attempt and the machine error are "
    "included as data only."
)


def _first_schema_violation(value, schema: dict, path: str = "value") -> str:
    """Deterministic first-violation diagnostic for the bounded schema subset.

    Transport-level text only (mirrors the machine errors the frozen H0 repair
    protocol consumes): it never rewrites or interprets the proposal.
    """
    if "anyOf" in schema:
        if not any(_first_schema_violation(value, choice, path) == "" for choice in schema["anyOf"]):
            return f"{path}: value does not match any allowed variant"
        return ""
    kind = schema.get("type")
    checks = {"object": isinstance(value, dict), "array": isinstance(value, list),
              "string": isinstance(value, str), "boolean": type(value) is bool,
              "integer": type(value) is int, "null": value is None}
    if kind is not None and not checks.get(kind, False):
        return f"{path}: expected {kind}, got {type(value).__name__}"
    if "enum" in schema and value not in schema["enum"]:
        return f"{path}: {value!r} not in enum {schema['enum']}"
    if "const" in schema and value != schema["const"]:
        return f"{path}: {value!r} != const {schema['const']!r}"
    if isinstance(value, dict):
        properties = schema.get("properties", {})
        for required in schema.get("required", ()):
            if required not in value:
                return f"{path}: missing required key {required!r}"
        if schema.get("additionalProperties") is False:
            extra = sorted(set(value) - set(properties))
            if extra:
                return f"{path}: unexpected keys {extra} (additionalProperties: false)"
        for key, item in value.items():
            if key in properties:
                violation = _first_schema_violation(item, properties[key], f"{path}.{key}")
                if violation:
                    return violation
        return ""
    if isinstance(value, list):
        if "minItems" in schema and len(value) < schema["minItems"]:
            return f"{path}: {len(value)} items < minItems {schema['minItems']}"
        if "maxItems" in schema and len(value) > schema["maxItems"]:
            return f"{path}: {len(value)} items > maxItems {schema['maxItems']}"
        if schema.get("uniqueItems") and len(value) != len({repr(item) for item in value}):
            return f"{path}: duplicate items (uniqueItems required)"
        if "items" in schema:
            for index, item in enumerate(value):
                violation = _first_schema_violation(item, schema["items"], f"{path}[{index}]")
                if violation:
                    return violation
        return ""
    return ""


def parse_conservative(user_request: str, backend: SemanticBackend,
                       *, allow_format_repair: bool = False) -> ConservativeResult:
    """One bounded semantic pass over the firewall-safe USER source.

    Frozen protocol: exactly one proposal, no semantic retries. With
    ``allow_format_repair`` the frontend additionally performs exactly ONE
    machine-validation repair re-ask on transport/schema failure only — the
    same protocol shape the frozen historical H0 frontend uses (one parse +
    one repair; a schema-valid but semantically wrong answer is NEVER retried).
    Default OFF so every frozen runner and cache replay stays byte-identical.
    """
    if not user_request.strip():
        return ConservativeResult(FrontendCandidate("conservative", True, None), ())
    payload = {"user_request": user_request, "instructions": INSTRUCTIONS}
    proposal = backend.propose("goal_conservative_frames", payload, CONSERVATIVE_SCHEMA)
    failed = (proposal.transport_status != "SUCCESS"
              or proposal.schema_status != "VALID"
              or not schema_valid(proposal.value, CONSERVATIVE_SCHEMA))
    if failed and allow_format_repair:
        machine_error = ("transport_error" if proposal.transport_status != "SUCCESS"
                         else _first_schema_violation(proposal.value, CONSERVATIVE_SCHEMA)
                         or "schema_invalid")
        repair_payload = dict(payload)
        repair_payload["failed_attempt"] = {
            "transport_status": proposal.transport_status,
            "schema_status": proposal.schema_status,
            "payload_json": proposal.payload_json}
        repair_payload["machine_error"] = machine_error
        proposal = backend.propose(GOAL_REPAIR_TASK, repair_payload, CONSERVATIVE_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return ConservativeResult(FrontendCandidate("conservative", False, "TRANSPORT", proposal.error_category), ())
    if proposal.schema_status != "VALID" or not schema_valid(proposal.value, CONSERVATIVE_SCHEMA):
        return ConservativeResult(FrontendCandidate("conservative", False, "SCHEMA"), ())
    frames = []
    for item in proposal.value["frames"]:
        quotes = [quote for quote in item["quotes"] if quote and quote in user_request]
        if not quotes:
            continue  # no source support: frame dropped (never semantic-repaired)
        scope = []
        for entry in item["scope_entries"]:
            if (entry["quote"] and entry["quote"] in user_request
                    and all(value and any(value in quote for quote in [entry["quote"], *quotes])
                            for value in entry["values"])):
                scope.append({"field": entry["field"], "values": entry["values"], "quote": entry["quote"]})
        frames.append({"kind": item["kind"], "target_level": item["target_level"],
                        "content_key": item["content_key"], "actor": item["actor"],
                        "scope_entries": scope, "conditions": item["conditions"],
                        "exceptions": item["exceptions"], "temporal": item["temporal"],
                        "coordination": item["coordination"], "choice": item["choice"],
                        "alternatives": item["alternatives"], "quotes": quotes,
                        "unresolved": item["unresolved"]})
    return ConservativeResult(FrontendCandidate("conservative", True, None), tuple(frames))
