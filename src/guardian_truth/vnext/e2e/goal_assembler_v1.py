"""Trusted deterministic Goal assembler (spec sections 76-77).

The assembler owns: canonical IDs, frame IDs, stable ordering, arity,
canonical records, schema validation, referential integrity, exact duplicate
removal and source-reference verification (via E5).

The assembler has NO authority to: must -> REQUIRE, may -> AUTHORIZATION,
unless -> EXCEPTION, guess actor, guess scope, guess root, nearest
attachment, delete invented conditions, authorization -> obligation,
prohibition -> negative obligation.  Frames whose semantic decision cannot be
validated are REJECTed (recorded with a reason) or keep explicit UNKNOWN
fields — never repaired.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from .goal_e5_v1 import resolve_ref
from .goal_types_v1 import (E5Resolution, ExtractiveRef, FrameKind, GoalContract,
                            GoalFrame, GroundedProposition, RuleFrameRaw, SourceText,
                            TargetLevel)

_FRAME_KINDS = {kind.value for kind in FrameKind}
_TARGET_LEVELS = {level.value for level in TargetLevel}
_VALID_TEMPORAL = {"NONE", "BEFORE", "AFTER"}
_VALID_COORDINATION = {"AND", "OR", "NONE"}
_VALID_CHOICE = {"EXACTLY_ONE", "ANY_OF", "ALL_OF", "NONE"}

# Mandatory grounded fields per frame kind (spec sections 57-62, 70).
_MANDATORY = {
    FrameKind.DESIRED_OUTCOME: ("content",),
    FrameKind.AUTHORIZATION: ("content", "alternatives"),
    FrameKind.PROHIBITION: ("content",),
    FrameKind.OBLIGATION: ("content",),
    FrameKind.GUARD: ("content",),
}


def _grounded(text_hint: str, ref: ExtractiveRef | None, sources) -> tuple[GroundedProposition | None, E5Resolution | None]:
    if ref is None:
        return None, None
    result = resolve_ref(ref, sources)
    if not result.ok:
        return None, result.resolution
    from .goal_e5_v1 import proposition_from_ref
    return proposition_from_ref(text_hint or ref.quote, result), result.resolution


def assemble_contract(frontend: str, raw_frames: tuple[RuleFrameRaw, ...],
                      sources: dict[str, SourceText], *, contract_id: str | None = None) -> GoalContract:
    """Assemble canonical frames from raw LLM proposals.  Deterministic,
    reject-only: every semantic decision comes verbatim from the proposal with
    a resolved source anchor; nothing is invented, rewritten or repaired."""
    contract_id = contract_id or ("goal:" + frontend)
    frames: list[GoalFrame] = []
    rejected: list[tuple[str, str]] = []
    unresolved_fields: list[str] = []

    for raw in sorted(raw_frames, key=lambda item: item.frame_id_local):
        # --- kind ---
        if raw.kind not in _FRAME_KINDS or raw.kind == "UNKNOWN":
            rejected.append((raw.frame_id_local, "UNKNOWN_OR_INVALID_KIND"))
            continue
        kind = FrameKind(raw.kind)

        # --- mandatory grounded semantic fields (E5-anchored, verbatim) ---
        content, content_res = _grounded("", raw.content, sources)
        if content is None:
            rejected.append((raw.frame_id_local,
                             "CONTENT_" + (content_res.value if content_res else "ABSENT")))
            continue
        bearer, _ = _grounded("", raw.bearer, sources)
        entity, entity_res = _grounded("", raw.entity, sources)
        if raw.entity is not None and entity is None:
            # The proposal attached an entity we cannot ground: keep frame
            # with entity UNKNOWN, never nearest-span repair (section 77).
            unresolved_fields.append(f"{raw.frame_id_local}:entity")

        alternatives = []
        for alternative in raw.alternatives:
            grounded, res = _grounded("", alternative, sources)
            if grounded is None:
                unresolved_fields.append(f"{raw.frame_id_local}:alternative")
                continue
            alternatives.append(grounded)
        alternatives = tuple(dict.fromkeys(alternatives))
        if kind is FrameKind.AUTHORIZATION and not alternatives:
            rejected.append((raw.frame_id_local, "AUTHORIZATION_WITHOUT_RESOLVED_ALTERNATIVES"))
            continue

        conditions, exceptions = [], []
        for label, refs, bucket in (("condition", raw.conditions, conditions),
                                    ("exception", raw.exceptions, exceptions)):
            for ref in refs:
                grounded, res = _grounded("", ref, sources)
                if grounded is None:
                    if res is E5Resolution.AMBIGUOUS:
                        # A genuinely ambiguous condition/exception reference is
                        # decisive for applicability: reject the frame.
                        rejected.append((raw.frame_id_local, f"{label.upper()}_AMBIGUOUS_REF"))
                        bucket.clear()
                        break
                    unresolved_fields.append(f"{raw.frame_id_local}:{label}")
                    continue
                bucket.append(grounded)
            if bucket is conditions and not conditions and raw.conditions:
                break
        if not conditions and raw.conditions:
            # every condition reference failed to ground
            if raw.frame_id_local not in [item[0] for item in rejected]:
                rejected.append((raw.frame_id_local, "CONDITIONS_UNGROUNDABLE"))
            continue
        if not exceptions and raw.exceptions:
            # exception refs failed to ground: the frame loses its carve-out.
            # Dropping a carve-out would CHANGE semantics: reject the frame.
            rejected.append((raw.frame_id_local, "EXCEPTIONS_UNGROUNDABLE"))
            continue

        # --- temporal ---
        temporal_event = None
        temporal = raw.temporal if raw.temporal in _VALID_TEMPORAL else "UNKNOWN"
        if temporal == "UNKNOWN":
            unresolved_fields.append(f"{raw.frame_id_local}:temporal")
            temporal = "NONE"
        if temporal in {"BEFORE", "AFTER"}:
            grounded, res = _grounded("", raw.temporal_event, sources)
            if grounded is None:
                rejected.append((raw.frame_id_local, "TEMPORAL_EVENT_UNGROUNDABLE"))
                continue
            temporal_event = grounded

        # --- carried enum fields ---
        coordination = raw.coordination if raw.coordination in _VALID_COORDINATION else "NONE"
        choice = raw.choice if raw.choice in _VALID_CHOICE else "UNKNOWN"
        if choice == "UNKNOWN":
            unresolved_fields.append(f"{raw.frame_id_local}:choice")
            choice = "NONE"
        target_level = raw.target_level if raw.target_level in _TARGET_LEVELS else "UNKNOWN"
        if target_level == "UNKNOWN":
            unresolved_fields.append(f"{raw.frame_id_local}:target_level")
            target_level = TargetLevel.UNKNOWN
        else:
            target_level = TargetLevel(target_level)

        support = tuple(dict.fromkeys(filter(None, (
            content.anchor, bearer.anchor if bearer else None,
            entity.anchor if entity else None, temporal_event.anchor if temporal_event else None,
            *(item.anchor for item in conditions), *(item.anchor for item in exceptions),
            *(item.anchor for item in alternatives)))))

        frame = GoalFrame(
            frame_id=f"{contract_id}:f{len(frames)}",
            frontend=frontend, kind=kind, content=content, bearer=bearer, entity=entity,
            conditions=tuple(conditions), exceptions=tuple(exceptions),
            alternatives=alternatives, temporal=temporal, temporal_event=temporal_event,
            coordination=coordination, choice=choice, target_level=target_level,
            source_support=support)
        frames.append(frame)

    # Exact duplicate removal: identical canonical frames collapse (section 76).
    seen, deduped = set(), []
    for frame in frames:
        key = (frame.kind, frame.content, frame.bearer, frame.entity, frame.conditions,
               frame.exceptions, frame.alternatives, frame.temporal, frame.temporal_event,
               frame.coordination, frame.choice, frame.target_level)
        if key not in seen:
            seen.add(key)
            deduped.append(frame)
    return GoalContract(contract_id, frontend, tuple(sorted(sources)), tuple(deduped),
                        tuple(rejected), tuple(dict.fromkeys(unresolved_fields)))
