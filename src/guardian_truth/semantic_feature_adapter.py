"""Controlled adapter from the underspecified prototype to metamorphic features.

This is deliberately an experiment adapter, not a production semantic parser.
It exposes normalized observations from the construction registry so that the
independent metamorphic suite can falsify insensitive or forced bindings.
"""

import re
from typing import Any, Mapping

from .underspecified_semantics import analyze_rule


_NUMBER_WORDS = {
    "zero": 0, "one": 1, "two": 2, "three": 3, "four": 4, "five": 5,
    "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
}


def _first_alternative(analysis, kind: str):
    item = next((item for item in analysis.obligations if item.kind == kind), None)
    return item.alternatives[0] if item else None


def _event_view(analysis):
    event = next((item for item in analysis.concepts
                  if item.kind in {"EVENT", "EVENT_TIME"}), None)
    if event is None:
        return None, None
    role = dict(event.roles).get("role")
    if event.binding_status == "UNBOUND_CONCEPT":
        binding = "UNBOUND_CONCEPT"
    elif len(event.binding_options) == 1:
        binding = event.binding_options[0]
    elif event.binding_options:
        binding = "UNRESOLVED"
    else:
        binding = None
    return role, binding


def _entity_reference(text: str):
    entities = re.findall(r"\b(?:Account|Booking|Flight)\s+[A-Z0-9]+\b", text)
    pronoun = bool(re.search(r"\b(?:it|its|they|their)\b", text, re.I))
    if not pronoun:
        binding = entities[-1] if entities else None
        return "EXPLICIT", binding
    unique = tuple(dict.fromkeys(entities))
    return "PRONOUN", unique[0] if len(unique) == 1 else "UNRESOLVED"


def _voice_roles(text: str):
    active = re.search(r"\bthe\s+agent\s+must\s+(cancel)\s+(.+?)(?:\.|$)", text, re.I)
    if active:
        return "Cancel", "Agent", active.group(2).strip()
    passive = re.search(r"\b(.+?)\s+must\s+be\s+(cancelled|canceled)\s+by\s+the\s+agent\b",
                        text, re.I)
    if passive:
        return "Cancel", "Agent", passive.group(1).strip()
    return None, None, None


def _latest_state(trace, entity: str | None):
    matching = [item for item in trace if isinstance(item, Mapping)
                and (entity is None or item.get("entity") == entity)
                and isinstance(item.get("sequence"), (int, float))]
    if not matching:
        return None
    return max(matching, key=lambda item: item["sequence"]).get("status")


def semantic_feature_view(payload: dict[str, Any]) -> dict[str, dict[str, Any]]:
    """Return a normalized feature view without receiving expected answers."""
    if not isinstance(payload, dict) or set(payload) != {"text", "schema", "trace"}:
        raise ValueError("Expected text/schema/trace only")
    text = payload["text"]
    schema = payload["schema"]
    trace = payload["trace"]
    if not isinstance(text, str) or not isinstance(schema, (tuple, list)):
        raise ValueError("Malformed semantic input")
    schema_fields = tuple(item["field"] for item in schema
                          if isinstance(item, Mapping) and isinstance(item.get("field"), str))
    analysis = analyze_rule(text, schema_fields=schema_fields)
    role, binding = _event_view(analysis)
    temporal = _first_alternative(analysis, "TEMPORAL_RELATION")
    comparison = _first_alternative(analysis, "COMPARISON")
    if comparison is None and temporal in {"GT", "GE"}:
        comparison = temporal
    direction = _first_alternative(analysis, "CONDITION_DIRECTION")
    direction = {"IF": "SUFFICIENT", "ONLY_IF": "NECESSARY", "IFF": "BICONDITIONAL"}.get(
        direction, direction)
    reference_form, entity_binding = _entity_reference(text)
    action, agent, patient = _voice_roles(text)
    threshold_match = re.search(
        r"\b(?:at\s+most|less\s+than|at\s+least)\s+(\d+|zero|one|two|three|four|five|six|seven|eight|nine|ten)\b",
        text, re.I)
    threshold = None
    if threshold_match:
        raw = threshold_match.group(1).lower()
        threshold = int(raw) if raw.isdigit() else _NUMBER_WORDS[raw]
    state_entity = next(iter(re.findall(r"\bAccount\s+[A-Z0-9]+\b", text)), None)
    features = {
        "event_role": role,
        "field_binding": binding,
        "temporal_operator": temporal,
        "comparison": comparison,
        "allows_equality": comparison in {"GE", "LE"} if comparison else None,
        "threshold": threshold,
        "modality": _first_alternative(analysis, "MODALITY"),
        "quantifier": _first_alternative(analysis, "QUANTIFIER"),
        "condition_direction": direction,
        "condition_operator": _first_alternative(analysis, "CONNECTIVE"),
        "exception_present": any(item.kind == "EXCEPTION" for item in analysis.obligations),
        "reference_form": reference_form,
        "entity_binding": entity_binding,
        "action": action,
        "agent": agent,
        "patient": patient,
        "current_state": _latest_state(trace, state_entity),
        "state_entity": state_entity,
    }
    return {"features": features}
