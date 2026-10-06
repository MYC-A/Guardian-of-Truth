"""V4 typed proof executor (no model calls). A proof plan states the condition that must HOLD for the current move
to comply; every leaf operand is bound to one source (source_id + verbatim quote + value + type) and verified
independently; code parses the values, executes the closed-set operation and returns HOLDS / VIOLATED / UNRESOLVED.
Derived values (e.g. 400 + 900 = 1300) never need to exist in the input; every leaf does. Any unverifiable leaf,
wrong type, duplicate leaf, missing source or unknown operation -> UNRESOLVED (never VIOLATED)."""
from __future__ import annotations

import datetime as dt
import json
import re

from . import derived as D
from .common import MD, norm_ws, quote_q2

CMP = {'EQ': lambda a, b: a == b, 'NE': lambda a, b: a != b, 'LT': lambda a, b: a < b, 'LE': lambda a, b: a <= b,
       'GT': lambda a, b: a > b, 'GE': lambda a, b: a >= b}
OPS = ['EQ', 'NE', 'LT', 'LE', 'GT', 'GE', 'SUM', 'SUM_COMPARE_LT', 'SUM_COMPARE_LE', 'SUM_COMPARE_GT', 'SUM_COMPARE_GE',
       'ADD', 'SUB', 'MUL', 'DIV', 'DATE_DIFF_DAYS', 'DATE_DIFF_NIGHTS', 'WEEKDAY_OF', 'ADD_DAYS', 'ADD_BUSINESS_DAYS',
       'NEXT_BUSINESS_DAY', 'BEFORE', 'AFTER', 'LATEST_VALUE_EQ', 'MEMBER_OF', 'NOT_MEMBER_OF']
ROLES = ['left', 'right', 'term', 'bound', 'result', 'start', 'end', 'date', 'n', 'observed', 'value', 'member']
TYPES = ['number', 'date', 'datetime', 'string', 'weekday']
# operation -> (required single roles, repeated roles (>=1), allowed types per role)
SIG = {**{k: (('left', 'right'), (), None) for k in CMP},
       **{f'SUM_COMPARE_{k}': (('bound',), ('term',), 'number') for k in ('LT', 'LE', 'GT', 'GE')},
       'SUM': (('result',), ('term',), 'number'),
       **{k: (('left', 'right', 'result'), (), 'number') for k in ('ADD', 'SUB', 'MUL', 'DIV')},
       'DATE_DIFF_DAYS': (('start', 'end', 'result'), (), None), 'DATE_DIFF_NIGHTS': (('start', 'end', 'result'), (), None),
       'WEEKDAY_OF': (('date', 'result'), (), None), 'ADD_DAYS': (('date', 'n', 'result'), (), None),
       'ADD_BUSINESS_DAYS': (('date', 'n', 'result'), (), None), 'NEXT_BUSINESS_DAY': (('date', 'result'), (), None),
       'BEFORE': (('left', 'right'), (), None), 'AFTER': (('left', 'right'), (), None),
       'LATEST_VALUE_EQ': (('value',), ('observed',), None), 'MEMBER_OF': (('value',), ('member',), None),
       'NOT_MEMBER_OF': (('value',), ('member',), None)}
DATE_ROLES = {'start', 'end', 'date'}
PAIR = re.compile(r'"([^"\\]{1,80})"\s*:\s*("(?:[^"\\]|\\.)*"|-?\d+(?:\.\d+)?|true|false|null|\[\]|\{\})')
DT_RE = re.compile(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2})?)?(?!\d)')


def json_leaves_ok(quote, text):
    """A quote written as JSON key/value pairs is grounded leaf-by-leaf: every `"key": value` pair must occur in the
    source (whitespace-insensitive). Needs >= 1 pair; non-pair residue other than JSON punctuation is not allowed."""
    q = MD.sub('', quote or '')
    pairs = PAIR.findall(q)
    if not pairs:
        return False
    rest = PAIR.sub('', q)
    if re.sub(r'[\s{}\[\],:….]+', '', rest):
        return False
    for k, v in pairs:
        tail = r'(?![\w.])' if not v.startswith('"') else ''
        if not re.search(r'"' + re.escape(k) + r'"\s*:\s*' + re.escape(v) + tail, text or ''):
            return False
    return True


