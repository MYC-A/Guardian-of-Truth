"""Line-based parser for the competition transcript format.

Format verified on the task page, on the organisers' answer "trust the examples" (21.09) and on
real valid rows:

    \u27e6SYSTEM\u27e7 / \u27e6USER\u27e7 / \u27e6ASSISTANT\u27e7 / \u27e6ASSISTANT \u00b7 \u0445\u043e\u0434 N\u27e7   role headers on their own line
    <TAB>-> TOOL_CALL name: {json arguments}                 one line (arrow is U+2192)
    <TAB><- TOOL_RESPONSE name: payload                      first line of the payload (U+2190)
    <TAB><- TOOL_RESPONSE name [ERROR]: Error: ...           status tag BEFORE the colon
    <TAB><SP><SP>continuation of a multi-line payload

The documented but unused dialect (\u27e6ASSISTANT_TOOL_CALL name="x"\u27e7, \u27e6TOOL_RESULT name="x"
 requestor="user"\u27e7) is accepted too; every event records the dialect it came from.
Calls and results are paired FIFO per tool name; a result inherits the owner of its call, so a
tool that the user runs on their own device (telecom) is owned by 'user', not by the agent.
"""
from __future__ import annotations

import json
import re
from collections import defaultdict, deque

from .model import Document, Event, Message, Span

HEADER = re.compile('^[ \t]*\u27e6(?P<inner>[^\u27e7\r\n]*)\u27e7[ \t]*(?P<rest>[^\r\n]*)$')
ARROW = re.compile(
    '^[ \t]*(?P<arrow>\u2192|->|\u2190|<-)[ \t]*(?P<kw>TOOL_CALL|TOOL_RESPONSE|TOOL_RESULT)[ \t]+'
    '(?P<tool>[^\\s:\\[\\]]+)[ \t]*(?:\\[(?P<status>[^\\]\r\n]{1,40})\\])?[ \t]*:(?P<rest>[^\r\n]*)$')
ROLE = re.compile(r'^(?P<role>SYSTEM|USER|ASSISTANT|AGENT|TOOL)(?![A-Za-z0-9_])(?P<tail>.*)$', re.I)
NUMBER = re.compile('(?:\u0445\u043e\u0434|turn|step|\u0448\u0430\u0433)\\D{0,3}(\\d+)', re.I)
ATTR = re.compile(r'(\w+)\s*=\s*"([^"]*)"')
ERROR_BODY = re.compile('^\\s*(?:error\\b|\u043e\u0448\u0438\u0431\u043a\u0430)', re.I)
LINE = re.compile(r'[^\n]*\n|[^\n]+')
ROLE_NAMES = {'system': 'system', 'user': 'user', 'assistant': 'assistant', 'agent': 'assistant',
              'tool': 'tool'}
MAX_JSON_LINES = 200
FENCE = re.compile(r'^ {0,3}(`{3,}|~{3,})([^\r\n]*)$')


def decode_json(text):
    """-> (value, ok, duplicate_keys). Duplicate keys keep the last value and are reported."""
    dups = []

    def hook(pairs):
        obj = {}
        for key, item in pairs:
            if key in obj:
                dups.append(key)
            obj[key] = item
        return obj
    try:
        return json.loads(text, object_pairs_hook=hook), True, dups
    except (ValueError, TypeError, RecursionError):
        return None, False, dups


def decode_prefix(text):
    """Leading JSON object/array of text -> (value, ok, end offset in text)."""
    stripped = text.lstrip()
    lead = len(text) - len(stripped)
    if not stripped or stripped[0] not in '{[':
        return None, False, 0
    try:
        value, end = json.JSONDecoder().raw_decode(stripped)
    except (ValueError, RecursionError):
        return None, False, 0
    return value, True, lead + end


def nested_json(value):
    """Arguments that are themselves JSON strings (call_discoverable_agent_tool arguments=...)."""
    out = {}
    if isinstance(value, dict):
        for key, item in value.items():
            if isinstance(item, str) and item.strip()[:1] in ('{', '['):
                decoded, ok, _ = decode_json(item)
                out[key] = decoded if ok else ValueError('INVALID_NESTED_JSON')
    return out


def _lines(text, lo, hi):
    """(start, content_end, full_end, content) per line; content excludes the newline and CR."""
    out = []
    for m in LINE.finditer(text, lo, hi):
        start, full_end = m.start(), m.end()
        end = full_end
        if end > start and text[end - 1] == '\n':
            end -= 1
        if end > start and text[end - 1] == '\r':
            end -= 1
        out.append((start, end, full_end, text[start:end]))
    return out


def _transport_bounds(text):
    m = re.match(r'\s*<(prompt|response)>', text)
    if m:
        close = re.search('</' + m.group(1) + r'>\s*$', text)
        if close:
            return m.end(), close.start()
    return 0, len(text)


