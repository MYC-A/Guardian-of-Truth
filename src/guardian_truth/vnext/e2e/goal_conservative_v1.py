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


def parse_conservative(user_request: str, backend: SemanticBackend) -> ConservativeResult:
    if not user_request.strip():
        return ConservativeResult(FrontendCandidate("conservative", True, None), ())
    payload = {"user_request": user_request, "instructions": INSTRUCTIONS}
    proposal = backend.propose("goal_conservative_frames", payload, CONSERVATIVE_SCHEMA)
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
