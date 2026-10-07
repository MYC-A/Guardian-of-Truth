"""Shared, typed views of a packet: parsed calls/results, call->result pairing, tool catalog schema, failure status."""
from __future__ import annotations

import json
import re
from guardian_truth.parsing import decode_json

CALL_RE = re.compile(r'TOOL_CALL\s+([^\s:]+):\s*(.*)\s*$', re.S)
RES_RE = re.compile(r'TOOL_RESPONSE\s+([^\s:]+):\s*(.*)\s*$', re.S)


def parse_call(item):
    """-> (tool, args) ; args is the parsed JSON object (types preserved) or None when unparseable."""
    m = CALL_RE.search(item.get('text') or '')
    if not m:
        return item.get('tool'), None
    a, valid = decode_json(m.group(2).strip())
    if not valid:
        return m.group(1), None
    return m.group(1), a if isinstance(a, dict) else None


def parse_result(item):
    """-> (tool, payload) ; payload = parsed JSON when possible, else the raw string."""
    m = RES_RE.search(item.get('text') or '')
    if not m:
        return item.get('tool'), (item.get('text') or '').strip()
    raw = m.group(2).strip()
    value, valid = decode_json(raw)
    return m.group(1), value if valid else raw


TRANSIENT = re.compile(r'time ?d? ?out|timeout|temporar|rate.?limit|too many requests|\b429\b|\b50[234]\b|try again later|'
                       r'service unavailable|connection (reset|refused|error)|network error', re.I)
FAIL_TEXT = re.compile(r'^\s*(error\b|exception\b|failed\b|failure\b)|\bnot found\b|does not exist|\binvalid\b|\bunauthori[sz]ed\b|'
                       r'\bdenied\b|\bcannot\b|\bunable to\b', re.I)


def failure_status(payload):
    """OK | FAILED_PERMANENT | FAILED_TRANSIENT | UNKNOWN. A JSON object fails only through an explicit failure field
    ({"error": null, "ok": true} is success); free text fails through failure wording."""
    if isinstance(payload, dict):
        err = payload.get('error', None)
        bad = (err not in (None, False, '', [], {})) or payload.get('ok') is False or payload.get('success') is False or \
            str(payload.get('status', '')).lower() in ('error', 'failed', 'failure')
        if not bad:
            return 'OK'
        txt = json.dumps(payload, ensure_ascii=False)
        return 'FAILED_TRANSIENT' if TRANSIENT.search(txt) else 'FAILED_PERMANENT'
    if isinstance(payload, (list, int, float, bool)) or payload is None:
        return 'OK'
    s = str(payload)
    if TRANSIENT.search(s):
        return 'FAILED_TRANSIENT'
    if FAIL_TEXT.search(s):
        return 'FAILED_PERMANENT'
    return 'OK'


def pair(history):
    """Pair calls with results. The rendered transcript carries no call ids, so pairing is by tool name inside one
    contiguous call/result block: a call is PAIRED only if its tool occurs exactly once among the block's calls and
    exactly once among its results; otherwise AMBIGUOUS (never guessed by position). Returns {call_source_id: info}."""
    out, i, h = {}, 0, history
    while i < len(h):
        if h[i].get('kind') not in ('call', 'result'):
            i += 1
            continue
        j = i
        while j < len(h) and h[j].get('kind') in ('call', 'result'):
            j += 1
        block = h[i:j]
        calls = [x for x in block if x['kind'] == 'call']
        res = [x for x in block if x['kind'] == 'result']
        for c in calls:
            tool, args = parse_call(c)
            same_c = [x for x in calls if parse_call(x)[0] == tool]
            same_r = [x for x in res if parse_result(x)[0] == tool]
            if len(same_c) == 1 and len(same_r) == 1:
                out[c['source_id']] = dict(status='PAIRED', result=same_r[0], block=(i, j))
            elif not same_r:
                out[c['source_id']] = dict(status='NO_RESULT', result=None, block=(i, j))
            else:
                out[c['source_id']] = dict(status='AMBIGUOUS', result=None, block=(i, j))
        i = j
    return out


TOOL_LINE = re.compile(r'^- ([A-Za-z0-9_.\-]+) — (.*)$')
FIELD_LINE = re.compile(r'^\s{2,}([A-Za-z0-9_]+): ([a-z]+)(!)?(?: \[enum: ([^\]]*)\])? — (.*)$')


def catalog(p):
    """Parse the rendered [AVAILABLE TOOLS] declarations -> {tool: dict(desc, fields={name: dict(type, required, enum, desc)}, source_id)}."""
    out, cur = {}, None
    for d in p.get('declarations') or []:
        for line in d['text'].split('\n'):
            m = TOOL_LINE.match(line)
            if m:
                cur = out.setdefault(m.group(1), dict(desc=m.group(2), fields={}, source_id=d['source_id']))
                continue
            f = FIELD_LINE.match(line)
            if f and cur is not None:
                cur['fields'][f.group(1)] = dict(type=f.group(2), required=bool(f.group(3)),
                                                 enum=f.group(4).split('|') if f.group(4) else None, desc=f.group(5))
            elif cur is not None and line.startswith('    ') and line.strip() and not f:
                cur['desc'] += ' ' + line.strip()             # wrapped description line
    return out


def coverage(p):
    c = p.get('coverage')
    return c if isinstance(c, dict) else {}


def complete(p):
    return bool(coverage(p).get('complete_input'))
