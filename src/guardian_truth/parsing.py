"""Lossless source references; explicit role boundaries; no eval or execution."""

import json
import math
import re

from .types import Catalog, Event, FieldSpec, Source, ToolSpec


MARKER = re.compile(
    r'^[ \t]*(?:⟦(?P<header>[^⟧\r\n]+)⟧[ \t]*|'
    r'(?P<arrow>→ TOOL_CALL|← TOOL_RESPONSE)[ \t]+(?P<tool>[\w.-]+)[ \t]*:[ \t]*)',
    re.MULTILINE,
)
TOOL = re.compile(r'^- (?P<name>[\w.-]+)\s+[—–]\s*', re.MULTILINE)
FIELD = re.compile(
    r'^(?P<indent>[ \t]+)(?:·\s*)?(?P<name>\w+):\s*'
    r'(?P<kind>string|integer|number|boolean|array|object)(?P<required>!)?'
    r'(?:\s+\[enum:\s*(?P<enum>[^\]]+)\])?(?=\s|$)'
)


def unique_object(pairs):
    value = {}
    for key, item in pairs:
        if key in value:
            raise ValueError('Duplicate JSON key')
        value[key] = item
    return value


def reject_constant(value):
    raise ValueError('Non-finite JSON number')


def finite_float(value):
    number = float(value)
    if not math.isfinite(number):
        raise ValueError('JSON number outside supported finite range')
    return number


def decode_json(text: str):
    try:
        return json.loads(text, object_pairs_hook=unique_object, parse_constant=reject_constant,
                          parse_float=finite_float), True
    except (ValueError, TypeError, RecursionError):
        return None, False


def parse_events(text: str, document: str) -> list[Event]:
    # Outer transport tags are delimiters, not changes to source offsets.
    left, right = 0, len(text)
    opening = re.match(r'\s*<(prompt|response)>', text)
    if opening:
        closing = re.search(r'</' + opening[1] + r'>\s*$', text)
        if closing:
            left, right = opening.end(), closing.start()
    markers = list(MARKER.finditer(text, left, right))
    role = "assistant" if document == "response" else "unknown"
    events = []

    def emit(start, end, event_role, kind, name=None):
        while start < end and text[start].isspace(): start += 1
        while end > start and text[end - 1].isspace(): end -= 1
        if start == end and kind == "text": return
        body = text[start:end]
        value, valid = decode_json(body)
        events.append(Event(event_role, kind, body, Source(document, start, end), name, value, valid))

    emit(left, markers[0].start() if markers else right, role, "text")
    for i, marker in enumerate(markers):
        end = markers[i + 1].start() if i + 1 < len(markers) else right
        header = marker["header"]
        name = marker["tool"]
        if header:
            tag = header.split()[0]
            if tag in ("SYSTEM", "USER", "ASSISTANT"):
                role = tag.lower()
                kind = "text"
            else:
                attr = dict(re.findall(r'(\w+)="([^"]*)"', header))
                name = attr.get("name")
                if tag in ("ASSISTANT_TOOL_CALL", "USER_TOOL_CALL"):
                    role = "assistant" if tag.startswith("ASSISTANT") else "user"
                    kind = "call"
                elif tag == "TOOL_RESULT":
                    role = attr.get("requestor", "unknown")
                    kind = "result"
                else:
                    role, kind = "unknown", "text"
        else:
            kind = "call" if marker["arrow"] == "→ TOOL_CALL" else "result"
        # For calls/results include the marker in source so tool names are cited.
        start = marker.start() if kind != "text" else marker.end()
        if kind != "text":
            body = text[marker.end():end].strip()
            value, valid = decode_json(body)
            events.append(Event(role, kind, body, Source(document, start, end), name, value, valid))
        else:
            emit(start, end, role, kind)
    return events


def parse_catalog(events: list[Event], prompt: str) -> Catalog:
    blocks = [e for e in events if e.role == "system" and '[AVAILABLE TOOLS]' in e.text]
    if len(blocks) != 1:
        return Catalog({}, None, False, ["missing_or_ambiguous_tool_catalog"])
    event = blocks[0]
    start = prompt.index('[AVAILABLE TOOLS]', event.source.start, event.source.end)
    source = Source("prompt", start, event.source.end)
    raw = prompt[start:source.end]
    definitions = list(TOOL.finditer(raw))
    issues = []
    if not definitions or '...' in raw or '…' in raw:
        issues.append("empty_or_potentially_truncated_catalog")
    # Unknown top-level list entries mean we cannot prove a tool absent.
    for line in raw.splitlines():
        if line.startswith('- ') and not TOOL.match(line):
            issues.append("unrecognized_tool_definition")
    tools = {}
    for i, definition in enumerate(definitions):
        begin = start + definition.start()
        end = start + (definitions[i + 1].start() if i + 1 < len(definitions) else len(raw))
        spec = ToolSpec(definition['name'], Source("prompt", begin, end))
        if spec.name in tools: issues.append("duplicate_tool_definition")
        stack: list[tuple[int, FieldSpec]] = []
        offset = begin
        for line in prompt[begin:end].splitlines(keepends=True):
            match = FIELD.match(line)
            if match:
                depth = len(match['indent'].expandtabs(4))
                field = FieldSpec(match['name'], match['kind'], bool(match['required']),
                                  Source("prompt", offset, offset + len(line)),
                                  match['enum'].split('|') if match['enum'] else [])
                while stack and stack[-1][0] >= depth: stack.pop()
                if stack:
                    if stack[-1][1].kind not in ('array', 'object'):
                        spec.schema_understood = False
                    stack[-1][1].children.append(field)
                else:
                    spec.fields.append(field)
                stack.append((depth, field))
            elif re.match(r'^\s+(?:·\s*)?\w+:\s*(?:string|int|number|bool|array|object)', line):
                spec.schema_understood = False
            offset += len(line)
        tools[spec.name] = spec
    return Catalog(tools, source, not issues, issues)
