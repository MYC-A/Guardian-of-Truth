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

import ast, io, re, tokenize
from datetime import date, datetime, timezone
from decimal import Decimal, DecimalException, Inexact, InvalidOperation, localcontext

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
            if isinstance(v, (bool, float)) or not isinstance(v, (str, int, Decimal)):
                raise Fail('TYPE_ERROR')
            d = Decimal(str(v).strip().replace(',', ''))
            if not d.is_finite():
                raise Fail('TYPE_ERROR')
            return d
        if t in ('DATE', 'DATETIME'):
            return _dt(v)
        if t == 'BOOL':
            s = str(v).strip().lower()
            if s not in ('true', 'false'):
                raise Fail('TYPE_ERROR')
            return s == 'true'
        if t != 'STRING' or not isinstance(v, str):
            raise Fail('TYPE_ERROR')
        return v
    except (InvalidOperation, ValueError):
        raise Fail('TYPE_ERROR')


def _name(n):
    if isinstance(n, ast.Name):
        return n.id
    if isinstance(n, ast.Attribute):
        return _name(n.value) + '.' + n.attr
    raise Fail('PARSE_ERROR')


def _ev(n, env, expression):
    if isinstance(n, ast.Expression):
        return _ev(n.body, env, expression)
    if isinstance(n, ast.BoolOp):
        vals = [_ev(v, env, expression) for v in n.values]
        if not all(isinstance(v, bool) for v in vals):
            raise Fail('TYPE_ERROR')
        return all(vals) if isinstance(n.op, ast.And) else any(vals)
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.Not):
        v = _ev(n.operand, env, expression)
        if not isinstance(v, bool):
            raise Fail('TYPE_ERROR')
        return not v
    if isinstance(n, ast.UnaryOp) and isinstance(n.op, ast.USub):
        v = _ev(n.operand, env, expression)
        if not isinstance(v, Decimal):
            raise Fail('TYPE_ERROR')
        return -v
    if isinstance(n, ast.Compare):
        left, out = _ev(n.left, env, expression), True
        for op, c in zip(n.ops, n.comparators):
            right = _ev(c, env, expression)
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
        a, b = _ev(n.left, env, expression), _ev(n.right, env, expression)
        if type(n.op) not in BIN or not (isinstance(a, Decimal) and isinstance(b, Decimal)):
            raise Fail('TYPE_ERROR')
        if isinstance(n.op, ast.Div) and b == 0:
            raise Fail('TYPE_ERROR')
        return BIN[type(n.op)](a, b)
    if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id in ('days_between', 'hours_between') and len(n.args) == 2 and not n.keywords:
        a, b = (_ev(x, env, expression) for x in n.args)
        if not (isinstance(a, datetime) and isinstance(b, datetime)):
            raise Fail('TYPE_ERROR')
        delta = b - a
        sec = Decimal(delta.days * 86400 + delta.seconds) + Decimal(delta.microseconds) / Decimal(1_000_000)
        return sec / (86400 if n.func.id == 'days_between' else 3600)
    if isinstance(n, ast.Constant):
        if isinstance(n.value, bool):
            return n.value
        if isinstance(n.value, (int, float)):
            # The AST float has already rounded the token; read the exact original token.
            token = ast.get_source_segment(expression, n)
            if not token or not re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', token):
                raise Fail('PARSE_ERROR')
            value = Decimal(token)
            if not value.is_finite():
                raise Fail('TYPE_ERROR')
            return value
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
    if not isinstance(expression, str) or len(expression) > 12000:
        return 'PARSE_ERROR', None
    try:
        tokens, numeric_literals = [], []
        words = {'AND': 'and', 'OR': 'or', 'NOT': 'not', 'TRUE': 'True', 'FALSE': 'False'}
        previous = None
        for token in tokenize.generate_tokens(io.StringIO(expression.strip()).readline):
            kind, text = token.type, token.string
            if kind == tokenize.NAME and previous != '.':
                if text.upper() in ('IF', 'THEN'):
                    return 'UNSUPPORTED_CONDITIONAL', None
                text = words.get(text.upper(), text)
            elif kind == tokenize.OP and text == '=':
                text = '=='
            elif kind == tokenize.NUMBER and re.fullmatch(r'(?:\d+(?:\.\d*)?|\.\d+)(?:[eE][+-]?\d+)?', text):
                numeric_literals.append(Decimal(text))
            elif kind in (tokenize.COMMENT, tokenize.ERRORTOKEN) and text.strip():
                return 'PARSE_ERROR', None
            tokens.append((kind, text))
            previous = text
        s = tokenize.untokenize(tokens).strip()
        tree = ast.parse(s, mode='eval')
    except (SyntaxError, tokenize.TokenError, IndentationError, ValueError, RecursionError, DecimalException):
        return 'PARSE_ERROR', None
    try:
        env = {}
        for b in bindings or []:
            if not isinstance(b, dict) or not isinstance(b.get('name'), str) or b['name'] in env:
                raise Fail('TYPE_ERROR')
            env[b['name']] = typed(b)
        # Bound work while retaining every input digit for supported decimal operations.
        numbers = numeric_literals + [v for v in env.values() if isinstance(v, Decimal)]
        precision = max(50, len(s) + sum(max(0, v.adjusted() + 1) + max(0, -v.as_tuple().exponent) for v in numbers) + 10)
        if precision > 20000:
            raise Fail('TYPE_ERROR')
        with localcontext() as ctx:
            ctx.prec = precision
            # Without an explicit rounding contract a rounded boolean comparison
            # cannot contradict a model claim. Repeating division is UNEVALUABLE.
            ctx.traps[Inexact] = True
            v = _ev(tree, env, s)
    except Fail as e:
        return str(e), None
    except (DecimalException, ArithmeticError, ValueError, TypeError, AttributeError, RecursionError):
        return 'TYPE_ERROR', None
    if not isinstance(v, bool):
        return 'NOT_BOOLEAN', None
    return 'OK', v


