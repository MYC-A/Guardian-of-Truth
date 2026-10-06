"""Typed consistency check of a pre-analysis' OWN condition checks (no model, no solver).
Input : one condition_check = {expression, bindings:[{name, value, type, source_id}], claimed_result, ...} and the
        packet's sources (source_id -> exact text).
Output: per-check statuses, kept separate on purpose:
  source_status      each binding value found in its cited source (VERBATIM / NUMERIC_EQUAL / NOT_FOUND / NO_SOURCE)
  interpretation     always MODEL   (code never checks that the expression is what the policy means, nor exceptions)
  binding            always MODEL   (code never checks that the value belongs to the right entity / role)
  computation        OK / PARSE_ERROR / UNBOUND:<name> / TYPE_ERROR / NOT_BOOLEAN    (the arithmetic/logic only)
  consistency        CONSISTENT / CONTRADICTION / UNEVALUABLE   (claimed_result vs computed value; UNKNOWN claim -> UNEVALUABLE)
A CONTRADICTION proves only that the claimed result does not follow from the analysis' own expression and bindings.
Grammar: AND OR NOT, > >= < <= == !=, + - * /, parentheses, numbers, 'strings', dotted names, days_between(a,b),
hours_between(a,b) (b - a). Values are typed by the binding: NUMBER -> Decimal of the exact string, DATE/DATETIME ->
ISO-8601, BOOL -> true/false, STRING -> exact string (no case folding: equal names are not equal entities)."""
from __future__ import annotations

import ast, re
from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

WORDS = [(re.compile(r'\bAND\b', re.I), ' and '), (re.compile(r'\bOR\b', re.I), ' or '), (re.compile(r'\bNOT\b', re.I), ' not '),
         (re.compile(r'\bTRUE\b', re.I), ' True '), (re.compile(r'\bFALSE\b', re.I), ' False ')]
CMP = {ast.Gt: lambda a, b: a > b, ast.GtE: lambda a, b: a >= b, ast.Lt: lambda a, b: a < b, ast.LtE: lambda a, b: a <= b,
       ast.Eq: lambda a, b: a == b, ast.NotEq: lambda a, b: a != b}
BIN = {ast.Add: lambda a, b: a + b, ast.Sub: lambda a, b: a - b, ast.Mult: lambda a, b: a * b, ast.Div: lambda a, b: a / b}
NUM = re.compile(r'-?\d+(?:[.,]\d+)*')


class Fail(Exception):
    pass


def _dt(s):
    s = str(s).strip()
    try:
        if len(s) == 10:
            return datetime.combine(date.fromisoformat(s), datetime.min.time(), tzinfo=timezone.utc)
        d = datetime.fromisoformat(s.replace('Z', '+00:00'))
        return d if d.tzinfo else d.replace(tzinfo=timezone.utc)
    except ValueError:
        raise Fail('TYPE_ERROR')


def typed(b):
    t, v = (b.get('type') or 'STRING').upper(), b.get('value')
    try:
        if t == 'NUMBER':
            return Decimal(str(v).strip().replace(',', ''))
        if t in ('DATE', 'DATETIME'):
            return _dt(v)
        if t == 'BOOL':
            s = str(v).strip().lower()
            if s not in ('true', 'false'):
                raise Fail('TYPE_ERROR')
            return s == 'true'
        return str(v).strip()
    except (InvalidOperation, ValueError):
        raise Fail('TYPE_ERROR')


