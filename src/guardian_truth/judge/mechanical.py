"""Mechanical layer.

hard  : findings provable from the transcript structure; any hard finding forces label 1.
        Tool not in the declared catalog; schema violation (required field, type, enum); arguments that
        are not an object; a reference argument (key *_id, *_ids, *_number, *_code, not new_*) whose value
        appears nowhere in the transcript; the narrow expired-contract date gate.
hints : suspicious spots code cannot prove; shown to the judge, never a label by themselves.
        Several calls or text plus call against an explicit policy rule (the task does not treat this
        as a hallucination by itself), unknown id-like values in non-reference arguments, numbers not
        found in the transcript, completion claims without a call, refusals, escalations, repeats.
Only prompt/response text is read. No domain names, row ids or labels. Errors -> no findings.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date

MARKER = re.compile(
    r'^[ \t]*(?:⟦(?P<header>[^⟧\r\n]+)⟧[ \t]*|'
    r'(?P<arrow>→ TOOL_CALL|← TOOL_RESPONSE)[ \t]+(?P<tool>[\w.-]+)[ \t]*:[ \t]*)',
    re.MULTILINE)
TOOL = re.compile(r'^- (?P<name>[\w.-]+)\s+[—–]\s*', re.MULTILINE)
FIELD = re.compile(
    r'^(?P<indent>[ \t]+)(?:·\s*)?(?P<name>\w+):\s*'
    r'(?P<kind>string|integer|number|boolean|array|object)(?P<required>!)?'
    r'(?:\s+\[enum:\s*(?P<enum>[^\]]+)\])?(?=\s|$)')
LOOSE_FIELD = re.compile(r'^\s+(?:·\s*)?\w+:\s*(?:string|int|number|bool|array|object)')

ONE_CALL = re.compile(r"\b(?:you\s+)?(?:should|must)\s+(?:only\s+make|at\s+most\s+make)\s+one\s+"
                      r"tool\s+call\s+at\s+a\s+time\b", re.I)
EXCLUSIVE = re.compile(r"\b(?:either|can\s+either)\b[\s\S]{0,240}\bsend\s+a\s+message\b"
                       r"[\s\S]{0,240}\bmake\s+a\s+tool\s+call\b[\s\S]{0,160}\bcannot\s+do\s+both\b", re.I)
EXPIRED_GATE = re.compile(r"\byou\s+are\s+not\s+allowed\s+to\s+lift\s+the\s+suspension\s+if\s+the\s+"
                          r"line['’]s\s+contract\s+end\s+date\s+is\s+in\s+the\s+past\b", re.I)
CURRENT_DATE = re.compile(r"\bthe\s+current\s+(?:time|date)\s+is\s+(\d{4}-\d{2}-\d{2})\b", re.I)

_ID = r'(?=[A-Za-z0-9_\-]*[A-Za-z])(?=[A-Za-z0-9_\-]*\d)[A-Za-z0-9][A-Za-z0-9_\-]{4,63}'
ID_VALUE = re.compile(r'^#?' + _ID + r'$')
TEXT_ID = re.compile(r'(?<![\w#-])#?' + _ID + r'(?![\w-])')
REF_KEY = re.compile(r'(?:^|_)(?:id|ids|number|code)$', re.I)
REF_VALUE = re.compile(r'^#?[A-Za-z0-9][A-Za-z0-9_\-]{3,63}$')
NUM_REPLY = re.compile(r'(?<![\w.:/-])\$?(\d{1,3}(?:,\d{3})+|\d+)(\.\d+)?(?![\w])')
NUM_CTX = re.compile(r'\d+(?:\.\d+)?')
REFUSAL = re.compile(r"\b(?:unable to|cannot|can't|can not|not able to|not possible|isn't possible|"
                     r"not eligible|unfortunately|i'm afraid|not allowed|not permitted)\b", re.I)
DONE_CLAIM = re.compile(r"\b(?:has been|have been|i've|i have|successfully|is now|are now)\b[^.!?\n]{0,60}?"
                        r"\b(?:cancel|refund|updat|chang|modif|book|exchang|return|process|transferr|resum|"
                        r"suspend|enabl|disabl|reset|upgrad|downgrad|issu|creat|submit)", re.I)
ERRORISH = re.compile(r'\b(?:error|not found|failed|invalid|denied|unauthori[sz]ed|exception)\b', re.I)
NON_ALNUM = re.compile(r'[\W_]+')
MAX_HINTS, HINT_CHARS = 8, 220


@dataclass
class Event:
    role: str
    kind: str            # text | call | result
    body: str
    name: str | None = None
    value: object = None
    valid: bool = False


@dataclass
class FieldSpec:
    name: str
    kind: str
    required: bool
    enum: list
    children: list = field(default_factory=list)


@dataclass
class ToolSpec:
    name: str
    fields: list = field(default_factory=list)
    understood: bool = True


@dataclass
class Findings:
    hard: list = field(default_factory=list)
    hints: list = field(default_factory=list)


def decode_json(text):
    try:
        return json.loads(text), True
    except (ValueError, TypeError, RecursionError):
        return None, False


def parse_events(text, default_role):
    events, markers, role = [], list(MARKER.finditer(text)), default_role

    def add(r, kind, body, name=None):
        body = body.strip()
        if kind == 'text' and not body:
            return
        value, valid = (None, False) if kind == 'text' else decode_json(body)
        events.append(Event(r, kind, body, name, value, valid))

    add(role, 'text', text[:markers[0].start()] if markers else text)
    for i, m in enumerate(markers):
        body = text[m.end():markers[i + 1].start() if i + 1 < len(markers) else len(text)]
        header = m.group('header')
        if header:
            tag = header.split()[0]
            attr = dict(re.findall(r'(\w+)="([^"]*)"', header))
            if tag in ('SYSTEM', 'USER', 'ASSISTANT'):
                role = tag.lower()
                add(role, 'text', body)
            elif tag in ('ASSISTANT_TOOL_CALL', 'USER_TOOL_CALL'):
                role = 'assistant' if tag.startswith('ASSISTANT') else 'user'
                add(role, 'call', body, attr.get('name'))
            elif tag == 'TOOL_RESULT':
                add('tool', 'result', body, attr.get('name'))
            else:
                add('unknown', 'text', body)
        else:
            kind = 'call' if m.group('arrow').startswith('→') else 'result'
            add(role if kind == 'call' else 'tool', kind, body, m.group('tool'))
    return events


def parse_catalog(events):
    blocks = [e for e in events if e.role == 'system' and '[AVAILABLE TOOLS]' in e.body]
    if len(blocks) != 1:
        return {}, False
    raw = blocks[0].body.split('[AVAILABLE TOOLS]', 1)[1]
    defs = list(TOOL.finditer(raw))
    complete = bool(defs) and '...' not in raw and '…' not in raw
    for line in raw.splitlines():
        if line.startswith('- ') and not TOOL.match(line):
            complete = False
    tools = {}
    for i, d in enumerate(defs):
        segment = raw[d.start():defs[i + 1].start() if i + 1 < len(defs) else len(raw)]
        spec, stack = ToolSpec(d.group('name')), []
        if spec.name in tools:
            complete = False
        for line in segment.splitlines():
            m = FIELD.match(line)
            if m:
                depth = len(m.group('indent').expandtabs(4))
                enum = [c.strip() for c in m.group('enum').split('|')] if m.group('enum') else []
                f = FieldSpec(m.group('name'), m.group('kind'), bool(m.group('required')), enum)
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                if stack:
                    if stack[-1][1].kind not in ('array', 'object'):
                        spec.understood = False
                    stack[-1][1].children.append(f)
                else:
                    spec.fields.append(f)
                stack.append((depth, f))
            elif LOOSE_FIELD.match(line):
                spec.understood = False
        tools[spec.name] = spec
    return tools, complete


def _type_ok(value, kind):
    return {'string': isinstance(value, str), 'integer': type(value) is int,
            'number': type(value) in (int, float), 'boolean': type(value) is bool,
            'array': isinstance(value, list), 'object': isinstance(value, dict)}.get(kind, True)


def _enum_ok(value, choices):
    if isinstance(value, str):
        return value in choices
    for choice in choices:
        expected, ok = decode_json(choice)
        if ok and isinstance(value, bool) == isinstance(expected, bool) and value == expected:
            return True
    return False


def validate(value, fields, prefix='$'):
    issues = []
    for f in fields:
        path = prefix + '.' + f.name
        if f.name not in value:
            if f.required:
                issues.append('missing ' + path)
            continue
        actual = value[f.name]
        if actual is None and not f.required:
            continue
        if not _type_ok(actual, f.kind):
            issues.append(f'type {path} expected {f.kind}')
            continue
        if f.enum and not _enum_ok(actual, f.enum):
            issues.append('enum ' + path)
        if f.children:
            if isinstance(actual, dict):
                issues += validate(actual, f.children, path)
            elif isinstance(actual, list):
                for k, item in enumerate(actual):
                    if isinstance(item, dict):
                        issues += validate(item, f.children, f'{path}[{k}]')
                    else:
                        issues.append(f'type {path}[{k}] expected object')
    return issues


def _keyed_strings(obj, key=None):
    """(nearest dict key, string value) for every string in the arguments; list items keep the list key."""
    if isinstance(obj, dict):
        for k, v in obj.items():
            yield from _keyed_strings(v, k)
    elif isinstance(obj, list):
        for v in obj:
            yield from _keyed_strings(v, key)
    elif isinstance(obj, str):
        yield key, obj


def _numbers(obj):
    if isinstance(obj, dict):
        for v in obj.values():
            yield from _numbers(v)
    elif isinstance(obj, list):
        for v in obj:
            yield from _numbers(v)
    elif type(obj) in (int, float):
        yield float(obj)


def is_reference_key(key):
    """Argument keys that point at an entity that must already exist (reservation_id, item_ids,
    flight_number, ...). new_* keys may legitimately carry values chosen for a new entity."""
    return bool(key) and bool(REF_KEY.search(key)) and not key.lower().startswith('new')


def _compact(text):
    return NON_ALNUM.sub('', text.lower())


def _collect_numbers(text):
    values = []
    for m in NUM_CTX.finditer(text.replace(',', '')):
        try:
            values.append(round(float(m.group()), 2))
        except ValueError:
            pass
    return values


class _Numbers:
    """Numbers of the transcript; sums/differences only over the 200 most recent distinct values."""

    def __init__(self, prompt):
        self.values = set(_collect_numbers(prompt))
        self.recent = list(dict.fromkeys(reversed(_collect_numbers(prompt[-30000:]))))[:200]
        self._pairs = None

    def derivable(self, x):
        x = round(x, 2)
        if x in self.values or any(round(x / k, 2) in self.values for k in range(2, 10)):
            return True
        if self._pairs is None:
            r = self.recent
            self._pairs = {round(a + b, 2) for a in r for b in r} | {round(abs(a - b), 2) for a in r for b in r}
        return x in self._pairs


def _earlier_identical(history, call):
    status = None
    for i, e in enumerate(history):
        if e.kind == 'call' and e.name == call.name and e.valid and e.value == call.value:
            result = next((r for r in history[i + 1:] if r.kind == 'result' and r.name == call.name), None)
            status = 'error' if result is not None and ERRORISH.search(result.body[:2000]) else 'ok'
    return status


def _date_gate(history, calls, system_text):
    clocks = set(CURRENT_DATE.findall(system_text))
    if len(EXPIRED_GATE.findall(system_text)) != 1 or len(clocks) != 1:
        return []
    try:
        current = date.fromisoformat(clocks.pop())
    except ValueError:
        return []
    found = []
    for call in calls:
        if call.name != 'resume_line' or not isinstance(call.value, dict):
            continue
        line = call.value.get('line_id')
        ends = []
        for i, e in enumerate(history):
            if e.kind == 'result' and isinstance(e.value, dict) and e.value.get('line_id') == line:
                try:
                    ends.append((i, date.fromisoformat(str(e.value.get('contract_end_date')))))
                except ValueError:
                    pass
        if line and ends and max(ends)[1] < current:
            found.append(f'date_gate resume_line {line}: contract ended before current date')
    return found


def analyze(prompt, response, hard_unknown_identifier=True):
    out = Findings()
    try:
        _analyze(prompt or '', response or '', out, hard_unknown_identifier)
    except Exception:
        return Findings()
    out.hints = [h[:HINT_CHARS] for h in dict.fromkeys(out.hints)][:MAX_HINTS]
    return out


def _analyze(prompt, response, out, hard_unknown_identifier):
    history = parse_events(prompt, 'unknown')
    turn = parse_events(response, 'assistant')
    tools, complete = parse_catalog(history)
    system_text = '\n'.join(e.body for e in history if e.role == 'system')
    calls = [e for e in turn if e.kind == 'call' and e.role == 'assistant']
    reply = '\n'.join(e.body for e in turn if e.kind == 'text' and e.role == 'assistant')
    context = prompt.lower()
    context_compact = _compact(prompt)
    numbers = _Numbers(prompt)

    for call in calls:
        spec = tools.get(call.name)
        if spec is None:
            if complete:
                out.hard.append(f'unavailable_tool {call.name}')
            else:
                out.hints.append(f'Tool "{call.name}" is not in the parsed tool list; check it is available.')
            continue
        if not call.valid:
            out.hints.append(f'The arguments of {call.name} are not valid JSON.')
            continue
        if not isinstance(call.value, dict):
            out.hard.append(f'arguments_not_object {call.name}')
            continue
        if spec.understood:
            out.hard.extend(f'schema {call.name}: {issue}' for issue in validate(call.value, spec.fields))
        for key, value in _keyed_strings(call.value):
            v = value.strip()
            if not v:
                continue
            if is_reference_key(key) and REF_VALUE.match(v):
                c = _compact(v)
                if len(c) >= 4 and c not in context_compact:
                    if hard_unknown_identifier:
                        out.hard.append(f'unknown_reference {call.name}.{key}: {v}')
                    else:
                        out.hints.append(f'{call.name}.{key} = "{v}" refers to an entity that appears nowhere '
                                         'in the transcript.')
            elif ID_VALUE.match(v) and v.lstrip('#').lower() not in context:
                out.hints.append(f'{call.name}.{key or "argument"} uses "{v}", which appears nowhere in the '
                                 'transcript.')
        odd = [x for x in _numbers(call.value) if x >= 10 and not numbers.derivable(x)]
        if odd:
            out.hints.append(f'{call.name} uses numbers not found in the transcript: '
                             + ', '.join(f'{x:g}' for x in odd[:4]) + '.')
        repeat = _earlier_identical(history, call)
        if repeat:
            out.hints.append(f'{call.name} repeats an identical earlier call'
                             + (' whose result looked like an error.' if repeat == 'error' else '.'))
        if 'transfer' in call.name and 'human' in call.name:
            out.hints.append('The turn transfers to a human: check the policy requires or allows it now '
                             'and that no permitted action is still available to the agent.')

    if ONE_CALL.search(system_text) and len(calls) > 1:
        out.hints.append('The policy asks for one tool call at a time and this turn makes several: '
                         'judge only whether this changes the outcome.')
    if EXCLUSIVE.search(system_text) and calls and reply.strip():
        out.hints.append('The policy separates messages and tool calls and this turn does both: '
                         'judge only whether this changes the outcome.')
    out.hard.extend(_date_gate(history, calls, system_text))

    if reply:
        if REFUSAL.search(reply):
            out.hints.append('The turn refuses or says something is impossible: check that the policy and '
                             'tools really leave no permitted way to proceed.')
        if DONE_CLAIM.search(reply) and not calls:
            last = next((e for e in reversed(history) if e.kind == 'result'), None)
            if last is not None and ERRORISH.search(last.body[:2000]):
                out.hints.append('The turn claims an action was completed, but the latest tool result looks '
                                 'like an error.')
            else:
                out.hints.append('The turn claims an action was completed: verify a matching successful tool '
                                 'result exists.')
        odd = []
        for m in NUM_REPLY.finditer(reply):
            x = float(m.group(1).replace(',', '') + (m.group(2) or ''))
            if (x >= 10 or m.group(2)) and not numbers.derivable(x):
                odd.append(m.group(0))
        if odd:
            out.hints.append('Numbers in the reply not found in the transcript (nor a simple sum, '
                             'difference or multiple): ' + ', '.join(dict.fromkeys(odd[:5])) + '.')
        ids = [t for t in TEXT_ID.findall(reply) if t.lstrip('#').lower() not in context]
        if ids:
            out.hints.append('Identifiers in the reply that appear nowhere in the transcript: '
                             + ', '.join(dict.fromkeys(ids[:5])) + '.')
