"""Deterministic (no-LLM) entity checks on the assistant's current state-changing tool call(s).
C TURN_FORMAT: tool call and user message in the same turn when the policy text forbids doing both.
A UNGROUNDED_ID: an identifier-like argument value never appears in user messages, tool results or system/catalog text.
B ATTRIBUTE_CONFLICT: the call's identifier selects a tool-result object whose attribute (e.g. a contact value) has the
  same shape as, but differs from, the value the user stated for that same attribute name, while no user message mentions
  the object's own value. No tool names, benchmark ids or domain rules; read-only calls (get/find/search/list/...) skipped."""
import json, re

READ = re.compile(r'^(get|find|search|list|lookup|check|calculate|verify|view|show|query|fetch|read|retrieve|describe|kb_|think|transfer)', re.I)
CALL = re.compile(r'TOOL_CALL\s+([\w.\-]+):\s*(\{.*\})\s*$', re.S)
RESP = re.compile(r'TOOL_RESPONSE\s+[\w.\-]+:\s*(.*)$', re.S)
CREATE = re.compile(r'^(create|add|new|open|register|log|record|submit|file|generate|issue)', re.I)
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}')


def idlike(v):
    if not isinstance(v, str):
        return False
    v = v.strip()
    if len(v) < 4 or len(v) > 40 or ' ' in v or DATE.match(v):
        return False
    d = sum(c.isdigit() for c in v); a = sum(c.isalpha() for c in v)
    return (d >= 1 and a >= 1) or d >= 6


def walk(x):
    if isinstance(x, dict):
        yield x
        for v in x.values():
            yield from walk(v)
    elif isinstance(x, list):
        for v in x:
            yield from walk(v)


def scalars(x):
    if isinstance(x, dict):
        for v in x.values():
            yield from scalars(v)
    elif isinstance(x, list):
        for v in x:
            yield from scalars(v)
    elif isinstance(x, str):
        yield x


def shape(s):
    return re.sub(r'[A-Za-z]', 'a', re.sub(r'\d', '9', s))


def check(packet):
    hist = packet.get('history', [])
    user = '\n'.join(s['text'] for s in hist if s.get('role') == 'user').lower()
    objs, restext = [], []
    for s in hist:
        if s.get('kind') == 'result':
            m = RESP.search(s['text']); body = m.group(1) if m else s['text']
            restext.append(body.lower())
            try:
                objs.extend(walk(json.loads(body)))
            except Exception:
                pass
    ground = user + '\n' + '\n'.join(restext) + '\n' + '\n'.join(
        s['text'] for k in ('normative_sources', 'declarations') for s in packet.get(k, [])).lower()
    # user-stated attribute values: tool-result scalar fields whose value the user typed
    stated = {}
    for o in objs:
        for k, v in o.items():
            if isinstance(v, str) and len(v) >= 5 and any(c.isdigit() for c in v) and v.lower() in user:
                stated.setdefault(k, set()).add(v)
    out = []
    kinds = {t.get('kind') for t in packet.get('current_targets', [])}
    pol = ' '.join(s['text'] for s in packet.get('normative_sources', [])).lower()
    if {'call', 'text'} <= kinds and re.search(r'(cannot|can not|must not|should not)[^.]{0,60}(both|same time|simultaneous)', pol):
        out.append(dict(rule='C', tool='-', value='call+message in one turn'))   # C: policy forbids doing both in one turn
    for t in packet.get('current_targets', []):
        if t.get('kind') != 'call':
            continue
        m = CALL.search(t['text'])
        if not m or READ.match(m.group(1)):
            continue
        try:
            args = json.loads(m.group(2))
        except Exception:
            continue
        for v in set(scalars(args)):
            if not idlike(v):
                continue
            if v.lower() not in ground:
                if CREATE.match(m.group(1)):
                    continue   # creation calls may legitimately introduce a new identifier
                out.append(dict(rule='A', tool=m.group(1), value=v)); continue
            for o in objs:
                idk = [k for k in o if isinstance(k, str) and 'id' in k.lower() and isinstance(o[k], str)]
                if not idk or o[idk[0]] != v:   # V must be the object's own (first) identifier, not a foreign key
                    continue
                for k2, w in o.items():
                    if not isinstance(w, str) or 'id' in k2.lower() or k2 not in stated or w.lower() in user:
                        continue
                    if any(shape(u) == shape(w) and u != w for u in stated[k2]):
                        out.append(dict(rule='B', tool=m.group(1), value=v, attr=k2, obj_value=w, user_value=sorted(stated[k2])))
    return out
