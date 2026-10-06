"""Exact numbers and instants (contract 4, execution). Decimal arithmetic; equality of a computed value with a STATED
value is exact after rounding the computed value to the stated precision (no relative tolerance: 100000 != 100009).
Datetimes keep seconds and timezone; an aware and a naive instant are incomparable (never silently equal)."""
from __future__ import annotations

import datetime as dt
from decimal import Decimal, InvalidOperation, ROUND_HALF_UP
import re

from ..verification import derived as D


def tok_dec(tok):
    t = re.sub(r'[ \u00a0\u202f]', '', tok)
    if re.fullmatch(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?', t):
        t = t.replace(',', '')
    elif re.fullmatch(r'-?\d+,\d+', t):
        t = t.replace(',', '.')
    try:
        return Decimal(t)
    except InvalidOperation:
        return None


def numbers(text):
    """[(Decimal, start, end)] in order of appearance (same tokenizer as derived.NUM_RE)."""
    out = []
    for m in D.NUM_RE.finditer(text or ''):
        v = tok_dec(m.group(0))
        if v is not None:
            out.append((v, m.start(), m.end()))
    return out


def to_dec(x):
    if isinstance(x, bool) or x is None:
        return None
    if isinstance(x, Decimal):
        return x
    if isinstance(x, int):
        return Decimal(x)
    if isinstance(x, float):
        return Decimal(repr(x))
    ns = numbers(str(x))
    return ns[0][0] if len(ns) == 1 else None


def eq(a, b):
    a, b = to_dec(a), to_dec(b)
    return a is not None and b is not None and a == b


def stated_equal(computed, stated):
    """computed (exact) vs a value a source/move STATES: equal iff computed rounded half-up to the stated precision
    (the written decimals; an integer statement is held to cents) equals the stated value. '33.33' states 100/3
    correctly; '100009' does not state 100000; '278' does not state 278.04."""
    if isinstance(stated, float) and stated.is_integer():
        stated = int(stated)
    c, s = to_dec(computed), to_dec(stated)
    if c is None or s is None:
        return False
    if c == s:
        return True
    exp = s.as_tuple().exponent
    exp = exp if isinstance(exp, int) and exp < 0 else -2          # written decimals, else at least cents
    return c.quantize(Decimal(1).scaleb(exp), rounding=ROUND_HALF_UP) == s


def fmt(x):
    """Same text as V4's `{x:g}` so unchanged candidates keep byte-identical verifier requests."""
    return f'{float(x):g}'


TZ = {'UTC': 0, 'GMT': 0, 'Z': 0, 'EST': -5, 'EDT': -4, 'CST': -6, 'CDT': -5, 'MST': -7, 'MDT': -6, 'PST': -8, 'PDT': -7,
      'CET': 1, 'CEST': 2, 'EET': 2, 'EEST': 3, 'MSK': 3}
DT_RE = re.compile(r'(?<!\d)(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}):(\d{2})(?::(\d{2})(?:\.(\d{1,6}))?)?)?'
                   r'(?:\s?(Z|[+-]\d{2}:?\d{2}|UTC|GMT|E[SD]T|C[SD]T|M[SD]T|P[SD]T|CES?T|EES?T|MSK)(?![A-Za-z]))?(?!\d)')


def _tz(s):
    if not s:
        return None
    if s in TZ:
        return dt.timezone(dt.timedelta(hours=TZ[s]))
    m = re.fullmatch(r'([+-])(\d{2}):?(\d{2})', s)
    sign = 1 if m[1] == '+' else -1
    return dt.timezone(sign * dt.timedelta(hours=int(m[2]), minutes=int(m[3])))


def datetimes(text):
    """[(datetime, start, end)] with seconds/fraction and tz (aware when a zone is written)."""
    out = []
    for m in DT_RE.finditer(str(text or '')):
        try:
            d = dt.date.fromisoformat(m[1])
            if m[2] is None:
                v = dt.datetime(d.year, d.month, d.day, tzinfo=_tz(m[6]))
            else:
                us = int((m[5] or '0').ljust(6, '0'))
                v = dt.datetime(d.year, d.month, d.day, int(m[2]), int(m[3]), int(m[4] or 0), us, tzinfo=_tz(m[6]))
        except ValueError:
            continue
        out.append((v, m.start(), m.end()))
    return out


def parse_datetime(s):
    ds = {v for v, _, _ in datetimes(s)}
    return ds.pop() if len(ds) == 1 else None


def comparable(a, b):
    if isinstance(a, dt.datetime) and isinstance(b, dt.datetime):
        return (a.tzinfo is None) == (b.tzinfo is None)
    return True
