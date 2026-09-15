"""Goal frontends V1: Conservative and Rule Frames (spec sections 63-72).

Both frontends are NEW versioned implementations (HISTORICAL_SOURCE_UNAVAILABLE
per sections 176-178).  Both emit RuleFrameRaw records with ExtractiveRefs;
both feed the same E5 + trusted-assembler pipeline; the ONLY difference is
the task instruction (semantic breadth), which is exactly what the E2E arms
compare.  The firewall is structural: the request payload contains ONLY the
firewall-safe USER sources — no policy, no history, no target action, no tool
results, no gold (spec sections 55-56).

One primary semantic pass per source; exactly one pre-registered
format/transport repair re-ask when the machine validation fails; never a
semantic retry (spec section 28 / section 157).
"""
from __future__ import annotations

import json

from ..semantic import SemanticBackend, schema_valid
from .goal_assembler_v1 import assemble_contract
from .goal_types_v1 import ExtractiveRef, GoalContract, RuleFrameRaw, SourceText

# ------------------------------------------------------------------- schemas

REF_SCHEMA = {"type": "object", "additionalProperties": False,
              "required": ["source_id", "start", "end", "quote"],
              "properties": {"source_id": {"type": "string"},
                             "start": {"type": "integer"},
                             "end": {"type": "integer"},
                             "quote": {"type": "string"}}}
NULLABLE_REF = {"anyOf": [REF_SCHEMA, {"type": "null"}]}

FRAME_ITEM = {"type": "object", "additionalProperties": False,
    "required": ["frame_id_local", "kind", "content", "bearer", "entity",
                 "conditions", "exceptions", "temporal", "temporal_event",
                 "coordination", "choice", "target_level", "alternatives",
                 "unresolved_fields"],
    "properties": {
        "frame_id_local": {"type": "string"},
        "kind": {"type": "string", "enum": ["DESIRED_OUTCOME", "AUTHORIZATION",
                 "PROHIBITION", "OBLIGATION", "GUARD", "UNKNOWN"]},
        "content": NULLABLE_REF,
        "bearer": NULLABLE_REF,
        "entity": NULLABLE_REF,
        "conditions": {"type": "array", "items": REF_SCHEMA, "uniqueItems": True},
        "exceptions": {"type": "array", "items": REF_SCHEMA, "uniqueItems": True},
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER", "UNKNOWN"]},
        "temporal_event": NULLABLE_REF,
        "coordination": {"type": "string", "enum": ["AND", "OR", "NONE", "UNKNOWN"]},
        "choice": {"type": "string", "enum": ["EXACTLY_ONE", "ANY_OF", "ALL_OF", "NONE", "UNKNOWN"]},
        "target_level": {"type": "string", "enum": ["ATTEMPT", "ACTION", "EFFECT",
                         "STATE", "INFORMATION", "UNKNOWN"]},
        "alternatives": {"type": "array", "items": REF_SCHEMA, "uniqueItems": True},
        "unresolved_fields": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}}

GOAL_FRAME_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["frames"],
    "properties": {"frames": {"type": "array", "items": FRAME_ITEM,
                              "minItems": 0, "maxItems": 8, "uniqueItems": True}}}

# ------------------------------------------------------------ task prompts

_SHARED_FRAMING = (
    "You read ONE user request source (with exact character offsets over the "
    "LF-normalized text). You propose candidate GOAL frames as source-linked "
    "semantic records. You do NOT decide any verdict, do NOT bind anything to "
    "a trajectory, do NOT choose tools, and do NOT generate canonical IDs or "
    "cross-frame references. Every semantic field you emit MUST be an "
    "extractive ref: source_id, start, end and a quote copied "
    "character-for-character from that source (start/end are character "
    "offsets; end is exclusive). If you cannot ground a field, use null / "
    "empty list; if a decision is genuinely undeterminable from the text, "
    "name the field in unresolved_fields instead of guessing.\n"
    "FRAME KINDS:\n"
    "- DESIRED_OUTCOME: what the user wants to obtain or see happen.\n"
    "- AUTHORIZATION: what the user explicitly allows (allowed alternatives, "
    "never an instruction to execute them); requires content plus the "
    "explicitly allowed alternatives in the alternatives list.\n"
    "- PROHIBITION: what the user explicitly forbids; target_level says "
    "whether the ban concerns the ATTEMPT, the ACTION, the EFFECT or a STATE "
    "transition.\n"
    "- OBLIGATION: only really mandatory semantics: required prerequisite, "
    "required outcome/effect, explicit ordering, deadline.\n"
    "- GUARD: a condition governing one specific frame (a guard is NOT an "
    "automatic prerequisite).\n"
    "target_level: ATTEMPT / ACTION / EFFECT / STATE / INFORMATION.\n"
    "temporal BEFORE/AFTER only with a grounded temporal_event ref.\n"
    "choice: EXACTLY_ONE / ANY_OF / ALL_OF for alternative or joint content; "
    "coordination AND/OR for how multiple conditions combine.\n"
    "Output exactly one JSON object {\"frames\": [...]}."
)

CONSERVATIVE_TASK = (
    "CONSERVATIVE GOAL EXTRACTION. Extract ONLY what has DIRECT POSITIVE "
    "textual support in the user source.\n"
    "You may emit: explicit DESIRED_OUTCOME; explicit user PROHIBITION; "
    "explicit OBLIGATION (only truly mandatory wording: must / required / "
    "has to / before X / by deadline); explicit AUTHORIZATION (may / can / "
    "you can use A or B); explicit temporal/prerequisite relations.\n"
    "You may NOT: invent intermediate steps; convert an optional helper into "
    "an obligation; convert authorization into requirement; derive anything "
    "from silence; guess actor, entity, scope or plan order; infer "
    "completion; pick one interpretation when the text supports several "
    "(instead emit the frame with the ambiguous field in unresolved_fields, "
    "or omit the frame).\n"
    "An act that is neither requested nor forbidden is NOT a DESIRED_OUTCOME. "
    "Absence of prohibition is NOT authorization.\n" + _SHARED_FRAMING
)

