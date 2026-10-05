"""Deterministic parsing and calendar/arithmetic operations for the derived-facts checker (amendment 4).
No model calls. Numbers: '1 020.00', '1 050,00', '1,050.00', '€540', '540 руб.'. Dates: ISO, dd.mm[.yyyy],
'18 февраля [2025]', 'February 18[, 2025]', '18 Feb'. Year-less dates take the year closest to the policy's
current time. Weekdays: ru (all case forms) / en. Business days = Mon-Fri (no holiday calendar)."""
from __future__ import annotations

import ast
import datetime as dt
import re

from .calc import _eval

RU_MONTHS = {'январ': 1, 'феврал': 2, 'март': 3, 'апрел': 4, 'июн': 6, 'июл': 7, 'август': 8, 'сентябр': 9,
             'октябр': 10, 'ноябр': 11, 'декабр': 12}
EN_MONTHS = {m: i + 1 for i, m in enumerate(('jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec'))}
RU_MON_RE = r'(январ[яеь]|феврал[яеь]|марта|марте|март|апрел[яеь]|ма[яйе]|июн[яеь]|июл[яеь]|августа|августе|август|сентябр[яеь]|октябр[яеь]|ноябр[яеь]|декабр[яеь])'
EN_MON_RE = r'(jan(?:uary)?|feb(?:ruary)?|mar(?:ch)?|apr(?:il)?|may|june?|july?|aug(?:ust)?|sep(?:t(?:ember)?)?|oct(?:ober)?|nov(?:ember)?|dec(?:ember)?)\.?'
RANGE_RE = re.compile(r'(?<![\d.:])(\d{1,2})\s*(?:-|–|—|по|до|to|and|и)\s*(\d{1,2})\s+(' + RU_MON_RE[1:-1] + '|' + EN_MON_RE[1:-4] + r')(?!\w)(?:\s+(\d{4}))?', re.I)
ISO_RE = re.compile(r'(?<!\d)(\d{4})-(\d{2})-(\d{2})(?!\d)')
DMY_RE = re.compile(r'(?<![\d.])(\d{1,2})\.(\d{1,2})(?:\.(\d{4}|\d{2}))?(?![\d])')
RU_RE = re.compile(r'(?<!\d)(\d{1,2})\s+' + RU_MON_RE + r'(?!\w)(?:\s+(\d{4}))?', re.I)
EN_DM_RE = re.compile(r'(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?' + EN_MON_RE + r'(?!\w)(?:,?\s+(\d{4}))?', re.I)
EN_MD_RE = re.compile(r'\b' + EN_MON_RE + r'\s+(\d{1,2})(?:st|nd|rd|th)?(?!\d)(?:,?\s+(\d{4}))?', re.I)
WEEKDAYS = [('понедельник', 'monday'), ('вторник', 'tuesday'), ('сред', 'wednesday'), ('четверг', 'thursday'),
            ('пятниц', 'friday'), ('суббот', 'saturday'), ('воскресен', 'sunday')]
WD_RE = re.compile(r'(?<!\w)(понедельник\w*|вторник\w*|сред[аыуе](?!\w)|четверг\w*|пятниц\w*|суббот\w*|воскресень\w*|воскресенье|'
                   r'monday|tuesday|wednesday|thursday|friday|saturday|sunday)', re.I)
NUM_RE = re.compile(r'(?<![\w.,])-?\d{1,3}(?:[ \u00a0\u202f]\d{3})+(?:[.,]\d+)?(?!\d)|(?<![\w.,])-?\d{1,3}(?:,\d{3})+(?:\.\d+)?(?!\d)|(?<![\w.,])-?\d+(?:[.,]\d+)?(?!\d)')


def _num_token(tok):
    t = re.sub(r'[ \u00a0\u202f]', '', tok)
    if re.fullmatch(r'-?\d{1,3}(?:,\d{3})+(?:\.\d+)?', t):
        t = t.replace(',', '')
    elif re.fullmatch(r'-?\d+,\d+', t):
        t = t.replace(',', '.')
    try:
        return float(t)
    except ValueError:
        return None


def numbers(text):
    """All numbers in text (callers compare by membership)."""
    out = []
    for m in NUM_RE.finditer(text or ''):
        v = _num_token(m.group(0))
        if v is not None:
            out.append(v)
    return out