def _name(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return _name(n.value) + '.' + n.attr
    raise Fail('PARSE_ERROR')


def _ev(n, env):
    if isinstance(n, ast.Expression):
        return _ev(n.body, env)
    if isinstance(n, ast.BoolOp):
        vals = [_ev(v, env) for v in n.values]
        if not all(isinstance(v, bool) for v in vals):
            raise Fail('TYPE_ERROR')
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        v = _ev(n.operand, env)
        if not isinstance(v, bool):
            raise Fail('TYPE_ERROR')
        return not v
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        return -_ev(n.operand, env)
    if isinstance(n, ast.Compare):
        left, out = _ev(n.left, env), True
        for op, c in zip(n.ops, n.comparators):
            right = _ev(c, env)
            if type(op) not in CMP:
                raise Fail('PARSE_ERROR')
            if not isinstance(op, (ast.Eq, ast.NotEq)) and not (isinstance(left, Decimal) and isinstance(right, Decimal)
                                                                    or isinstance(left, datetime) and isinstance(right, datetime)):
                raise Fail('TYPE_ERROR')
            if type(left) is not type(right):
                raise Fail('TYPE_ERROR')
            out = out and CMP[type(op)](left, right)
            left = right
        return out
    if isinstance(n, ast.BinOp):
        a, b = _ev(n.left, env), _ev(n.right, env)
        if type(n.op) not in BIN or not (isinstance(a, Decimal) and isinstance(b, Decimal)):
            raise Fail('TYPE_ERROR')
        if isinstance(n.op, ast.Div) and b == 0:
            raise Fail('TYPE_ERROR')
        return BIN[type(n.op)](a, b)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('days_between', 'hours_between') and len(n.args) == 2:
        a, b = (_ev(x, env) for x in n.args)
        if not (isinstance(a, datetime) and isinstance(b, datetime)):
            raise Fail('TYPE_ERROR')
        sec = Decimal((b - a).total_seconds())
        return sec / (86400 if n.func.id == 'days_between' else 3600)
    if isinstance(n, ast.Constant):
        if isinstance(n.value, bool):
            return n.value
        if isinstance(n.value, (int, float)):
            return Decimal(str(n.value))
        if isinstance(n.value, str):
            return n.value
        raise Fail('PARSE_ERROR')
    if isinstance(n, (ast.Name, ast.Attribute)):
        k = _name(n)
        if k not in env:
            raise Fail('UNBOUND:' + k)
        return env[k]
    raise Fail('PARSE_ERROR')


def compute(expression, bindings):
    """-> (status, value)"""
    s = str(expression or '').strip()
    s = re.sub(r'^\s*IF\s+(.*?)\s+THEN\b.*$', r'\1', s, flags=re.I | re.S)     # "IF cond THEN x" -> cond
    s = re.sub(r'(?<![<>=!])=(?!=)', '==', s)
    for rx, rep in WORDS:
        s = rx.sub(rep, s)
    try:
        tree = ast.parse(s.strip(), mode='eval')
    except SyntaxError:
        return 'PARSE_ERROR', None
    try:
        env = {}
        for b in bindings or []:
            env[str(b.get('name', '')).strip()] = typed(b)
        v = _ev(tree, env)
    except Fail as e:
        return str(e), None
    if not isinstance(v, bool):
        return 'NOT_BOOLEAN', None
    return 'OK', v


def source_status(b, sources):
    sid, v = b.get('source_id'), str(b.get('value', '')).strip()
    txt = sources.get(sid)
    if txt is None:
        return 'NO_SOURCE'
    if v and v in txt:
        return 'VERBATIM'
    if (b.get('type') or '').upper() == 'NUMBER':
        try:
            d = Decimal(v.replace(',', ''))
            if any(Decimal(m.replace(',', '')) == d for m in NUM.findall(txt)):
                return 'NUMERIC_EQUAL'
        except InvalidOperation:
            pass
    return 'NOT_FOUND'


def check(c, sources):
    status, val = compute(c.get('expression'), c.get('bindings'))
    claimed = str(c.get('claimed_result') or 'UNKNOWN').upper()
    if status != 'OK' or claimed not in ('TRUE', 'FALSE'):
        cons = 'UNEVALUABLE'
    else:
        cons = 'CONSISTENT' if (claimed == 'TRUE') == val else 'CONTRADICTION'
    return dict(requirement_source_id=c.get('requirement_source_id'), expression=c.get('expression'), claimed_result=claimed,
                computation=status, computed=None if val is None else ('TRUE' if val else 'FALSE'), consistency=cons,
                interpretation='MODEL', binding='MODEL',
                source_status=[dict(name=b.get('name'), source_id=b.get('source_id'), status=source_status(b, sources)) for b in c.get('bindings') or []])