def source_status(b, sources):
    if not isinstance(b, dict) or not isinstance(sources, dict):
        return 'NO_SOURCE'
    sid, raw = b.get('source_id'), b.get('value', '')
    v = raw if isinstance(raw, str) else str(raw)
    txt = sources.get(sid)
    if txt is None:
        return 'NO_SOURCE'
    if v and v in txt:
        return 'VERBATIM'
    if str(b.get('type') or '').upper() == 'NUMBER':
        try:
            d = Decimal(v.replace(',', ''))
            if not d.is_finite():
                return 'NOT_FOUND'
            if any(Decimal(m.replace(',', '')) == d for m in NUM.findall(txt)):
                return 'NUMERIC_EQUAL'
        except InvalidOperation:
            pass
    return 'NOT_FOUND'


def check(c, sources):
    if not isinstance(c, dict):
        c = {}
    status, val = compute(c.get('expression'), c.get('bindings'))
    claimed = str(c.get('claimed_result') or 'UNKNOWN').upper()
    if status != 'OK' or claimed not in ('TRUE', 'FALSE'):
        cons = 'UNEVALUABLE'
    else:
        cons = 'CONSISTENT' if (claimed == 'TRUE') == val else 'CONTRADICTION'
    return dict(requirement_source_id=c.get('requirement_source_id'), expression=c.get('expression'), claimed_result=claimed,
                computation=status, computed=None if val is None else ('TRUE' if val else 'FALSE'), consistency=cons,
                interpretation='MODEL', binding='MODEL',
                source_status=[dict(name=b.get('name'), source_id=b.get('source_id'), status=source_status(b, sources))
                               for b in (c.get('bindings') if isinstance(c.get('bindings'), list) else []) if isinstance(b, dict)])