def parse_number(s):
    if isinstance(s, (int, float)) and not isinstance(s, bool):
        return float(s)
    ns = numbers(str(s or ''))
    return ns[0] if len(ns) == 1 else None


def _year_for(month, day, now):
    return dt.date(now.year, month, day)          # amendment 4: year of the policy's current time


def _mk(y, mth, d, now):
    if mth is None:
        return None
    try:
        if y is None:
            return _year_for(mth, d, now) if now else None
        y = int(y)
        if y < 100:
            y += 2000
        return dt.date(y, mth, d)
    except (ValueError, TypeError):
        return None


def _ru_month(w):
    w = w.lower()
    if w.startswith('ма') and not w.startswith('март'):
        return 5
    for k, v in RU_MONTHS.items():
        if w.startswith(k):
            return v
    return None


def dates(text, now=None):
    """[(date, span_text)] for every date in text, in order of appearance. `now` is a date (for year-less dates)."""
    text = text or ''
    found = []
    for m in ISO_RE.finditer(text):
        found.append((m.start(), _mk(m[1], int(m[2]), int(m[3]), now), m[0]))
    for m in RU_RE.finditer(text):
        found.append((m.start(), _mk(m[3], _ru_month(m[2]), int(m[1]), now), m[0]))
    for m in EN_DM_RE.finditer(text):
        found.append((m.start(), _mk(m[3], EN_MONTHS[m[2][:3].lower()], int(m[1]), now), m[0]))
    for m in EN_MD_RE.finditer(text):
        found.append((m.start(), _mk(m[3], EN_MONTHS[m[1][:3].lower()], int(m[2]), now), m[0]))
    for m in RANGE_RE.finditer(text):           # '10-15 октября': the first day shares the month
        w = m[3].lower()
        mth = _ru_month(w) if re.match('[а-я]', w) else EN_MONTHS.get(w[:3])
        found.append((m.start(), _mk(m[4], mth, int(m[1]), now), m[1]))
    iso_spans = [(m.start(), m.end()) for m in ISO_RE.finditer(text)]
    for m in DMY_RE.finditer(text):
        if any(a <= m.start() < b for a, b in iso_spans):
            continue
        dd, mm = int(m[1]), int(m[2])
        if not (1 <= mm <= 12 and 1 <= dd <= 31) or (m[3] is None and now is None):
            continue
        found.append((m.start(), _mk(m[3], mm, dd, now), m[0]))
    found.sort(key=lambda x: x[0])
    out, seen = [], set()
    for pos, d, s in found:
        if d is None or pos in seen:
            continue
        seen.add(pos)
        out.append((d, s))
    return out


def parse_date(s, now=None):
    ds = {d for d, _ in dates(str(s or ''), now)}
    return ds.pop() if len(ds) == 1 else None


def weekdays(s):
    ws = []
    for m in WD_RE.finditer(str(s or '')):
        w = m.group(0).lower()
        for i, forms in enumerate(WEEKDAYS):
            if any(w.startswith(f) for f in forms):
                ws.append(i)
    return ws


def parse_weekday(s):
    """0=Monday..6=Sunday if s names exactly one weekday."""
    ws = set(weekdays(s))
    return ws.pop() if len(ws) == 1 else None


def add_business_days(d, n):
    """n business days (Mon-Fri) after d, counting from the next day (d itself is not counted)."""
    k, cur = 0, d
    while k < n:
        cur += dt.timedelta(days=1)
        if cur.weekday() < 5:
            k += 1
    return cur


def next_business_day(d):
    return add_business_days(d, 1)


def arithmetic(expr, values):
    """Evaluate an expression over operand names and numbers with + - * / and parentheses."""
    if not isinstance(expr, str) or not expr.strip() or len(expr) > 200:
        return None
    e = expr.replace('×', '*').replace('−', '-').replace('·', '*').strip()
    try:
        tree = ast.parse(e, mode='eval')
    except SyntaxError:
        return None

    class Sub(ast.NodeTransformer):
        def visit_Name(self, node):
            if values.get(node.id) is None:
                raise ValueError('unknown operand')
            return ast.copy_location(ast.Constant(values[node.id]), node)
    try:
        tree = ast.fix_missing_locations(Sub().visit(tree))
        return float(_eval(tree))
    except (ValueError, ZeroDivisionError, TypeError, RecursionError):
        return None


def num_equal(a, b):
    return a is not None and b is not None and abs(a - b) <= max(0.006, 1e-4 * abs(b))
