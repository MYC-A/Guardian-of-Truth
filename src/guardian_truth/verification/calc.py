"""Code-computed CALCULATIONS (exact arithmetic only; relevance and meaning are NOT implied):
for every ISO date/datetime in the current move and the packet history: difference to the policy's
stated current time (days, hours), weekday, and age in full years for dates >= 10 years before now.
Plus a safe evaluator for 'expression = result' strings written by the model."""
from __future__ import annotations

import ast
import datetime as dt
import json
import operator
import re

NOW = re.compile(r'current (?:time|date) is (\d{4}-\d{2}-\d{2})(?:[ T](\d{2}:\d{2})(?::\d{2})?)?', re.I)
ISO = re.compile(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2})(?::\d{2})?)?(?!\d)')
MAX_ROWS = 40


def now_of(packet):
    for s in packet['normative_sources']:
        m = NOW.search(s['text'])
        if m:
            return _parse(m[1], m[2])
    return None


def _parse(d, t=None):
    try:
        return dt.datetime.fromisoformat(d + ('T' + t if t else 'T00:00')), bool(t)
    except ValueError:
        return None


def table(packet):
    n = now_of(packet)
    if n is None:
        return dict(reference_now=None, rows=[], note='no current time stated in the retrieved policy')
    now, now_has_time = n
    seen, rows = set(), []
    recs = list(packet['current_targets']) + sorted(packet['history'], key=lambda r: -(r['event'] if r['event'] is not None else -1))
    for r in recs:
        for m in ISO.finditer(r['text'] or ''):
            key = (m[1], m[2])
            if key in seen:
                continue
            p = _parse(m[1], m[2])
            if p is None:
                continue
            seen.add(key)
            d, has_time = p
            row = dict(value=m[0], first_seen_in=r['source_id'], weekday=d.strftime('%A'),
                       calendar_days_from_today=(d.date() - now.date()).days)
            if has_time:
                row['hours_from_now'] = round((d - now).total_seconds() / 3600, 1)
            if (now - d).days >= 3650:
                row['age_years_now'] = now.year - d.year - ((now.month, now.day) < (d.month, d.day))
            rows.append(row)
            if len(rows) >= MAX_ROWS:
                break
        if len(rows) >= MAX_ROWS:
            break
    return dict(reference_now=now.isoformat(sep=' ', timespec='minutes'), reference_weekday=now.strftime('%A'), rows=rows,
                note='Exact code arithmetic relative to the current time stated in the policy. It does not say which value matters.')


OPS = {ast.Add: operator.add, ast.Sub: operator.sub, ast.Mult: operator.mul, ast.Div: operator.truediv, ast.USub: operator.neg, ast.UAdd: operator.pos}


def _eval(node):
    if isinstance(node, ast.Expression):
        return _eval(node.body)
    if isinstance(node, ast.Constant) and isinstance(node.value, (int, float)) and not isinstance(node.value, bool):
        return node.value
    if isinstance(node, ast.BinOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.left), _eval(node.right))
    if isinstance(node, ast.UnaryOp) and type(node.op) in OPS:
        return OPS[type(node.op)](_eval(node.operand))
    raise ValueError('unsupported')


_CMP = re.compile(r'(?<![\w.:/\-])(\d+(?:\.\d+)?)\s*(<=|>=|≤|≥|<|>)\s*(\d+(?:\.\d+)?)(?![\w.:/\-])')


def check_comparisons(text):
    """All 'a OP b' numeric comparisons in text -> True if all hold, False if any fails, None if none."""
    if not isinstance(text, str):
        return None
    t = text.replace(',', '')
    found = _CMP.findall(t)
    if not found:
        return None
    ops = {'<': lambda a, b: a < b, '>': lambda a, b: a > b, '<=': lambda a, b: a <= b, '≤': lambda a, b: a <= b,
           '>=': lambda a, b: a >= b, '≥': lambda a, b: a >= b}
    return all(ops[o](float(a), float(b)) for a, o, b in found)


def check_computation(text):
    """'(67 - 42) * 4 = 100' -> True/False; also 'a < b' comparisons; None if no checkable claim."""
    cmp_ok = check_comparisons(text)
    if cmp_ok is False:
        return False
    arith = _check_arith(text)
    if arith is None:
        return cmp_ok
    return arith


def _check_arith(text):
    if not isinstance(text, str) or '=' not in text:
        return None
    left, _, right = text.rpartition('=')
    left = left.replace('×', '*').replace('−', '-').replace(',', '').replace('$', '').replace('€', '').replace('£', '')
    right = right.replace(',', '').replace('$', '').replace('€', '').replace('£', '').strip()
    left = left.split('=')[-1]
    if not re.fullmatch(r'[\d\s.+\-*/()]+', left.strip() or 'x') or not re.fullmatch(r'-?\d+(?:\.\d+)?', right):
        return None
    try:
        v = _eval(ast.parse(left.strip(), mode='eval'))
    except (ValueError, SyntaxError, ZeroDivisionError):
        return None
    r = float(right)
    return abs(v - r) <= max(0.006, 1e-4 * abs(r))      # rounding to cents tolerated
