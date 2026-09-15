"""Rule Frames goal frontend (spec 69-73) + trusted deterministic assembler
(spec 76, 77) with E5 reference resolution.

The LLM decides ONLY semantic questions (kind, content, actor, scope, guards,
conditions, temporal, coordination, choice, target level) and emits
source-linked parts as ExtractiveRefs (start/end/quote). It never generates
canonical IDs, cross-frame foreign keys or final AST serializations. E5
resolves every reference deterministically; the assembler assigns canonical
frame IDs, stable ordering, arity and referential integrity, and performs NO
semantic repair (must/may/unless keyword rewriting, actor/scope guessing and
nearest attachment are forbidden - ambiguous or unresolvable fields become
UNKNOWN or the frame is rejected).
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical
from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import ExtractiveRef, FrontendCandidate, GoalContract, GoalFrame, ScopeEntry
from .goal_e5_v1 import E5Status, resolve_ref
from .policy_composition_v1 import _key_from

RULE_FRAMES_VERSION = "goal_rule_frames_e2e_v1"
ASSEMBLER_VERSION = "goal_assembler_e2e_v1"

REF_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["start", "end", "quote"],
              "properties": {"start": {"type": "integer", "minimum": 0},
                             "end": {"type": "integer", "minimum": 1},
                             "quote": {"type": "string"}}}

FRAME_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["kind", "target_level", "content_key", "actor_ref", "entity_ref", "content_ref",
                 "scope_entries", "conditions", "exceptions", "temporal", "coordination",
                 "choice", "alternatives", "support", "unresolved_fields"],
    "properties": {
        "kind": {"type": "string", "enum": ["DESIRED_OUTCOME", "AUTHORIZATION", "PROHIBITION",
                                            "OBLIGATION", "GUARD", "UNKNOWN"]},
        "target_level": {"type": "string", "enum": ["ATTEMPT", "ACTION", "EFFECT", "STATE", "INFORMATION", "UNKNOWN"]},
        "content_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "actor_ref": {"anyOf": [REF_SCHEMA, {"type": "null"}]},
        "entity_ref": {"anyOf": [REF_SCHEMA, {"type": "null"}]},
        "content_ref": REF_SCHEMA,
        "scope_entries": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False, "required": ["field", "values", "ref"],
            "properties": {"field": {"type": "string"},
                "values": {"type": "array", "minItems": 1, "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
                "ref": REF_SCHEMA}}},
        "conditions": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "ref"],
            "properties": {"key": {"type": "string"}, "ref": REF_SCHEMA}}},
        "exceptions": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {
            "type": "object", "additionalProperties": False, "required": ["key", "ref"],
            "properties": {"key": {"type": "string"}, "ref": REF_SCHEMA}}},
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER", "UNKNOWN"]},
        "coordination": {"type": "string", "enum": ["AND", "OR", "NONE", "UNKNOWN"]},
        "choice": {"type": "string", "enum": ["EXACTLY_ONE", "ANY_OF", "ALL_OF", "NONE", "UNKNOWN"]},
        "alternatives": {"type": "array", "maxItems": 4, "uniqueItems": True, "items": {"type": "string"}},
        "support": {"type": "array", "minItems": 1, "maxItems": 8, "uniqueItems": True, "items": REF_SCHEMA},
        "unresolved_fields": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    },
}

RF_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["frames"],
             "properties": {"frames": {"type": "array", "maxItems": 8, "items": FRAME_SCHEMA}}}

INSTRUCTIONS = (
    "Parse the USER request into source-linked rule frames. You see ONLY the user's message. "
    "For every semantic part emit an ExtractiveRef: {start, end, quote} where quote is the exact "
    "substring of the user message and start/end are its character offsets (offsets may be "
    "re-resolved deterministically; the quote must be exact). Frame kinds: DESIRED_OUTCOME, "
    "AUTHORIZATION, PROHIBITION, OBLIGATION, GUARD. You decide kind, content, actor, entity, "
    "scope argument constraints (field + exact machine values + supporting ref; only concrete "
    "argument fields, never abstract facets like information type; bare '40' for '40 dollars'; "
    "never map a display name to an id field - when the user identifies an entity only by name, "
    "leave the scope empty because identity resolution is a separate deterministic pass), "
    "conditions, exceptions, "
    "temporal relation, coordination and choice. content_key: snake_case semantic key. "
    "alternatives: allowed alternative action keys for AUTHORIZATION choices. Do NOT invent "
    "IDs, do NOT infer completion, do NOT convert authorization into obligation. Ambiguous "
    "parts go to unresolved_fields. This is a candidate contract, NOT a verdict. "
    "Return exactly one JSON object, no markdown.")


@dataclass(frozen=True)
class RuleFramesResult:
    candidate: FrontendCandidate
    frames: tuple[GoalFrame, ...]
    rejected: tuple[str, ...]


def _resolved_ref(user_request: str, ref):
    if not isinstance(ref, dict):
        return None
    resolution = resolve_ref(user_request, ref)
    if resolution.status in {E5Status.RESOLVED_EXACT, E5Status.RESOLVED_UNIQUE_QUOTE}:
        return ExtractiveRef("user_request", resolution.start, resolution.end, resolution.quote)
    return None


def parse_rule_frames(user_request: str, backend: SemanticBackend) -> RuleFramesResult:
    if not user_request.strip():
        return RuleFramesResult(FrontendCandidate("rule_frames", True, None), (), ())
    payload = {"user_request": user_request, "instructions": INSTRUCTIONS}
    proposal = backend.propose("goal_rule_frames", payload, RF_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return RuleFramesResult(FrontendCandidate("rule_frames", False, "TRANSPORT", proposal.error_category), (), ())
    if proposal.schema_status != "VALID" or not schema_valid(proposal.value, RF_SCHEMA):
        return RuleFramesResult(FrontendCandidate("rule_frames", False, "SCHEMA"), (), ())
    frames, rejected = [], []
    for item in proposal.value["frames"]:
        frame, reason = assemble_frame(item, user_request)
        if frame is None:
            rejected.append(reason or "REJECT_FRAME")
        else:
            frames.append(frame)
    frames = tuple(sorted(frames, key=lambda frame: canonical(_frame_row(frame)).decode("utf-8")))
    frames = _dedupe(frames)
    return RuleFramesResult(FrontendCandidate("rule_frames", True, None), frames, tuple(rejected))


def assemble_frame(item: dict, user_request: str):
    """Deterministic assembler for ONE frame: E5 resolution, arity, canonical
    fields. No semantic repair; ambiguous/unresolvable fields become UNKNOWN."""
    support = tuple(ref for ref in (_resolved_ref(user_request, r) for r in item["support"]) if ref)
    if not support:
        return None, "REJECT_FRAME:no_resolved_support"
    content_ref = _resolved_ref(user_request, item["content_ref"])
    if content_ref is None or not item["content_key"]:
        return None, "REJECT_FRAME:unresolved_content"
    actor = None
    if item["actor_ref"]:
        actor_ref = _resolved_ref(user_request, item["actor_ref"])
        actor = "assistant" if actor_ref and "assistant" in actor_ref.quote.lower() else (
            "user" if actor_ref and any(word in actor_ref.quote.lower() for word in ("i ", "my", "me")) else None)
    entity_key = None
    if item["entity_ref"]:
        entity_ref = _resolved_ref(user_request, item["entity_ref"])
        entity_key = entity_ref.quote if entity_ref else None
    scope = []
    for entry in item["scope_entries"]:
        ref = _resolved_ref(user_request, entry["ref"])
        if ref is None or not entry["field"]:
            continue
        values = [value for value in entry["values"] if value and value in ref.quote]
        if values:
            scope.append(ScopeEntry(entry["field"], tuple(values), ref))
    conditions = tuple(cond["key"] for cond in item["conditions"]
                       if cond.get("key") and _resolved_ref(user_request, cond.get("ref")))
    exceptions = tuple(exc["key"] for exc in item["exceptions"]
                       if exc.get("key") and _resolved_ref(user_request, exc.get("ref")))
    unresolved = tuple(dict.fromkeys((*item["unresolved_fields"],
        *(["content_ref"] for _ in [0] if content_ref is None),
        *(["actor"] for _ in [0] if item["actor_ref"] and actor is None))))
    frame = GoalFrame(
        frame_kind=item["kind"], target_level=item["target_level"], actor=actor,
        content_key=item["content_key"], entity_key=entity_key, scope=tuple(scope),
        conditions=conditions, exceptions=exceptions, temporal=item["temporal"],
        coordination=item["coordination"], choice=item["choice"],
        support=support, unresolved_fields=unresolved)
    return frame, None


def _derived_key(frame: GoalFrame) -> str:
    """Deterministic frame key for canonical equivalence: derived from the
    PRIMARY SUPPORT QUOTE (fixed by the source text), not from the model's
    free-form content_key. Two frontends agreeing on kind/scope/support are
    the same admissible reading even when their binding hints differ; the
    hint is resolved deterministically in PASS 2."""
    if frame.support:
        quote = frame.support[0].quote
        if frame.content_key and frame.content_key in quote:
            return _key_from(quote, frame.content_key)
        return _key_from(quote, None)
    return frame.content_key or "unknown"


def _frame_row(frame: GoalFrame) -> dict:
    return {"kind": frame.frame_kind, "content_key": _derived_key(frame), "target_level": frame.target_level,
            "actor": frame.actor, "entity": frame.entity_key,
            "scope": [[entry.field, list(entry.values)] for entry in frame.scope],
            "conditions": list(frame.conditions), "exceptions": list(frame.exceptions),
            "temporal": frame.temporal, "coordination": frame.coordination, "choice": frame.choice,
            "support": [ref.quote for ref in frame.support],
            "alternatives": list(frame.alternatives),
            "unresolved": list(frame.unresolved_fields)}


def _dedupe(frames: tuple[GoalFrame, ...]) -> tuple[GoalFrame, ...]:
    seen, kept = set(), []
    for frame in frames:
        key = canonical(_frame_row(frame)).decode("utf-8")
        if key in seen:
            continue
        seen.add(key)
        kept.append(frame)
    return tuple(kept)


def make_contract(frontend: str, frames: tuple[GoalFrame, ...], unresolved_terms: tuple[str, ...]) -> GoalContract:
    return GoalContract(f"goal:{frontend}:r0", frontend, frames, tuple(dict.fromkeys(unresolved_terms)))


def contract_canonical_key(contract: GoalContract) -> str:
    """Canonical lowering for deterministic equivalence (spec 78, 79)."""
    return canonical([_frame_row(frame) for frame in contract.frames] + sorted(contract.unresolved_terms)).decode("utf-8")


def dedupe_contracts(contracts: tuple[GoalContract, ...]) -> tuple[GoalContract, ...]:
    seen, kept = set(), []
    for contract in contracts:
        key = contract_canonical_key(contract)
        if key in seen:
            continue
        seen.add(key)
        kept.append(contract)
    return tuple(kept)


def contract_from_rows(authoritative_rows, user_request: str) -> GoalContract:
    """Oracle substitution: authoritative contract rows -> GoalContract."""
    frames = []
    rows = authoritative_rows.get("frames", authoritative_rows) if isinstance(authoritative_rows, dict) else authoritative_rows
    for i, row in enumerate(rows):
        support = tuple(ExtractiveRef("user_request", 0, len(quote), quote)
                        for quote in row.get("support", (user_request,)))
        scope = tuple(ScopeEntry(entry[0], tuple(entry[1]), None) for entry in row.get("scope", []))
        frames.append(GoalFrame(
            frame_kind=row.get("kind", "UNKNOWN"), target_level=row.get("target_level", "UNKNOWN"),
            actor=row.get("actor"), content_key=row.get("content_key"), entity_key=row.get("entity_key"),
            scope=scope, conditions=tuple(row.get("conditions", ())),
            exceptions=tuple(row.get("exceptions", ())), temporal=row.get("temporal", "NONE"),
            coordination=row.get("coordination", "NONE"), choice=row.get("choice", "NONE"),
            support=support, unresolved_fields=tuple(row.get("unresolved", ())),
            alternatives=tuple(row.get("alternatives", ()))))
    unresolved = authoritative_rows.get("unresolved", []) if isinstance(authoritative_rows, dict) else []
    return GoalContract("goal:oracle:r0", "oracle", tuple(frames), tuple(unresolved))