def classify_header(inner):
    """-> (kind, who, attrs, number); kind is role | call | result | unknown."""
    s = inner.strip()
    tag = s.split(None, 1)[0].upper() if s else ''
    attrs = dict(ATTR.findall(s))
    if tag in ('ASSISTANT_TOOL_CALL', 'USER_TOOL_CALL', 'TOOL_CALL'):
        who = 'assistant' if tag.startswith('ASSISTANT') else ('user' if tag.startswith('USER') else None)
        return 'call', who, attrs, None
    if tag in ('TOOL_RESULT', 'TOOL_RESPONSE'):
        return 'result', attrs.get('requestor'), attrs, None
    m = ROLE.match(s)
    if m:
        n = NUMBER.search(m.group('tail') or '')
        return 'role', ROLE_NAMES[m.group('role').lower()], attrs, int(n.group(1)) if n else None
    return 'unknown', None, attrs, None


def _dedent(content):
    """Remove the transport indent of a result continuation line: a tab and up to two spaces."""
    if content.startswith('\t'):
        content = content[1:]
        return content[2:] if content.startswith('  ') else content[1:] if content.startswith(' ') else content
    return content[4:] if content.startswith('    ') else content


class _Builder:
    def __init__(self, text, doc):
        self.text, self.doc = text, doc
        self.messages, self.events, self.diag = [], [], []
        self.msg = -1
        self.role = 'assistant' if doc == 'response' else 'unknown'
        self.open = None

    def owner(self):
        return self.role if self.role in ('assistant', 'user', 'system') else 'unknown'

    def add(self, **kw):
        event = Event(index=len(self.events), message=self.msg, **kw)
        self.events.append(event)
        if self.msg >= 0:
            self.messages[self.msg].events.append(event.index)
        return event

    def start_message(self, role, header, number, start, body_start):
        self.close()
        if self.messages:
            prev = self.messages[-1]
            prev.span = Span(self.doc, prev.span.start, start)
        self.messages.append(Message(len(self.messages), role, header, number,
                                     Span(self.doc, start, len(self.text)), body_start))
        self.msg, self.role = len(self.messages) - 1, role

    # -- closing open blocks -------------------------------------------------------------
    def close(self):
        o, self.open = self.open, None
        if o is None:
            return
        if o['kind'] == 'text':
            self._finish_text(o)
        elif o['kind'] == 'result':
            self._finish_result(o)
        else:
            self._finish_header_event(o)

    def _finish_text(self, o):
        lines = [ln for ln in o['lines']]
        while lines and not lines[0][3].strip():
            lines.pop(0)
        while lines and not lines[-1][3].strip():
            lines.pop()
        if not lines:
            return
        first = lines[0]
        start = first[0] + (len(first[3]) - len(first[3].lstrip()))
        body = self.text[start:lines[-1][1]].rstrip()
        self.add(kind='text', role=self.role, owner=self.owner(), span=Span(self.doc, start, start + len(body)),
                 body=body, dialect='text', diagnostics=list(o['diag']))

    def _finish_result(self, o):
        pieces = o['pieces']
        body = '\n'.join(pieces).strip()
        diag = o['diag']
        tag = (o['tag'] or '').strip()
        if tag:
            status = tag.upper()
        elif ERROR_BODY.match(body):
            status = 'ERROR'
            diag.append('ERROR_INFERRED_FROM_BODY')
        else:
            status = 'OK'
        value, ok, dups = (None, False, [])
        if body[:1] in ('{', '['):
            value, ok, dups = decode_json(body)
        diag.extend('DUPLICATE_JSON_KEY:' + k for k in dups)
        self.add(kind='result', role=self.role, owner='unknown', span=Span(self.doc, o['start'], o['end']),
                 body=body, tool=o['tool'], status=status, value=value, is_json=ok,
                 dialect=o.get('dialect', 'arrow'), diagnostics=diag)

    def _finish_header_event(self, o):
        body = '\n'.join(o['lines']).strip()
        attrs, diag = o['attrs'], o['diag']
        name = attrs.get('name')
        if o['kind'] == 'hcall':
            value, ok, dups = decode_json(body) if body else ({}, True, [])
            if not ok:
                diag.append('CALL_ARGUMENTS_NOT_JSON')
            event = self.add(kind='call', role=self.role, owner=o['who'] or self.owner(),
                             span=Span(self.doc, o['start'], o['end']), body=body, tool=name, value=value,
                             is_json=ok, dialect='header', diagnostics=diag)
            event.nested = nested_json(value)
        else:
            self._finish_result(dict(start=o['start'], end=o['end'], tool=name, tag=attrs.get('status'),
                                     pieces=[body], diag=diag, dialect='header'))
            if o['who']:
                self.events[-1].owner = o['who']
                self.events[-1].diagnostics.append('REQUESTOR:' + o['who'])

    # -- line handlers -----------------------------------------------------------------
    def on_call(self, lines, i, m):
        self.close()
        start, cend, _, _ = lines[i]
        rest = m.group('rest')
        p0 = start + m.start('rest') + (len(rest) - len(rest.lstrip()))
        diag = []
        if m.group('arrow') == '->':
            diag.append('ASCII_ARROW')
        if m.group('status'):
            diag.append('STATUS_TAG_ON_CALL')
        value, ok, endpos = decode_prefix(self.text[p0:cend])
        j = i
        if not ok and self.text[p0:cend].lstrip()[:1] in ('{', '['):
            for k in range(i + 1, min(len(lines), i + MAX_JSON_LINES)):
                content = lines[k][3]
                if HEADER.match(content) or ARROW.match(content):
                    break
                value, ok, endpos = decode_prefix(self.text[p0:lines[k][1]])
                if ok:
                    j = k
                    diag.append('MULTILINE_ARGUMENTS')
                    break
        if ok:
            body_end = p0 + endpos
        else:
            body_end = cend
            diag.append('CALL_ARGUMENTS_NOT_JSON')
        body = self.text[p0:body_end].strip()
        if ok:
            value, _, dups = decode_json(body)
            diag.extend('DUPLICATE_JSON_KEY:' + k for k in dups)
        if m.group('kw') != 'TOOL_CALL':
            diag.append('UNEXPECTED_KEYWORD:' + m.group('kw'))
        event = self.add(kind='call', role=self.role, owner=self.owner(), span=Span(self.doc, start, body_end),
                         body=body, tool=m.group('tool'), value=value, is_json=ok, diagnostics=diag)
        event.nested = nested_json(value)
        last_end = lines[j][1]
        tail = self.text[body_end:last_end] if ok else ''
        if tail.strip():
            ts = body_end + (len(tail) - len(tail.lstrip()))
            self.open = dict(kind='text', lines=[(ts, last_end, last_end, self.text[ts:last_end])],
                             diag=['TEXT_AFTER_CALL_SAME_LINE'])
        return j + 1

    def on_result(self, line, m):
        self.close()
        start, cend, _, _ = line
        rest = m.group('rest')
        first = rest[1:] if rest.startswith(' ') else rest
        diag = []
        if m.group('arrow') == '<-':
            diag.append('ASCII_ARROW')
        if m.group('kw') != 'TOOL_RESPONSE':
            diag.append('KEYWORD:' + m.group('kw'))
        self.open = dict(kind='result', start=start, end=cend, tool=m.group('tool'), tag=m.group('status'),
                         pieces=[first], pending=[], diag=diag)

    def on_plain(self, line):
        content = line[3]
        o = self.open
        if o is not None and o['kind'] == 'result':
            if content.startswith('\t') or content.startswith('    '):
                o['pieces'].extend(o['pending'])
                o['pending'] = []
                o['pieces'].append(_dedent(content))
                o['end'] = line[1]
                return
            if not content.strip():
                o['pending'].append('')
                return
            self.close()
            self.open = dict(kind='text', lines=[line], diag=['TEXT_AFTER_RESULT_WITHOUT_HEADER'])
            return
        if o is not None and o['kind'] == 'text':
            o['lines'].append(line)
            return
        if o is not None and o['kind'] in ('hcall', 'hresult'):
            o['lines'].append(content)
            o['end'] = line[1]
            return
        if not content.strip():
            return
        last = self.events[-1] if self.events else None
        diag = []
        if last is not None and last.message == self.msg and last.kind in ('call', 'result'):
            diag.append('TEXT_AFTER_TOOL_EVENT')
        self.open = dict(kind='text', lines=[line], diag=diag)


