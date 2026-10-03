"""Shared, source-bound views over the visible dialogue (no LLM, no dataset IDs).

* ``observed_records``: every JSON object returned by a tool, with nested objects,
  in dialogue order. Only tool *results* are records; assistant prose never is.
* ``user_texts``: what the user actually typed (the only source of user-provided values).
* ``reference_date``: the evaluation "now" (policy current time or latest current-time tool).
* ``parse_date``: conservative date parser (ISO, US numeric, English/Russian month names).
"""
from datetime import date, datetime
import json
import re

from guardian_truth.policy_table.segment import system_text
from .witness import current_datetime

_MONTHS = {
    'jan': 1, 'feb': 2, 'mar': 3, 'apr': 4, 'may': 5, 'jun': 6, 'jul': 7, 'aug': 8, 'sep': 9, 'oct': 10, 'nov': 11, 'dec': 12,
    'янв': 1, 'фев': 2, 'мар': 3, 'апр': 4, 'мая': 5, 'май': 5, 'июн': 6, 'июл': 7, 'авг': 8, 'сен': 9, 'окт': 10, 'ноя': 11, 'дек': 12,
}
_ISO = re.compile(r'(?<!\d)(\d{4})-(\d{1,2})-(\d{1,2})(?!\d)')
_NUMERIC = re.compile(r'(?<!\d)(\d{1,2})[/.](\d{1,2})[/.](\d{4})(?!\d)')
_WORD_DMY = re.compile(r'(?<!\d)(\d{1,2})(?:st|nd|rd|th)?\s+(?:of\s+)?([A-Za-zА-Яа-яЁё]{3,})\.?,?\s+(\d{4})(?!\d)')
_WORD_MDY = re.compile(r'\b([A-Za-zА-Яа-яЁё]{3,})\.?\s+(\d{1,2})(?:st|nd|rd|th)?,?\s+(\d{4})(?!\d)')


def _month(word):
    return _MONTHS.get(word[:3].lower())


def _safe(y, m, d):
    try: return date(int(y), int(m), int(d))
    except (ValueError, TypeError): return None


def parse_dates(text):
    """All calendar dates written in ``text``; ambiguous dd/mm vs mm/dd yields both readings."""
    out = set()
    text = str(text)
    for y, m, d in _ISO.findall(text): out.add(_safe(y, m, d))
    for a, b, y in _NUMERIC.findall(text): out.update({_safe(y, a, b), _safe(y, b, a)})
    for d, w, y in _WORD_DMY.findall(text):
        if _month(w): out.add(_safe(y, _month(w), d))
    for w, d, y in _WORD_MDY.findall(text):
        if _month(w): out.add(_safe(y, _month(w), d))
    out.discard(None)
    return out


def parse_date(value):
    """Single date from a field value, or None when absent/ambiguous."""
    if not isinstance(value, str): return None
    m = _ISO.match(value.strip())
    if m: return _safe(*m.groups())
    found = parse_dates(value)
    return next(iter(found)) if len(found) == 1 else None


def reference_date(store):
    """'Now' for the step under evaluation, as a date; None when it cannot be established."""
    if not store.target_events: return None
    value = current_datetime(store, {'source_id': 't0'})
    if value.status != 'RESOLVED' or not value.value: return None
    try: return datetime.fromisoformat(value.value).date()
    except ValueError: return None


def _decoded(value):
    if isinstance(value, str) and value.strip()[:1] in '{[':
        try: return json.loads(value)
        except ValueError: return None
    return value


def _objects(value, path=()):
    if isinstance(value, dict):
        yield path, value
        for k, v in value.items(): yield from _objects(v, path + (k,))
    elif isinstance(value, list):
        for i, v in enumerate(value): yield from _objects(v, path + (i,))


def observed_records(store, *, include_target=False):
    """(source_id, tool, top_level_object, nested_object) for every object in tool results."""
    events = [('h' + str(i), e) for i, e in enumerate(store.history_events)]
    if include_target: events += [('t' + str(i), e) for i, e in enumerate(store.target_events)]
    for sid, e in events:
        if e.kind != 'result': continue
        top = e.value if e.json_valid else _decoded(e.text)
        for _, obj in _objects(top):
            yield sid, e.name, top, obj


def user_texts(store, *, before_target=True):
    return [e.text for e in store.history_events if e.role == 'user' and e.kind == 'text']


def last_user_text(store):
    texts = user_texts(store)
    return texts[-1] if texts else ''


def policy_text(store):
    return system_text(store)


def sentences(text):
    """Sentence-ish spans (keeps list items and headings separate)."""
    for m in re.finditer(r'[^\n.!?]+(?:[.!?]+|$)', text or '', re.M):
        s = m.group(0).strip()
        if s: yield m.start(), s


def leaves(value, path=''):
    if isinstance(value, dict):
        for k, v in value.items(): yield from leaves(v, f'{path}.{k}' if path else str(k))
    elif isinstance(value, list):
        for i, v in enumerate(value): yield from leaves(v, f'{path}[{i}]')
    else: yield path, value


def leaf_key(path):
    return re.sub(r'\[\d+\]', '', path).rsplit('.', 1)[-1]