def numbers_grounded(quote, text):
    """Every number written in the quote also occurs in the source (Q2's near-verbatim word match tolerates a changed
    word, which must never be a changed number)."""
    have = D.numbers(text)
    return all(any(D.num_equal(x, y) for y in have) for x in D.numbers(quote))


def leaf_quote_ok(quote, text):
    if not quote or not text:
        return False
    return (quote_q2(quote, [text]) and numbers_grounded(quote, text)) or json_leaves_ok(quote, text)


def _norm_str(s):
    return norm_ws(str(s)).strip(' "\'«»“”`').lower()


def _datetime(s):
    m = DT_RE.search(str(s or ''))
    if not m:
        return None
    try:
        return dt.datetime.fromisoformat(m[1] + 'T' + (m[2] or '00:00'))
    except ValueError:
        return None


def parse_leaf(o, texts, now=None):
    """-> (value, None) or (None, NOTE). The value must be present in the verified quote of its own source."""
    sid, quote, typ = o.get('source_id'), o.get('quote') or '', o.get('type')
    src = texts.get(sid)
    if src is None:
        return None, 'SOURCE_MISSING'
    if not leaf_quote_ok(quote, src):
        return None, 'QUOTE_NOT_VERIFIED'
    raw = o.get('value')
    if typ == 'number':
        v = D.parse_number(raw)
        if v is None:
            return None, 'VALUE_NOT_PARSED'
        if v == 0 and o.get('role') == 'term' and re.fullmatch(r'\s*\{?\s*"[^"]+"\s*:\s*\[\s*\]\s*\}?\s*', MD.sub('', quote)):
            return 0.0, None                          # an empty JSON list contributes nothing to a sum
        return (v, None) if any(D.num_equal(v, y) for y in D.numbers(quote)) else (None, 'VALUE_NOT_IN_QUOTE')
    if typ == 'date':
        v = D.parse_date(raw, now)
        if v is None:
            return None, 'VALUE_NOT_PARSED'
        return (v, None) if v in {x for x, _ in D.dates(quote, now)} else (None, 'VALUE_NOT_IN_QUOTE')
    if typ == 'datetime':
        v = _datetime(raw)
        if v is None:
            return None, 'VALUE_NOT_PARSED'
        qd = {_datetime(m[0]) for m in DT_RE.finditer(quote)}
        return (v, None) if v in qd else (None, 'VALUE_NOT_IN_QUOTE')
    if typ == 'weekday':
        v = D.parse_weekday(raw)
        if v is None:
            return None, 'VALUE_NOT_PARSED'
        return (v, None) if v in D.weekdays(quote) else (None, 'VALUE_NOT_IN_QUOTE')
    if typ == 'string':
        v = _norm_str(raw)
        if not v:
            return None, 'VALUE_NOT_PARSED'
        return (v, None) if v in _norm_str(MD.sub('', quote)) else (None, 'VALUE_NOT_IN_QUOTE')
    return None, 'BAD_TYPE'


def _order(sid):
    """Event order of a source id: history hN in prompt order, then current targets tN."""
    m = re.fullmatch(r'([ht])(\d+)', sid or '')
    if not m:
        return -1
    return int(m[2]) + (10 ** 6 if m[1] == 't' else 0)


