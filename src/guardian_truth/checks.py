"""Checks whose evidence is inspectable. No dataset IDs or label-based routing."""

import json

from .types import Catalog, Event, FieldSpec, Finding


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
