"""Deterministic prose-channel invariants (no LLM, no dataset IDs, no tool-name lists).

The prose channel used to return UNKNOWN for every assistant message. It now applies
bounded, source-bound checks; a message with no violated invariant is ADMISSIBLE with
the residual risk reported (same bounded-admissibility contract as tool calls).

* REDUNDANT_INFO_REQUEST: the assistant asks the user for a personal field (date of
  birth, e-mail, phone, address, zip) of a named person although an observed tool
  record for that same person already carries a non-empty value for that field.
* ARITHMETIC_CLAIM_ERROR: the message states an explicit chain "a + b - c = r" whose
  arithmetic is wrong (exact decimal arithmetic, unambiguous number formats only).
"""
from decimal import Decimal, InvalidOperation
import re

from .records import observed_records, sentences

FIELDS = {
    'date_of_birth': (re.compile(r'\b(?:date\s+of\s+birth|birth\s*date|birthday|DOB)\b|дат\w*\s+рождени|день\s+рождени', re.I),
                      ('dob', 'date_of_birth', 'birth_date', 'birthdate', 'birthday')),
    'email': (re.compile(r'\be-?mail(?:\s+address)?\b|(?:адрес\w*\s+)?электронн\w*\s+почт\w*', re.I),
              ('email', 'email_address', 'e_mail')),
    'phone': (re.compile(r'\b(?:phone|telephone|mobile)\s*(?:number)?\b|телефон', re.I), ('phone', 'phone_number', 'mobile')),
    'zip': (re.compile(r'\b(?:zip(?:\s*code)?|postal\s+code|postcode)\b|почтов\w*\s+индекс', re.I), ('zip', 'zip_code', 'postal_code', 'zipcode')),
    'address': (re.compile(r'\baddress\b|\bадрес', re.I),
                ('address',)),
}
_REQUEST = re.compile(
    r'\b(?:please\s+(?:provide|share|tell|confirm|specify|enter|send|give|let\s+me\s+know)|could\s+you\s+(?:please\s+)?(?:provide|share|tell|give|confirm)'
    r'|can\s+you\s+(?:please\s+)?(?:provide|share|tell|give|confirm)|what\s+is\s+(?:your|the|their|his|her)|i\s+(?:will\s+)?need|need\s+(?:your|the|their))\b'
    r'|уточните|укажите|предоставьте|сообщите|назовите|подскажите|необходим\w*|нужн[аоы]\w*', re.I)
_NAME = re.compile(r'\b([A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)?)\s+([A-Z][a-z]+(?:[-\'][A-Z]?[a-z]+)?)\b|'
                   r'\b([А-ЯЁ][а-яё]+)\s+([А-ЯЁ][а-яё]+)\b')


def _names(sentence):
    out = []
    for m in _NAME.finditer(sentence):
        a, b = (m.group(1), m.group(2)) if m.group(1) else (m.group(3), m.group(4))
        out.append((a.lower(), b.lower()))
    return out


def _person(obj):
    first, last = obj.get('first_name'), obj.get('last_name')
    name = obj.get('name')
    if isinstance(name, dict): first, last = name.get('first_name', first), name.get('last_name', last)
    elif isinstance(name, str) and not first:
        parts = name.split()
        if len(parts) >= 2: first, last = parts[0], parts[-1]
    if isinstance(first, str) and isinstance(last, str): return first.lower(), last.lower()
    return None


def _known_fields(store):
    """{(first, last): {field: (value, source_id)}} from observed tool records."""
    known = {}
    for sid, _, _, obj in observed_records(store):
        who = _person(obj)
        if not who: continue
        for field, (_, keys) in FIELDS.items():
            for k in keys:
                v = obj.get(k)
                if v not in (None, '', [], {}): known.setdefault(who, {})[field] = (v, sid)
    return known


def redundant_request_violations(store, text):
    known = None
    out = []
    for _, s in sentences(text):
        if not _REQUEST.search(s): continue
        bare = FIELDS['email'][0].sub(' ', s)  # "e-mail address" / "адрес электронной почты" is not a postal address
        asked = [f for f, (pat, _) in FIELDS.items() if pat.search(bare if f == 'address' else s)]
        if not asked: continue
        names = _names(s)
        if not names: continue
        if known is None: known = _known_fields(store)
        for who in names:
            for f in asked:
                hit = known.get(who, {}).get(f)
                if hit:
                    out.append({'code': 'REDUNDANT_INFO_REQUEST', 'field': f, 'person': ' '.join(who).title(),
                                'observed_value': hit[0], 'evidence_source_id': hit[1], 'quote': s[:240]})
    return out


_NUMBER = r'\$?\s*(\d{1,3}(?:,\d{3})+(?:\.\d+)?|\d+(?:\.\d+)?)'
_CHAIN = re.compile(_NUMBER + r'((?:\s*[+\-−]\s*' + _NUMBER + r')+)\s*=\s*\**\s*' + _NUMBER + r'(?![\d.,]*\d)')


def _dec(text):
    try: return Decimal(text.replace(',', '').replace('$', '').strip())
    except InvalidOperation: return None


def arithmetic_violations(text):
    out = []
    for m in _CHAIN.finditer(text or ''):
        first = _dec(m.group(1))
        terms = re.findall(r'([+\-−])\s*' + _NUMBER, m.group(2))
        result = _dec(m.group(m.lastindex))
        if first is None or result is None or not terms: continue
        total = first
        for op, num in terms:
            n = _dec(num)
            if n is None: break
            total = total + n if op == '+' else total - n
        else:
            if abs(total - result) > Decimal('0.011'):
                out.append({'code': 'ARITHMETIC_CLAIM_ERROR', 'expression': m.group(0).strip(), 'computed': str(total),
                            'stated': str(result)})
    return out


CHECKS = ('REDUNDANT_INFO_REQUEST', 'ARITHMETIC_CLAIM_ERROR')


def prose_violations(store, route):
    out = []
    for sid in route.prose_source_ids:
        text = store.target_events[int(sid[1:])].text
        for v in redundant_request_violations(store, text) + arithmetic_violations(text):
            out.append({**v, 'source_id': sid})
    return out