def execute(plan, texts, target_ids, now=None):
    """plan = {operation, target_ids, operands:[{role, source_id, quote, value, type}]}; texts = source_id -> text;
    target_ids = ids of the current move. -> dict(status HOLDS|VIOLATED|UNRESOLVED, note, detail, leaves)."""
    op = plan.get('operation')
    if op not in SIG:
        return dict(status='UNRESOLVED', note='UNKNOWN_OPERATION')
    ops = plan.get('operands') or []
    pt = plan.get('target_ids') or []
    if not pt or any(t not in target_ids for t in pt):
        return dict(status='UNRESOLVED', note='BAD_TARGET_IDS')
    single, repeated, ntype = SIG[op]
    by = {}
    for o in ops:
        by.setdefault(o.get('role'), []).append(o)
    if set(by) - set(single) - set(repeated):
        return dict(status='UNRESOLVED', note='UNEXPECTED_ROLE')
    if any(len(by.get(r, [])) != 1 for r in single) or any(not by.get(r) for r in repeated):
        return dict(status='UNRESOLVED', note='OPERANDS_MISSING')
    keys = [(o.get('source_id'), norm_ws(MD.sub('', o.get('quote') or '')).lower(), str(o.get('value')).strip()) for o in ops]
    if len(set(keys)) != len(keys):
        return dict(status='UNRESOLVED', note='DUPLICATE_OPERAND')
    if not any(o.get('source_id') in target_ids for o in ops):
        return dict(status='UNRESOLVED', note='NO_TARGET_OPERAND')
    vals, leaves = {}, []
    for o in ops:
        r = o.get('role')
        if ntype and o.get('type') != ntype:
            return dict(status='UNRESOLVED', note='WRONG_TYPE', role=r)
        if r in DATE_ROLES and o.get('type') not in ('date', 'datetime'):
            return dict(status='UNRESOLVED', note='WRONG_TYPE', role=r)
        v, err = parse_leaf(o, texts, now)
        if err:
            return dict(status='UNRESOLVED', note=err, role=r, source_id=o.get('source_id'))
        vals.setdefault(r, []).append((v, o))
        leaves.append(dict(role=r, source_id=o.get('source_id'), value=v if not isinstance(v, (dt.date, dt.datetime)) else v.isoformat(),
                           type=o.get('type')))
    one = {r: vals[r][0][0] for r in single}
    many = {r: [v for v, _ in vals[r]] for r in repeated}
    try:
        holds, detail = _run(op, one, many, vals)
    except (TypeError, ValueError, ZeroDivisionError, OverflowError) as ex:
        return dict(status='UNRESOLVED', note=f'EXEC_ERROR:{type(ex).__name__}', leaves=leaves)
    if holds is None:
        return dict(status='UNRESOLVED', note=detail, leaves=leaves)
    return dict(status='HOLDS' if holds else 'VIOLATED', detail=detail, leaves=leaves, operation=op)


def _same_kind(a, b):
    num = (int, float)
    if isinstance(a, num) and isinstance(b, num):
        return True
    return type(a) is type(b)


def _f(x):
    return x.isoformat() if isinstance(x, (dt.date, dt.datetime)) else f'{x:g}' if isinstance(x, float) else str(x)