def parse_document(text, doc='prompt'):
    """Parse a prompt or a response. Never raises on malformed input; problems become diagnostics."""
    text = '' if text is None else str(text)
    b = _Builder(text, doc)
    lo, hi = _transport_bounds(text)
    if (lo, hi) != (0, len(text)):
        b.diag.append('TRANSPORT_TAGS')
    lines = _lines(text, lo, hi)
    i = 0
    fence = None
    while i < len(lines):
        line = lines[i]
        content = line[3]
        # The documented TAB + two spaces belongs to an open result payload.
        # Its embedded role headers/arrows are data, never transport markers.
        if b.open is not None and b.open['kind']=='result' and content.startswith('\t  '):
            b.on_plain(line)
            i += 1
            continue
        fm = FENCE.match(content)
        if fence is not None:
            b.on_plain(line)
            if fm and fm.group(1)[0] == fence[0] and len(fm.group(1)) >= fence[1] and not fm.group(2).strip():
                fence = None
            i += 1
            continue
        if fm:
            fence = (fm.group(1)[0], len(fm.group(1)))
            b.on_plain(line)
            i += 1
            continue
        hm = HEADER.match(content)
        if hm:
            kind, who, attrs, number = classify_header(hm.group('inner'))
            rest = hm.group('rest')
            if kind == 'role':
                body_start = line[0] + hm.start('rest') if rest.strip() else line[2]
                b.start_message(who, hm.group('inner').strip(), number, line[0], body_start)
                if rest.strip():
                    rs = line[0] + hm.start('rest')
                    b.open = dict(kind='text', lines=[(rs, line[1], line[2], text[rs:line[1]])],
                                  diag=['TEXT_ON_HEADER_LINE'])
            elif kind in ('call', 'result'):
                b.close()
                b.open = dict(kind='h' + kind, start=line[0], end=line[1], attrs=attrs, who=who,
                              lines=[rest] if rest.strip() else [], diag=['HEADER_DIALECT'])
            else:
                b.diag.append('UNRECOGNIZED_HEADER:' + hm.group('inner')[:40])
                b.on_plain(line)
            i += 1
            continue
        am = ARROW.match(content)
        if am:
            if am.group('kw') == 'TOOL_CALL' or am.group('arrow') in ('\u2192', '->'):
                i = b.on_call(lines, i, am)
            else:
                b.on_result(line, am)
                i += 1
            continue
        b.on_plain(line)
        i += 1
    b.close()
    if fence is not None:
        b.diag.append('UNCLOSED_MARKDOWN_FENCE')
    if b.messages:
        last = b.messages[-1]
        last.span = Span(doc, last.span.start, hi)
    _pair(b)
    document = Document(doc, text, b.messages, b.events, b.diag)
    _document_checks(document)
    return document


