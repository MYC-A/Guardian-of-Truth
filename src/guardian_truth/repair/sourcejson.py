"""Addressed JSON leaves (contract 2, source support). A tool payload is parsed once; a quote written as JSON
key/value pairs is admitted only if EVERY pair is the value of one key of the SAME parent object (deep equality),
which yields stable JSON-pointer identities. Two pairs found in different objects are not one piece of evidence."""
from __future__ import annotations

import json
import re

from ..verification.common import MD
from . import numeric as N

MARK = re.compile(r'(?:TOOL_RESPONSE|TOOL_CALL)\s+[^:\n{]*:\s*')


def _no_dup(pairs):
    """Duplicate keys make the object ambiguous (the production parser marks it json_valid=False): reject, never last-wins."""
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError('DUPLICATE_KEY')
        d[k] = v
    return d


_dec = json.JSONDecoder(object_pairs_hook=_no_dup)


def _body(text):
    m = MARK.search(text or '')
    return (text or '')[m.end():].lstrip() if m else (text or '').strip()


def json_shaped(text):
    """The source is written as a JSON tool payload (whether or not it decodes)."""
    return bool(MARK.search(text or '')) and _body(text)[:1] in ('{', '[')


def failed(text):
    """A tool result that reports failure ([ERROR] marker, ok/success false, or a non-empty error field): its fields
    echo the request, they are not evidence of the state of the world."""
    if re.search(r'TOOL_RESPONSE[^:\n]*\[(?:ERROR|FAIL\w*)\]', text or '', re.I):
        return True
    p = payload(text)
    return isinstance(p, dict) and (p.get('ok') is False or p.get('success') is False or bool(p.get('error')))


def payload(text):
    """The JSON payload of a TOOL_CALL / TOOL_RESPONSE source text, else None (also None for duplicate keys)."""
    s = _body(text)
    if not s[:1] in ('{', '['):
        return None
    try:
        v, _ = _dec.raw_decode(s)
        return v
    except ValueError:
        return None


def nodes(x, ptr=''):
    """(pointer, value) for every node in document order (containers too)."""
    yield ptr, x
    if isinstance(x, dict):
        for k, v in x.items():
            yield from nodes(v, ptr + '/' + str(k).replace('~', '~0').replace('/', '~1'))
    elif isinstance(x, list):
        for i, v in enumerate(x):
            yield from nodes(v, f'{ptr}/{i}')


def same(a, b):
    """Deep JSON equality; numbers by exact Decimal value (1300 == 1300.0), strings exact."""
    if isinstance(a, bool) or isinstance(b, bool):
        return a is b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return N.eq(a, b)
    if isinstance(a, dict) and isinstance(b, dict):
        return set(a) == set(b) and all(same(a[k], b[k]) for k in a)
    if isinstance(a, list) and isinstance(b, list):
        return len(a) == len(b) and all(same(x, y) for x, y in zip(a, b))
    return type(a) is type(b) and a == b


def _balanced(s, i):
    """End index of the JSON value starting at s[i] (string, number, literal, array or object)."""
    try:
        _, end = _dec.raw_decode(s, i)
        return end
    except ValueError:
        return None


KEY = re.compile(r'"((?:[^"\\]|\\.){1,120})"\s*:\s*')


def quote_pairs(quote):
    """Key/value pairs written in a quote: whole JSON object if it parses, else every `"k": <json value>` pair.
    Returns (pairs, residue_ok). Residue other than JSON punctuation/ellipsis means the quote is not pure JSON."""
    q = MD.sub('', quote or '').strip()
    p = payload(q)
    if isinstance(p, dict) and p:
        return list(p.items()), True
    pairs, spans, i = [], [], 0
    for m in KEY.finditer(q):
        if m.start() < i:
            continue
        end = _balanced(q, m.end())
        if end is None:
            continue
        try:
            k = json.loads('"' + m[1] + '"')
            v = json.loads(q[m.end():end])
        except ValueError:
            continue
        pairs.append((k, v))
        spans.append((m.start(), end))
        i = end
    rest = ''.join(ch for j, ch in enumerate(q) if not any(a <= j < b for a, b in spans))
    return pairs, not re.sub(r'[\s{}\[\],:….]+', '', rest)


def addressed(quote, text):
    """-> dict(parent=ptr, pointers=[...], ambiguous=bool) if the quote's pairs are all children of ONE object of the
    source payload; None otherwise (including non-JSON sources or residue)."""
    src = payload(text)
    if src is None:
        return None
    pairs, pure = quote_pairs(quote)
    if not pairs or not pure:
        return None
    hits = []
    for ptr, node in nodes(src):
        if isinstance(node, dict) and all(k in node and same(node[k], v) for k, v in pairs):
            hits.append(ptr)
    if not hits:
        return None
    esc = lambda k: str(k).replace('~', '~0').replace('/', '~1')
    return dict(parent=hits[0], pointers=[hits[0] + '/' + esc(k) for k, _ in pairs], ambiguous=len(hits) > 1,
                values={hits[0] + '/' + esc(k): v for k, v in pairs})


def get(text, ptr):
    x = payload(text)
    for part in [p for p in ptr.split('/')[1:]]:
        part = part.replace('~1', '/').replace('~0', '~')
        if isinstance(x, list):
            x = x[int(part)]
        else:
            x = x[part]
    return x


def id_fields(obj):
    """Identifier-like scalar fields of one object (key ends with id/number/code/_ref) -> {key: value}."""
    if not isinstance(obj, dict):
        return {}
    return {k: v for k, v in obj.items() if isinstance(v, (str, int)) and not isinstance(v, bool)
            and re.search(r'(?:^|_)(?:id|number|code|ref)$', str(k), re.I)}
