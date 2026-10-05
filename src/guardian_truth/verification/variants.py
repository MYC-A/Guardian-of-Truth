"""Code-built minimal counterfactual variants of the current assistant move (protocol §3).

Each variant changes exactly ONE element of the current move:
  ARG      a scalar argument leaf of a current call -> a same-type value observed earlier
           (history tool payloads, user text) or stated next to the argument name in the policy;
  OMIT_CALL  the call is not made;
  PROSE_VALUE a number / date / ID in current prose -> a same-type value observed earlier;
  OMIT_SENTENCE  a prose sentence carrying a value is removed.
Code never decides which variant is right; ranking only bounds the count (<= MAX_VARIANTS)."""
from __future__ import annotations

import json
import re

MAX_VARIANTS = 10
PER_LEAF = 3
DATE = re.compile(r'^\d{4}-\d{2}-\d{2}(?:[T ][\d:]+)?$')
ID_LIKE = re.compile(r'^(?=.*[A-Za-z])[A-Za-z0-9]+(?:[-_.][A-Za-z0-9]+)+$|^(?=.*\d)(?=.*[A-Za-z])[A-Za-z0-9]{4,}$')
NUM_TXT = re.compile(r'(?<![\w.])\$?(\d{1,3}(?:[ ,]\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)(?![\w])')
DATE_TXT = re.compile(r'\b\d{4}-\d{2}-\d{2}\b')
ID_TXT = re.compile(r'\b(?=[\w-]*[A-Za-z])(?=[\w-]*\d)[A-Za-z0-9]+(?:[-_][A-Za-z0-9]+)+\b')
SENT = re.compile(r'(?<=[^\d\W][.!?])\s+|(?<=[)»"][.!?])\s+|\n+')
MAX_OMITS = 5
LIST_MARK = re.compile(r'^\s*(?:[-*•]|\d{1,2}[.)])\s*')


def vclass(v):
    if isinstance(v, bool):
        return 'bool'
    if isinstance(v, (int, float)):
        return 'id' if isinstance(v, int) and abs(v) >= 10 ** 6 else 'num'
    if isinstance(v, str):
        s = v.strip()
        if not s or '\n' in s or len(s) > 120:
            return None
        if DATE.match(s):
            return 'date'
        if ID_LIKE.match(s):
            return 'id'
        return 'str'
    return None


def _num(s):
    try:
        return float(s.replace(' ', '').replace(',', '').lstrip('$'))
    except ValueError:
        return None


def leaves(value, path=()):
    """(path, key, value) for every scalar leaf of a JSON value."""
    if isinstance(value, dict):
        for k, v in value.items():
            yield from leaves(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value):
            yield from leaves(v, path + (i,))
    else:
        key = next((p for p in reversed(path) if isinstance(p, str)), None)
        yield path, key, value


def _dicts(value):
    if isinstance(value, dict):
        yield value
        for v in value.values():
            yield from _dicts(v)
    elif isinstance(value, list):
        for v in value:
            yield from _dicts(v)


def observations(store):
    """Values observed BEFORE the current move: dict(value, cls, key, event, origin, neighbours)."""
    out = []
    for i, e in enumerate(store.history_events):
        if e.role == 'system':
            continue
        if e.kind in ('call', 'result') and e.json_valid:
            for d in _dicts(e.value):
                scal = {json.dumps(v, ensure_ascii=False) for v in d.values() if vclass(v)}
                for k, v in d.items():
                    c = vclass(v)
                    if c:
                        out.append(dict(value=v, cls=c, key=k, event=i, origin='tool_' + e.kind, neighbours=scal))
            if not isinstance(e.value, (dict, list)) and vclass(e.value):
                out.append(dict(value=e.value, cls=vclass(e.value), key=None, event=i, origin='tool_' + e.kind, neighbours=set()))
        elif e.kind == 'text':
            out += _text_values(e.text, i, 'user' if e.role == 'user' else 'assistant_text')
    return out


def _text_values(text, event, origin):
    out = []
    for m in DATE_TXT.finditer(text):
        out.append(dict(value=m[0], cls='date', key=None, event=event, origin=origin, neighbours=set()))
    for m in ID_TXT.finditer(text):
        out.append(dict(value=m[0], cls='id', key=None, event=event, origin=origin, neighbours=set()))
    for m in NUM_TXT.finditer(text):
        if DATE_TXT.search(text[max(0, m.start() - 8):m.end() + 8]):
            continue
        line_start = text.rfind('\n', 0, m.start()) + 1
        if LIST_MARK.match(text[line_start:m.end() + 2]) and text[line_start:m.start()].strip() in ('', '-', '*', '•'):
            continue                                   # list marker "1." / "2)"
        n = _num(m[1])
        if n is None:
            continue
        if n.is_integer() and abs(n) >= 10 ** 6 and '.' not in m[1]:
            out.append(dict(value=m[1], cls='id', key=None, event=event, origin=origin, neighbours=set()))
            continue
        weak = n.is_integer() and abs(n) < 10 and '$' not in m[0] and '.' not in m[1]
        out.append(dict(value=n, cls='num', key=None, event=event, origin=origin, neighbours=set(), weak=weak))
    return out


def shape(v):
    """Leading letters of an ID (prefix), used so ID alternatives stay within the same ID family."""
    m = re.match(r'[A-Za-z]*', str(v))
    return (m[0].lower(), str(v).count('_'), str(v).count('-'))