def _pair(b):
    pending = defaultdict(deque)
    for e in b.events:
        if e.kind == 'call':
            pending[e.tool].append(e)
        elif e.kind == 'result':
            queue = pending.get(e.tool)
            # Header-dialect requestor is authoritative. An explicit user
            # result must not close an older pending assistant call (or vice versa).
            if queue and e.owner != 'unknown':
                call = next((c for c in queue if c.owner == e.owner), None)
                if call is not None:
                    queue.remove(call)
                else:
                    call = None
            else:
                call = queue.popleft() if queue else None
            if call is not None:
                call.pair, e.pair = e.index, call.index
                if e.owner == 'unknown':
                    e.owner = call.owner
                if call.message != e.message:
                    e.diagnostics.append('RESULT_IN_OTHER_MESSAGE')
            else:
                e.diagnostics.append('RESULT_WITHOUT_CALL')
                if e.owner == 'unknown' and e.role in ('assistant', 'user'):
                    e.owner = e.role
    if b.doc == 'prompt':
        for queue in pending.values():
            for call in queue:
                call.diagnostics.append('CALL_WITHOUT_RESULT')


def _document_checks(d):
    if any(e.message < 0 for e in d.events):
        d.diagnostics.append('CONTENT_BEFORE_FIRST_HEADER')
    if d.doc == 'response':
        roles = [m.role for m in d.messages]
        if not roles:
            d.diagnostics.append('RESPONSE_WITHOUT_HEADER')
        elif any(r != 'assistant' for r in roles):
            d.diagnostics.append('RESPONSE_NON_ASSISTANT_HEADER')
        if len(roles) > 1:
            d.diagnostics.append('RESPONSE_SEVERAL_HEADERS')
    else:
        if not d.messages or d.messages[0].role != 'system':
            d.diagnostics.append('PROMPT_NOT_STARTING_WITH_SYSTEM')
        if sum(1 for m in d.messages if m.role == 'system') > 1:
            d.diagnostics.append('SEVERAL_SYSTEM_MESSAGES')


def document_stats(d):
    """Counters that make format drift visible in a platform log."""
    stats = dict(messages=len(d.messages), events=len(d.events))
    for m in d.messages:
        stats['msg_' + m.role] = stats.get('msg_' + m.role, 0) + 1
    stats['numbered_turns'] = sum(1 for m in d.messages if m.number is not None)
    for e in d.events:
        key = e.kind + ('_' + e.owner if e.kind != 'text' else '_' + e.role)
        stats[key] = stats.get(key, 0) + 1
        stats['dialect_' + e.dialect] = stats.get('dialect_' + e.dialect, 0) + 1
        if e.is_error:
            stats['result_error'] = stats.get('result_error', 0) + 1
        for item in e.diagnostics:
            key = 'diag_' + item.split(':')[0]
            stats[key] = stats.get(key, 0) + 1
    for item in d.diagnostics:
        key = 'doc_' + item.split(':')[0]
        stats[key] = stats.get(key, 0) + 1
    return stats
