"""[AVAILABLE TOOLS] catalog: tool list, argument schema, argument validation.

Real layout (all four domains):

    [AVAILABLE TOOLS]
    - tool_name \u2014 First line of the description.
        <4 spaces>more description lines (blank ones are four spaces)
        <4 spaces>arg: string! \u2014 description            ! = required
        <4 spaces>reason: string [enum: a|b|c] \u2014 description

Nested fields are indented deeper (optionally with a bullet). A description line that merely
contains a colon ("Checks: Line status must be Active.") is not a field: the word after the
colon must be a known type and be followed by end of line, '!', '[', '(' or a dash.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

HEAD = re.compile(r'^[ \t]*\[AVAILABLE TOOLS\][ \t]*$', re.I)
TOOL_LINE = re.compile(r'^-\s+(?P<name>[A-Za-z0-9_.\-]+)(?:\s*(?:\u2014|\u2013|--|-|:)\s*(?P<desc>.*))?$')
PARAM_LINE = re.compile('^(?P<ind>[ \t]+)(?:[\u00b7\u2022*][ \t]*|-[ \t]+)?(?P<name>[A-Za-z_][A-Za-z0-9_]*)[ \t]*:[ \t]*'
                        '(?P<type>[A-Za-z]+)(?P<sub>\\[[^\\]\r\n]*\\]|<[^>\r\n]*>)?(?P<req>!)?(?P<tail>[^\r\n]*)$')
TAIL_OK = re.compile('^\\s*(?:$|\\[enum:|[\u2014\u2013-]\\s|\\(|,)', re.I)
ENUM = re.compile(r'\[enum:\s*(?P<values>[^\]]*)\]', re.I)
DESC = re.compile('(?:\u2014|\u2013|\\s-\\s)\\s*(?P<desc>.*)$')
TRUNCATION = re.compile('^\\s*(?:\\.\\.\\.|\u2026)\\s*$|\\[\\s*(?:\\.\\.\\.|\u2026)\\s*\\]|\\b(?:truncated|omitted)\\b', re.I)
CONFIRM = re.compile(r'explicit\s+(?:user\s+)?confirmation|ask\s+for\s+explicit|obtain\s+explicit', re.I)
TYPES = {'string': 'string', 'str': 'string', 'integer': 'integer', 'int': 'integer', 'number': 'number',
         'float': 'number', 'boolean': 'boolean', 'bool': 'boolean', 'array': 'array', 'list': 'array',
         'object': 'object', 'dict': 'object', 'null': 'null', 'any': 'any'}


@dataclass
class Param:
    name: str
    kind: str
    required: bool
    enum: Optional[list]
    description: str
    start: int
    children: list = field(default_factory=list)
    raw_type: str = ''


@dataclass
class ToolSpec:
    name: str
    description: str
    start: int
    end: int
    params: list = field(default_factory=list)
    understood: bool = True
    issues: list = field(default_factory=list)

    @property
    def requires_confirmation(self):
        return bool(CONFIRM.search(self.description))

    def param(self, name):
        return next((p for p in self.params if p.name == name), None)


@dataclass
class Catalog:
    present: bool
    start: int = -1
    end: int = -1
    tools: dict = field(default_factory=dict)
    complete: bool = False
    issues: list = field(default_factory=list)

    def __contains__(self, name):
        return name in self.tools

    def get(self, name):
        return self.tools.get(name)


def _line_iter(text, start, end):
    pos = start
    for raw in text[start:end].splitlines(keepends=True):
        yield pos, raw.rstrip('\r\n')
        pos += len(raw)


def find_catalog(text, start, end):
    """Absolute position of the [AVAILABLE TOOLS] line inside [start, end) or -1."""
    for pos, line in _line_iter(text, start, end):
        if HEAD.match(line):
            return pos
    return -1


def parse_catalog(text, start, end):
    """Parse the catalog that begins at `start` (the [AVAILABLE TOOLS] line) and runs to `end`."""
    if start < 0:
        return Catalog(False, issues=['NO_CATALOG'])
    cat = Catalog(True, start, end)
    tool, stack, base = None, [], None
    lines = list(_line_iter(text, start, end))[1:]
    for pos, line in lines:
        if not line.strip():
            continue
        tm = TOOL_LINE.match(line)
        if tm:
            if tool is not None:
                tool.end = pos
            name = tm.group('name')
            if name in cat.tools:
                cat.issues.append('DUPLICATE_TOOL:' + name)
            tool = ToolSpec(name, (tm.group('desc') or '').strip(), pos, end)
            if name in cat.tools:
                tool.understood = False
                tool.issues.append('DUPLICATE_TOOL_SCHEMA')
            cat.tools[name] = tool
            stack, base = [], None
            continue
        if not line[:1].isspace():
            if tool is None:
                cat.issues.append('TEXT_BEFORE_FIRST_TOOL')
                continue
            cat.issues.append('CATALOG_ENDS_WITH_TEXT')
            tool.end = pos
            cat.end = pos
            break
        if tool is None:
            cat.issues.append('TEXT_BEFORE_FIRST_TOOL')
            continue
        if TRUNCATION.search(line):
            cat.issues.append('TRUNCATION_MARKER:' + tool.name)
        pm = PARAM_LINE.match(line)
        if pm and pm.group('type').lower() in TYPES and TAIL_OK.match(pm.group('tail')):
            tail = pm.group('tail')
            em = ENUM.search(tail)
            dm = DESC.search(tail[em.end():] if em else tail)
            p = Param(pm.group('name'), TYPES[pm.group('type').lower()], bool(pm.group('req')),
                      [v.strip() for v in em.group('values').split('|')] if em else None,
                      dm.group('desc').strip() if dm else '', pos, raw_type=pm.group('type') + (pm.group('sub') or ''))
            depth = len(pm.group('ind').expandtabs(4))
            if base is None:
                base = depth
            while stack and stack[-1][0] >= depth:
                stack.pop()
            if depth > base:
                if not stack:
                    tool.understood = False
                    tool.issues.append('ORPHAN_NESTED_FIELD:' + p.name)
                    tool.params.append(p)
                else:
                    parent = stack[-1][1]
                    if parent.kind not in ('array', 'object'):
                        tool.understood = False
                        tool.issues.append('CHILD_OF_SCALAR:' + p.name)
                    parent.children.append(p)
            else:
                if tool.param(p.name) is not None:
                    tool.understood = False
                    tool.issues.append('DUPLICATE_PARAM:' + p.name)
                tool.params.append(p)
            stack.append((depth, p))
            continue
        if pm and (pm.group('type').lower() in TYPES or pm.group('sub')):
            tool.understood = False
            tool.issues.append('UNSUPPORTED_FIELD_SCHEMA:' + pm.group('name'))
        tool.description = (tool.description + '\n' + line.strip()).strip()
    if tool is not None and cat.end == end:
        tool.end = end
    bad = ('DUPLICATE_TOOL', 'TEXT_BEFORE_FIRST_TOOL', 'TRUNCATION_MARKER', 'CATALOG_ENDS_WITH_TEXT')
    cat.complete = bool(cat.tools) and not any(i.split(':')[0] in bad for i in cat.issues)
    return cat


def _type_ok(value, kind):
    if kind == 'any':
        return True
    if kind == 'null':
        return value is None
    if kind == 'string':
        return isinstance(value, str)
    if kind == 'integer':
        return (type(value) is int) or (type(value) is float and value.is_integer())
    if kind == 'number':
        return type(value) in (int, float)
    if kind == 'boolean':
        return type(value) is bool
    if kind == 'array':
        return isinstance(value, list)
    if kind == 'object':
        return isinstance(value, dict)
    return True


def _enum_ok(value, choices):
    if isinstance(value, str):
        return value in choices
    for choice in choices:
        try:
            expected = json.loads(choice)
        except ValueError:
            continue
        if type(expected) is type(value) and expected == value:
            return True
    return False


def validate_arguments(spec, args):
    """Schema issues as stable strings: MISSING/NULL/TYPE/ENUM/UNEXPECTED <json path>."""
    if not isinstance(args, dict):
        return ['ARGUMENTS_NOT_OBJECT']
    if spec is None or not spec.understood:
        return []
    return _validate(args, spec.params, '$', top=True)


def _validate(obj, params, path, top=False):
    out = []
    names = {p.name for p in params}
    for p in params:
        where = path + '.' + p.name
        if p.name not in obj:
            if p.required:
                out.append('MISSING ' + where)
            continue
        value = obj[p.name]
        if value is None:
            if p.required and p.kind not in ('null', 'any'):
                out.append('NULL ' + where)
            continue
        if not _type_ok(value, p.kind):
            out.append('TYPE %s expected %s got %s' % (where, p.kind, type(value).__name__))
            continue
        if p.enum and not _enum_ok(value, p.enum):
            out.append('ENUM %s=%r' % (where, value))
        if p.children:
            if isinstance(value, dict):
                out += _validate(value, p.children, where)
            elif isinstance(value, list):
                for k, item in enumerate(value):
                    if isinstance(item, dict):
                        out += _validate(item, p.children, '%s[%d]' % (where, k))
    if top or params:
        out += ['UNEXPECTED %s.%s' % (path, k) for k in obj if k not in names]
    return out