def policy_numbers(store, key):
    """Numbers on a policy line that mentions the argument name (e.g. `fee_usd` = 50)."""
    if not key or len(key) < 3:
        return []
    out = []
    for e in store.history_events:
        if e.role != 'system':
            continue
        for line in e.text.splitlines():
            if key in line:
                for m in NUM_TXT.finditer(line):
                    n = _num(m[1])
                    if n is not None:
                        out.append(n)
    return out


def _same(a, b):
    if isinstance(a, (int, float)) and isinstance(b, (int, float)) and not isinstance(a, bool) and not isinstance(b, bool):
        return float(a) == float(b)
    return a == b


def _cast(alt, cur):
    if isinstance(cur, int) and not isinstance(cur, bool) and isinstance(alt, float) and alt.is_integer():
        return int(alt)
    return alt


def _set_path(value, path, new):
    value = json.loads(json.dumps(value))
    cur = value
    for p in path[:-1]:
        cur = cur[p]
    cur[path[-1]] = new
    return value


def _arg_alternatives(store, obs, call_values, key, cur, cls):
    scored = []
    if cls == 'bool':
        return [not cur]
    for o in obs:
        if o['cls'] != cls or _same(o['value'], cur):
            continue
        s = 0
        if key and o['key'] == key:
            s = 3
        elif o['neighbours'] & call_values:
            s = 2
        elif o['origin'] == 'user':
            s = 1
        if cls == 'str' and s < 3:
            continue                       # free strings only from the same key
        if cls == 'id' and s < 3 and shape(o['value']) != shape(cur):
            continue                       # IDs only within the same ID family unless same key
        if s == 0:
            continue
        scored.append((s, o['event'], o['value']))
    if cls == 'num':
        scored += [(2, 10 ** 6, n) for n in policy_numbers(store, key) if not _same(n, cur)]
    out = []
    for s, ev, v in sorted(scored, key=lambda x: (-x[0], -x[1])):
        v = _cast(v, cur)
        if not any(_same(v, x) for x in out):
            out.append(v)
        if len(out) >= PER_LEAF:
            break
    return out


def build(store, target_ids=None):
    """-> list of variants dict(variant_id, target_id, kind, path, original, replacement, text)."""
    obs = observations(store)
    groups, omits = [], []
    for ti, e in enumerate(store.target_events):
        tid = (target_ids or {}).get(ti, f't{ti}')
        if e.kind == 'call':
            omits.append(dict(target_id=tid, kind='OMIT_CALL', path=None, original=e.name, replacement=None,
                              text=f'{tid}: the call {e.name} is NOT made (the assistant replies to the user instead)'))
            if not e.json_valid:
                continue
            call_values = {json.dumps(v, ensure_ascii=False) for _, _, v in leaves(e.value) if vclass(v)}
            for path, key, cur in leaves(e.value):
                cls = vclass(cur)
                if not cls:
                    continue
                g = []
                for alt in _arg_alternatives(store, obs, call_values, key, cur, cls):
                    new = _set_path(e.value, path, alt)
                    g.append(dict(target_id=tid, kind='ARG', path='.'.join(map(str, path)), original=cur, replacement=alt,
                                  text=f'{tid}: {e.name} {json.dumps(new, ensure_ascii=False)}'))
                if g:
                    groups.append(g)
        elif e.kind == 'text':
            text = e.text
            vals = _text_values(text, -1, 'target')
            vals.sort(key=lambda v: bool(v.get('weak')))   # small bare integers last
            seen = set()
            for v in vals:
                k = (v['cls'], str(v['value']))
                if k in seen:
                    continue
                seen.add(k)
                alts = []
                for o in sorted(obs, key=lambda o: -o['event']):
                    if o['cls'] != v['cls'] or _same(o['value'], v['value']) or any(_same(o['value'], a) for a in alts):
                        continue
                    if v['cls'] == 'num':
                        if v['value'] == 0 or not (0.5 <= abs(o['value'] / v['value']) <= 2 if v['value'] else False):
                            continue
                    if v['cls'] == 'id' and shape(o['value']) != shape(v['value']):
                        continue
                    alts.append(o['value'])
                if v['cls'] == 'num':
                    alts.sort(key=lambda a: abs(a - v['value']))
                alts = alts[:2]
                g = [dict(target_id=tid, kind='PROSE_VALUE', path=None, original=v['value'], replacement=a,
                          text=f'{tid}: same prose but {_fmt(v["value"])} replaced by {_fmt(a)}') for a in alts]
                if g:
                    groups.append(g)
            sents = [LIST_MARK.sub('', s).strip() for s in SENT.split(text)]
            sents = [s for s in sents if len(re.findall(r'\w+', s)) >= 4]
            with_val = [s for s in sents if any(not v.get('weak') for v in _text_values(s, -1, 't'))] or sents[:3]
            for s in with_val[:4]:
                omits.append(dict(target_id=tid, kind='OMIT_SENTENCE', path=None, original=s, replacement=None,
                                  text=f'{tid}: same prose but WITHOUT the sentence: "{s}"'))
    out = list(omits[:MAX_OMITS])
    i = 0
    while len(out) < MAX_VARIANTS and any(groups):
        g = groups[i % len(groups)]
        if g:
            out.append(g.pop(0))
        i += 1
        if i > 1000:
            break
    for n, v in enumerate(out):
        v['variant_id'] = f'V{n + 1}'
    return out


def _fmt(v):
    if isinstance(v, float) and v.is_integer():
        return str(int(v))
    return str(v)