def _run(op, one, many, vals):
    if op in CMP:
        a, b = one['left'], one['right']
        if not _same_kind(a, b) or (isinstance(a, str) and op not in ('EQ', 'NE')):
            return None, 'INCOMPARABLE_TYPES'
        return CMP[op](a, b), f'{_f(a)} {op} {_f(b)}'
    if op.startswith('SUM_COMPARE_'):
        s = sum(many['term'])
        k = op.rsplit('_', 1)[1]
        return CMP[k](s, one['bound']), ' + '.join(_f(x) for x in many['term']) + f' = {_f(s)}; {_f(s)} {k} {_f(one["bound"])} required'
    if op == 'SUM':
        s = sum(many['term'])
        return D.num_equal(s, one['result']), ' + '.join(_f(x) for x in many['term']) + f' = {_f(s)} (stated {_f(one["result"])})'
    if op in ('ADD', 'SUB', 'MUL', 'DIV'):
        a, b = one['left'], one['right']
        c = {'ADD': a + b, 'SUB': a - b, 'MUL': a * b, 'DIV': a / b}[op]
        sym = {'ADD': '+', 'SUB': '-', 'MUL': '*', 'DIV': '/'}[op]
        return D.num_equal(c, one['result']), f'{_f(a)} {sym} {_f(b)} = {_f(c)} (stated {_f(one["result"])})'
    if op in ('DATE_DIFF_DAYS', 'DATE_DIFF_NIGHTS'):
        a, b, r = one['start'], one['end'], one['result']
        if not isinstance(r, float):
            return None, 'WRONG_TYPE'
        a, b = (a.date() if isinstance(a, dt.datetime) else a), (b.date() if isinstance(b, dt.datetime) else b)
        n = (b - a).days
        return D.num_equal(n, r), f'{_f(a)} -> {_f(b)} = {n} {"nights" if op.endswith("NIGHTS") else "days"} (stated {_f(r)})'
    if op == 'WEEKDAY_OF':
        d, w = one['date'], one['result']
        if not isinstance(w, int):
            return None, 'WRONG_TYPE'
        return d.weekday() == w, f'{_f(d)} is {D.WEEKDAYS[d.weekday()][1]} (stated {D.WEEKDAYS[w][1]})'
    if op in ('ADD_DAYS', 'ADD_BUSINESS_DAYS', 'NEXT_BUSINESS_DAY'):
        d, r = one['date'], one['result']
        d = d.date() if isinstance(d, dt.datetime) else d
        r = r.date() if isinstance(r, dt.datetime) else r
        if not isinstance(r, dt.date):
            return None, 'WRONG_TYPE'
        if op == 'NEXT_BUSINESS_DAY':
            c = D.next_business_day(d)
        else:
            n = one['n']
            if not isinstance(n, float) or n != int(n) or not 0 <= n <= 366:
                return None, 'BAD_N'
            c = d + dt.timedelta(days=int(n)) if op == 'ADD_DAYS' else D.add_business_days(d, int(n))
        return c == r, f'{op}({_f(d)}{", " + _f(one["n"]) if "n" in one else ""}) = {_f(c)} (stated {_f(r)})'
    if op in ('BEFORE', 'AFTER'):
        a, b = one['left'], one['right']
        if not isinstance(a, (dt.date, dt.datetime)) or not isinstance(b, (dt.date, dt.datetime)):
            return None, 'WRONG_TYPE'
        if type(a) is not type(b):
            a, b = (a.date() if isinstance(a, dt.datetime) else a), (b.date() if isinstance(b, dt.datetime) else b)
        return (a < b) if op == 'BEFORE' else (a > b), f'{_f(a)} {op} {_f(b)}'
    if op == 'LATEST_VALUE_EQ':
        obs = sorted(vals['observed'], key=lambda vo: _order(vo[1].get('source_id')))
        if any(_order(o.get('source_id')) < 0 or o.get('source_id', '').startswith('t') for _, o in obs):
            return None, 'OBSERVED_NOT_IN_HISTORY'
        latest, src = obs[-1][0], obs[-1][1].get('source_id')
        v = one['value']
        if not _same_kind(v, latest):
            return None, 'INCOMPARABLE_TYPES'
        eq = D.num_equal(v, latest) if isinstance(v, float) else v == latest
        return eq, f'latest observed value ({src}) = {_f(latest)}; used {_f(v)}'
    if op in ('MEMBER_OF', 'NOT_MEMBER_OF'):
        v = one['value']
        mem = many['member']
        if not all(_same_kind(v, m) for m in mem):
            return None, 'INCOMPARABLE_TYPES'
        inside = any((D.num_equal(v, m) if isinstance(v, float) else v == m) for m in mem)
        return inside if op == 'MEMBER_OF' else not inside, f'{_f(v)} {"in" if inside else "not in"} {{' + ', '.join(_f(m) for m in mem) + '}'
    return None, 'UNKNOWN_OPERATION'


def texts_of(packet, extra=()):
    t = {s['source_id']: s['text'] for k in ('normative_sources', 'history', 'declarations', 'current_targets') for s in packet[k]}
    t.update({s['source_id']: s['text'] for s in extra})
    return t
