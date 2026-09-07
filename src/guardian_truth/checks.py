"""Checks whose evidence is inspectable. No dataset IDs or label-based routing."""

import json
import re
from datetime import date

from .types import Catalog, Event, FieldSpec, Finding, Source


ONE_CALL = re.compile(
    r"\b(?:you\s+)?(?:should|must)\s+(?:only\s+make|at\s+most\s+make)\s+one\s+"
    r"tool\s+call\s+at\s+a\s+time\b",
                      re.IGNORECASE)
EXCLUSIVE_ACTION = re.compile(
    r"\b(?:either|can\s+either)\b[\s\S]{0,240}\bsend\s+a\s+message\b"
    r"[\s\S]{0,240}\bmake\s+a\s+tool\s+call\b[\s\S]{0,160}"
    r"\bcannot\s+do\s+both\b", re.IGNORECASE)
EXPIRED_CONTRACT_GATE = re.compile(
    r"\byou\s+are\s+not\s+allowed\s+to\s+lift\s+the\s+suspension\s+if\s+the\s+"
    r"line['’]s\s+contract\s+end\s+date\s+is\s+in\s+the\s+past\b",
    re.IGNORECASE,
)
CURRENT_DATE = re.compile(
    r"\bthe\s+current\s+(?:time|date)\s+is\s+(\d{4}-\d{2}-\d{2})\b",
    re.IGNORECASE,
)


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


def _authoritative_matches(history, pattern):
    return [(event, match) for event in history if event.role == "system"
            for match in pattern.finditer(event.text)]


def _iso_date(value):
    if not isinstance(value, str):
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def check_date_gated_actions(history: list[Event], candidate: list[Event],
                              enabled: frozenset[str]):
    """Enforce one narrow typed date gate from authoritative policy.

    This intentionally recognizes only an explicit system prohibition and the
    corresponding structured ``resume_line`` action. Missing/ambiguous policy,
    clock, JSON, entity binding or date data abstains. The latest same-line
    structured result wins; values for another line never unify.
    """
    if "rules" not in enabled:
        return []
    policies = _authoritative_matches(history, EXPIRED_CONTRACT_GATE)
    clocks = _authoritative_matches(history, CURRENT_DATE)
    if len(policies) != 1 or len(clocks) != 1:
        return []
    current = _iso_date(clocks[0][1].group(1))
    if current is None:
        return []
    policy_event, policy_match = policies[0]
    clock_event, clock_match = clocks[0]
    policy_source = Source(policy_event.source.document,
                           policy_event.source.start + policy_match.start(),
                           policy_event.source.start + policy_match.end())
    clock_source = Source(clock_event.source.document,
                          clock_event.source.start + clock_match.start(1),
                          clock_event.source.start + clock_match.end(1))
    findings = []
    for call in candidate:
        if (call.role != "assistant" or call.kind != "call" or call.name != "resume_line"
                or not call.json_valid or not isinstance(call.value, dict)):
            continue
        line_id = call.value.get("line_id")
        if not isinstance(line_id, str) or not line_id:
            continue
        observations = []
        for index, event in enumerate(history):
            value = event.value
            if (event.kind != "result" or not event.json_valid or not isinstance(value, dict)
                    or value.get("line_id") != line_id):
                continue
            end = _iso_date(value.get("contract_end_date"))
            if end is not None:
                observations.append((index, end, event.source))
        if not observations:
            continue
        latest_index = max(item[0] for item in observations)
        latest = [item for item in observations if item[0] == latest_index]
        if len(latest) != 1 or latest[0][1] >= current:
            continue
        findings.append(Finding(
            "date_gated_action_violation",
            "The system policy forbids resuming this line after its contract end date.",
            [policy_source, clock_source, latest[0][2], call.source],
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
