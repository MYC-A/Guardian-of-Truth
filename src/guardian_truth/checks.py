"""Checks whose evidence is inspectable. No dataset IDs or label-based routing."""

import json
import re

from .types import Catalog, Event, FieldSpec, Finding, Source


ONE_CALL = re.compile(
    r"\b(?:you\s+)?(?:should|must)\s+(?:only\s+make|at\s+most\s+make)\s+one\s+"
    r"tool\s+call\s+at\s+a\s+time\b",
                      re.IGNORECASE)
EXCLUSIVE_ACTION = re.compile(
    r"\b(?:either|can\s+either)\b[\s\S]{0,240}\bsend\s+a\s+message\b"
    r"[\s\S]{0,240}\bmake\s+a\s+tool\s+call\b[\s\S]{0,160}"
    r"\bcannot\s+do\s+both\b", re.IGNORECASE)


def _system_rule(history, pattern):
    """Return the exact first authoritative rule span, never user text."""
    for event in history:
        if event.role != "system":
            continue
        match = pattern.search(event.text)
        if match:
            return Source(event.source.document,
                          event.source.start + match.start(),
                          event.source.start + match.end())
    return None


def check_turn_structure(history: list[Event], candidate: list[Event],
                         enabled: frozenset[str]):
    """Enforce explicit per-turn action cardinality from system policy.

    Multiple calls are not intrinsically erroneous.  This check fires only when
    an authoritative system event contains a narrowly parsed prohibition.
    """
    if "schema" not in enabled:
        return []
    calls = [event for event in candidate
             if event.role == "assistant" and event.kind == "call"]
    texts = [event for event in candidate
             if event.role == "assistant" and event.kind == "text" and event.text.strip()]
    findings = []
    one_call = _system_rule(history, ONE_CALL)
    if one_call is not None and len(calls) > 1:
        findings.append(Finding(
            "multiple_tool_calls_in_turn",
            "The system policy permits only one tool call in this turn.",
            [one_call, *(event.source for event in calls)],
        ))
    exclusive = _system_rule(history, EXCLUSIVE_ACTION)
    if exclusive is not None and calls and texts:
        findings.append(Finding(
            "mixed_text_and_tool_call",
            "The system policy forbids combining a user message and a tool call in one turn.",
            [exclusive, *(event.source for event in texts),
             *(event.source for event in calls)],
        ))
    return findings


def type_matches(value, kind):
    return {
        "string": isinstance(value, str),
        "integer": type(value) is int,
        "number": type(value) in (int, float),
        "boolean": type(value) is bool,
        "array": isinstance(value, list),
        "object": isinstance(value, dict),
    }[kind]


def enum_matches(value, choices):
    if isinstance(value, str):
        return value in choices
    for choice in choices:
        try:
            expected = json.loads(choice)
        except (ValueError, TypeError):
            continue
        # JSON booleans must not compare equal to numeric 0/1.
        if isinstance(value, bool) != isinstance(expected, bool):
            continue
        if value == expected:
            return True
    return False


def validate_fields(value: dict, fields: list[FieldSpec], call: Event, prefix="$") -> list[Finding]:
    findings = []
    for field in fields:
        path = prefix + '.' + field.name
        refs = [call.source, field.source]
        if field.name not in value:
            if field.required:
                findings.append(Finding("missing_argument", f"Отсутствует обязательное поле {path}", refs))
            continue
        actual = value[field.name]
        if not type_matches(actual, field.kind):
            findings.append(Finding("argument_type", f"{path}: ожидается {field.kind}", refs))
            continue
        if field.enum and not enum_matches(actual, field.enum):
            findings.append(Finding("argument_enum", f"{path}: значение вне перечисленных вариантов", refs))
        if field.children:
            if isinstance(actual, dict):
                findings.extend(validate_fields(actual, field.children, call, path))
            elif isinstance(actual, list):
                for index, item in enumerate(actual):
                    if not isinstance(item, dict):
                        findings.append(Finding("argument_type", f"{path}[{index}]: ожидается объект", refs))
                    else:
                        findings.extend(validate_fields(item, field.children, call, f"{path}[{index}]"))
    # Extra keys are NOT forbidden unless the schema explicitly says so.
    return findings


def check_calls(events: list[Event], catalog: Catalog, enabled: frozenset[str]):
    findings, unresolved = [], []
    for event in events:
        if event.kind != "call" or event.role != "assistant": continue
        tool = catalog.tools.get(event.name)
        if tool is None:
            if catalog.complete and 'availability' in enabled:
                findings.append(Finding("unavailable_tool", f"Инструмент {event.name} отсутствует в объявленном списке",
                                        [event.source, catalog.source]))
            else:
                unresolved.append("tool_availability_unknown")
            continue
        if 'schema' not in enabled: continue
        if not event.json_valid:
            # Formatting alone need not affect the evaluated outcome.
            unresolved.append("call_arguments_unparsed")
        elif not isinstance(event.value, dict):
            findings.append(Finding("arguments_not_object", "Аргументы вызова должны быть объектом",
                                    [event.source, tool.source]))
        elif not tool.schema_understood:
            unresolved.append("tool_schema_not_fully_understood")
        else:
            findings.extend(validate_fields(event.value, tool.fields, event))
    return findings, unresolved
