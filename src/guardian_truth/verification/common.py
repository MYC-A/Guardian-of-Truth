"""Shared helpers for verification-v2 model steps: strict JSON-schema requests, admission, quote checks."""
from __future__ import annotations

import json
import re

from ..integrated.reviewer import decode_reply


def request(model, system, user_obj, schema, name, max_tokens=1500):
    return dict(model=model, temperature=0, max_tokens=max_tokens,
                messages=[dict(role='system', content=system),
                          dict(role='user', content=json.dumps(user_obj, ensure_ascii=False, separators=(',', ':')))],
                response_format=dict(type='json_schema', json_schema=dict(name=name, strict=True, schema=schema)))


def call(client, req, attempt, tag):
    rec = client.call(req, attempt=attempt, tag=tag)
    value, valid, norm = decode_reply(rec.get('content'))
    return rec, (value if valid and isinstance(value, dict) else None), norm


def norm_ws(s):
    return re.sub(r'\s+', ' ', s or '').strip()


def quote_ok(quote, texts, min_len=8):
    q = norm_ws(quote).strip('"«»“”\'')
    if len(q) < min_len:
        return False
    return any(q in norm_ws(t) for t in texts)


def _clean_quote(quote):
    q = norm_ws(quote).strip('"«»“”\'')
    q = re.sub(r'^(?:[-*•]\s+|\d+[.)]\s+)', '', q)          # leading list marker
    return q.rstrip(' .;:,')


def _fuzzy_in(q, t, threshold=0.9, min_words=6):
    """Word-level near-verbatim match (one elided/changed word in ~10) against a same-length window of t."""
    from difflib import SequenceMatcher
    qw, tw = re.findall(r'\w+', q.lower()), re.findall(r'\w+', t.lower())
    if len(qw) < min_words:
        return False
    qs = set(qw)
    for n in range(max(1, len(qw) - 3), len(qw) + 4):
        for i in range(0, max(1, len(tw) - n + 1)):
            win = tw[i:i + n]
            if len(qs.intersection(win)) < threshold * len(qs):
                continue
            if SequenceMatcher(None, qw, win, autojunk=False).ratio() >= threshold:
                return True
    return False


def quote_fragments_ok(quote, text, min_len=8, min_longest=20):
    """Policy-quote check for requirement extraction (grounding only, never a verdict): exact substring after
    stripping list markers / trailing punctuation; or stitched from verbatim pieces of ONE source (joined by
    ': ', '...', '…', ' - ', '; ') with the longest piece >= min_longest chars; or a near-verbatim word match
    (SequenceMatcher ratio >= 0.9 against a window of the source)."""
    q = _clean_quote(quote)
    if len(q) < min_len:
        return False
    t = norm_ws(text)
    if q in t:
        return True
    parts = [p.strip(' "«»“”\'.;,') for p in re.split(r'\.\.\.|…|:\s+|\s+-\s+|;\s+', q)]
    parts = [p for p in parts if p]
    if len(parts) >= 2 and max(len(p) for p in parts) >= min_longest and all(len(p) >= 4 and p in t for p in parts):
        return True
    return _fuzzy_in(q, t)


def step_record(rec, tag, req):
    from ..integrated.transport import sha
    return dict(tag=tag, key=rec.get('key'), cached=rec.get('cached'), usage=rec.get('usage'), transport=rec.get('transport'),
                finish_reason=rec.get('finish_reason'), seconds=rec.get('seconds'), request_sha256=sha(req),
                request_bytes=len(json.dumps(req, ensure_ascii=False).encode()), raw_content=rec.get('content'))