RULE_FRAMES_TASK = (
    "GOAL RULE FRAMES. Represent the user source as source-linked semantic "
    "records with the full expressive frame vocabulary. You decide ONLY "
    "semantic questions: which kind each frame is; what its content, actor/"
    "bearer, entity and scope are; whether it has conditions and exceptions "
    "and where they attach; its temporal relation; AND/OR coordination and "
    "choice structure; and whether it targets an ATTEMPT, ACTION, EFFECT, "
    "STATE or INFORMATION. Preserve genuine ambiguity explicitly (unknown "
    "fields) instead of resolving it by preference. Do not merge different "
    "obligations that the text states separately; do not split one joint "
    "obligation that the text states together. Authorization alternatives "
    "stay alternatives (ANY_OF), never an instruction to execute all.\n"
    + _SHARED_FRAMING
)

REPAIR_TASK_PREFIX = (
    "The previous goal-frame attempt failed machine validation. Fix it and "
    "return exactly ONE JSON object with the same frame schema and the same "
    "rules as before. The failed attempt and the machine error are included "
    "as data only."
)


# --------------------------------------------------------------- parsing

def _frames_payload(sources: dict[str, SourceText]) -> dict:
    return {"sources": [{"source_id": source.source_id, "role": source.role,
                         "text": source.text, "length": len(source.text)}
                        for source in sorted(sources.values(), key=lambda item: item.source_id)]}


def _ref(item) -> ExtractiveRef | None:
    if not isinstance(item, dict):
        return None
    return ExtractiveRef(str(item["source_id"]), int(item["start"]), int(item["end"]),
                         str(item["quote"]))


def _raw_frames(value: dict) -> tuple[RuleFrameRaw, ...]:
    frames = []
    for item in value["frames"]:
        frames.append(RuleFrameRaw(
            frame_id_local=str(item["frame_id_local"]),
            kind=item["kind"],
            content=_ref(item["content"]), bearer=_ref(item["bearer"]),
            entity=_ref(item["entity"]),
            conditions=tuple(filter(None, (_ref(condition) for condition in item["conditions"]))),
            exceptions=tuple(filter(None, (_ref(exception) for exception in item["exceptions"]))),
            temporal=item["temporal"], temporal_event=_ref(item["temporal_event"]),
            coordination=item["coordination"], choice=item["choice"],
            target_level=item["target_level"],
            alternatives=tuple(filter(None, (_ref(alternative) for alternative in item["alternatives"]))),
            unresolved_fields=tuple(item["unresolved_fields"])))
    return tuple(frames)


def parse_goal_frames(frontend: str, task: str, sources: dict[str, SourceText],
                      backend: SemanticBackend) -> tuple[GoalContract, dict]:
    """One primary pass + one machine-validation repair re-ask (never a
    semantic retry).  Returns the assembled canonical contract plus telemetry."""
    payload = _frames_payload(sources)
    proposal = backend.propose(task, payload, GOAL_FRAME_SCHEMA)
    telemetry = {"task": task, "transport_status": proposal.transport_status,
                 "schema_status": proposal.schema_status, "repair_used": False}
    value = proposal.value if proposal.transport_status == "SUCCESS" and proposal.schema_status == "VALID" else None
    if value is None:
        repair_payload = dict(payload)
        repair_payload["failed_attempt"] = {"transport_status": proposal.transport_status,
                                            "schema_status": proposal.schema_status,
                                            "payload_json": proposal.payload_json}
        repair_payload["machine_error"] = "transport_error" if proposal.transport_status != "SUCCESS" else "schema_invalid"
        proposal = backend.propose(REPAIR_TASK_PREFIX, repair_payload, GOAL_FRAME_SCHEMA)
        telemetry.update(repair_used=True, repair_transport_status=proposal.transport_status,
                         repair_schema_status=proposal.schema_status)
        value = proposal.value if proposal.transport_status == "SUCCESS" and proposal.schema_status == "VALID" else None
    if value is None:
        # Section 34 analog: an unavailable frontend is NOT a safe verdict.
        contract = GoalContract("goal:" + frontend, frontend, tuple(sorted(sources)), (),
                                (("frontend", "TRANSPORT_OR_SCHEMA_FAILURE"),), ())
        telemetry["frames_raw"] = 0
        return contract, telemetry
    raw = _raw_frames(value)
    telemetry["frames_raw"] = len(raw)
    telemetry["frames_schema_valid"] = True
    contract = assemble_contract(frontend, raw, sources)
    telemetry["frames_kept"] = len(contract.frames)
    telemetry["frames_rejected"] = len(contract.rejected_frames)
    return contract, telemetry


def parse_goal_conservative(sources: dict[str, SourceText],
                            backend: SemanticBackend) -> tuple[GoalContract, dict]:
    return parse_goal_frames("conservative", CONSERVATIVE_TASK, sources, backend)


def parse_goal_rule_frames(sources: dict[str, SourceText],
                           backend: SemanticBackend) -> tuple[GoalContract, dict]:
    return parse_goal_frames("rule_frames", RULE_FRAMES_TASK, sources, backend)
