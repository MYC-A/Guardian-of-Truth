"""Value normalisation for a bilingual transcript (English data and policy, Russian dialogue).

- numbers in both conventions: 1,234.56 / 1 234,56 / 299,99 / $1,234 / 12.5%
- dates: ISO, MM/DD/YYYY, '14 \u043d\u043e\u044f\u0431\u0440\u044f 2025', 'November 14, 2025'
- token-bounded search: '3019' inside 'sofia.thomas3019@example.com' is NOT a standalone mention
- opaque identifiers (letters+digits, '#W0000000', long digit strings)
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

SPACES = '\u00a0\u202f\u2009'
_SPACE_RE = re.compile('[' + SPACES + ']')


def norm_space(text):
    return _SPACE_RE.sub(' ', text)


def _word(ch):
    return ch.isalnum() or ch == '_'


def find_token(haystack_lower, needle, limit=200):
    """[(position, bounded)] of needle (case-insensitive) in an already lower-cased haystack.
    bounded: the match is not glued to other letters/digits on either side."""
    needle = needle.lower()
    out, start, n = [], 0, len(needle)
    if not n:
        return out
    while len(out) < limit:
        i = haystack_lower.find(needle, start)
        if i < 0:
            break
        before = haystack_lower[i - 1] if i > 0 else ''
        after = haystack_lower[i + n] if i + n < len(haystack_lower) else ''
        glued = (before and _word(before) and _word(needle[0])) or (after and _word(after) and _word(needle[-1]))
        out.append((i, not glued))
        start = i + 1
    return out


def compact(text):
    return re.sub(r'[\W_]+', '', str(text).lower())


# --- numbers --------------------------------------------------------------------------------
_MASKS = [
    re.compile(r'\b\d{4}-\d{2}-\d{2}(?:[ T]\d{1,2}:\d{2}(?::\d{2})?)?\b'),          # ISO date / datetime
    re.compile(r'\b\d{1,2}/\d{1,2}/\d{2,4}\b'),                                    # US date
    re.compile(r'\b\d{1,2}:\d{2}(?::\d{2})?\b'),                                   # time
    re.compile(r'\+?\d{1,3}[- .]\(?\d{3}\)?[- .]\d{3}[- .]\d{4}\b|\b\d{3}-\d{3}-\d{4}\b'),  # phones
    re.compile(r'[#@]?[A-Za-z_][A-Za-z_0-9.\-]*\d[A-Za-z_0-9.\-]*|\b\d+[A-Za-z_][A-Za-z_0-9\-]*'),  # ids
]
NUMBER = re.compile('(?<![\\w.,])(?P<sign>[-\u2212])?(?P<int>\\d{1,3}(?:[ ' + SPACES + ',.]\\d{3})+|\\d+)'
                    '(?:(?P<dec>[.,])(?P<frac>\\d+))?(?P<pct>\\s?%)?(?![\\w])')
CURRENCY_BEFORE = re.compile('(?:\\$|\u20bd|\u20ac|USD|RUB)\\s?$', re.I)
CURRENCY_AFTER = re.compile('^\\s?(?:\\$|\u20bd|\u20ac|usd|rub|\u0434\u043e\u043b\u043b|\u0440\u0443\u0431)', re.I)


@dataclass(frozen=True)
class NumberMention:
    raw: str
    values: frozenset
    start: int
    end: int
    money: bool
    percent: bool


def _masked(text):
    spans = []
    for rx in _MASKS:
        spans += [(m.start(), m.end()) for m in rx.finditer(text)]
    return spans


def _candidates(int_part, dec, frac):
    """All readings of a written number (separator conventions are ambiguous in mixed text)."""
    groups = re.split('[ ' + SPACES + ',.]', int_part)
    seps = set(re.findall('[ ' + SPACES + ',.]', int_part))
    out = set()
    if len(groups) > 1:
        out.add(float(''.join(groups) + ('.' + frac if frac else '')))
        if len(groups) == 2 and seps <= {',', '.'} and not frac:
            out.add(float(groups[0] + '.' + groups[1]))       # '1,234' might be 1.234
    else:
        out.add(float(int_part + ('.' + frac if frac else '')))
        if frac and dec == ',' and len(frac) == 3:
            out.add(float(int_part + frac))                     # '1,234' as thousands
    return frozenset(round(v, 4) for v in out)


def parse_numbers(text):
    text = norm_space(text or '')
    masks = _masked(text)
    out = []
    for m in NUMBER.finditer(text):
        s, e = m.start(), m.end()
        if any(a <= s < b or a < e <= b for a, b in masks):
            continue
        values = _candidates(m.group('int'), m.group('dec'), m.group('frac'))
        if m.group('sign'):
            values = frozenset(-v for v in values)
        money = bool(CURRENCY_BEFORE.search(text[max(0, s - 5):s]) or CURRENCY_AFTER.match(text[e:e + 6]))
        out.append(NumberMention(m.group(0), values, s, e, money, bool(m.group('pct'))))
    return out


# --- dates ----------------------------------------------------------------------------------
RU_MONTHS = ['\u044f\u043d\u0432\u0430\u0440', '\u0444\u0435\u0432\u0440\u0430\u043b', '\u043c\u0430\u0440\u0442',
             '\u0430\u043f\u0440\u0435\u043b', '\u043c\u0430', '\u0438\u044e\u043d', '\u0438\u044e\u043b',
             '\u0430\u0432\u0433\u0443\u0441\u0442', '\u0441\u0435\u043d\u0442\u044f\u0431\u0440',
             '\u043e\u043a\u0442\u044f\u0431\u0440', '\u043d\u043e\u044f\u0431\u0440', '\u0434\u0435\u043a\u0430\u0431\u0440']
EN_MONTHS = ['jan', 'feb', 'mar', 'apr', 'may', 'jun', 'jul', 'aug', 'sep', 'oct', 'nov', 'dec']
ISO_DATE = re.compile(r'\b(\d{4})-(\d{2})-(\d{2})\b')
US_DATE = re.compile(r'\b(\d{1,2})/(\d{1,2})/(\d{4})\b')
RU_DATE = re.compile('\\b(\\d{1,2})\\s+(\u044f\u043d\u0432\u0430\u0440|\u0444\u0435\u0432\u0440\u0430\u043b|\u043c\u0430\u0440\u0442|'
                     '\u0430\u043f\u0440\u0435\u043b|\u043c\u0430|\u0438\u044e\u043d|\u0438\u044e\u043b|\u0430\u0432\u0433\u0443\u0441\u0442|'
                     '\u0441\u0435\u043d\u0442\u044f\u0431\u0440|\u043e\u043a\u0442\u044f\u0431\u0440|\u043d\u043e\u044f\u0431\u0440|'
                     '\u0434\u0435\u043a\u0430\u0431\u0440)[\u0430-\u044f]*\\.?(?:\\s+(\\d{4}))?', re.I)
EN_DATE = re.compile(r'\b(jan|feb|mar|apr|may|jun|jul|aug|sep|oct|nov|dec)[a-z]*\.?\s+(\d{1,2})(?:st|nd|rd|th)?'
                     r'(?:,?\s+(\d{4}))?\b', re.I)


def parse_dates(text, default_year=None):
    """[(date or None, start, end, raw)]; dates without a year use default_year when given."""
    out = []

    def add(y, mo, d, m):
        try:
            value = date(int(y), int(mo), int(d)) if y else (date(default_year, int(mo), int(d)) if default_year else None)
        except ValueError:
            value = None
        out.append((value, m.start(), m.end(), m.group(0)))
    for m in ISO_DATE.finditer(text):
        add(m.group(1), m.group(2), m.group(3), m)
    for m in US_DATE.finditer(text):
        add(m.group(3), m.group(1), m.group(2), m)
    for m in RU_DATE.finditer(text):
        add(m.group(3), RU_MONTHS.index(m.group(2).lower()) + 1, m.group(1), m)
    for m in EN_DATE.finditer(text):
        add(m.group(3), EN_MONTHS.index(m.group(1).lower()[:3]) + 1, m.group(2), m)
    return sorted(out, key=lambda item: item[1])


# --- identifiers ----------------------------------------------------------------------------
ID_TOKEN = re.compile(r'(?<![\w#@.\-])#?[A-Za-z0-9][A-Za-z0-9_\-]{3,63}(?![\w\-])')


def is_identifier(token):
    t = token.lstrip('#')
    if not any(c.isdigit() for c in t):
        return False
    if re.fullmatch(r'\d{4}-\d{2}-\d{2}|\d{1,2}-\d{1,2}-\d{2,4}|[\d\-]+', t) and not re.fullmatch(r'\d{6,}', t):
        return False
    return any(c.isalpha() for c in t) or token.startswith('#') or len(t) >= 6


def extract_identifiers(text):
    return [(m.group(0), m.start(), m.end()) for m in ID_TOKEN.finditer(text or '') if is_identifier(m.group(0))]


EMAIL = re.compile(r'[\w.+\-]+@[\w\-]+(?:\.[\w\-]+)+')


def value_kind(key, value):
    """Coarse kind of a scalar argument value: id | email | phone | date | number | name | text."""
    if isinstance(value, bool):
        return 'flag'
    if isinstance(value, (int, float)):
        return 'number'
    s = str(value).strip()
    k = (key or '').lower()
    if EMAIL.fullmatch(s):
        return 'email'
    if re.fullmatch(r'\+?[\d\-() .]{7,}', s) and sum(c.isdigit() for c in s) >= 7:
        return 'phone'
    if ISO_DATE.fullmatch(s) or US_DATE.fullmatch(s):
        return 'date'
    if re.fullmatch(r'-?\d+(?:\.\d+)?', s):
        return 'id' if (k.endswith(('_id', '_ids', 'id', 'zip', 'code', 'number')) or len(s) >= 6) else 'number'
    if is_identifier(s) and ' ' not in s:
        return 'id'
    if len(s.split()) <= 4 and len(s) <= 60:
        return 'name'
    return 'text'


# --- transliteration (user may write 'Джон Смит' for 'John Smith') ----------------------------
_TR = dict(zip('\u0430\u0431\u0432\u0433\u0434\u0435\u0451\u0436\u0437\u0438\u0439\u043a\u043b\u043c\u043d\u043e\u043f\u0440\u0441\u0442\u0443\u0444\u0445\u0446\u0447\u0448\u0449\u044a\u044b\u044c\u044d\u044e\u044f',
               ['a', 'b', 'v', 'g', 'd', 'e', 'e', 'zh', 'z', 'i', 'y', 'k', 'l', 'm', 'n', 'o', 'p', 'r', 's', 't',
                'u', 'f', 'kh', 'ts', 'ch', 'sh', 'shch', '', 'y', '', 'e', 'yu', 'ya']))


def translit(text):
    out = []
    for c in text:
        low = c.lower()
        if low in _TR:
            t = _TR[low]
            out.append(t.capitalize() if c != low else t)
        else:
            out.append(c)
    return ''.join(out)
