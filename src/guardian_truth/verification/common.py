"""Shared helpers for verification-v2 model steps: strict JSON-schema requests, admission, quote checks."""
from __future__ import annotations

import json
import re
from functools import lru_cache

from jsonschema import validators
from jsonschema.exceptions import SchemaError

from ..integrated.reviewer import decode_reply


def request(model, system, user_obj, schema, name, max_tokens=1500):
    return dict(model=model, temperature=0, max_tokens=max_tokens,
                messages=[dict(role='system', content=system),
                          dict(role='user', content=json.dumps(user_obj, ensure_ascii=False, separators=(',', ':')))],
                response_format=dict(type='json_schema', json_schema=dict(name=name, strict=True, schema=schema)))


@lru_cache(maxsize=256)
def _validator(serialized_schema):
    schema = json.loads(serialized_schema)
    cls = validators.validator_for(schema)
    cls.check_schema(schema)
    return cls(schema)


def schema_errors(value, schema):
    """Validate code-owned JSON schemas locally, independent of provider strict mode.

    Diagnostics contain addresses and failed keywords rather than unbounded source text.
    An invalid code-owned schema is a visible technical/configuration failure too.
    """
    try:
        validator = _validator(json.dumps(schema, sort_keys=True, separators=(',', ':')))
    except (SchemaError, TypeError, ValueError) as exc:
        return [dict(path=[], keyword='INVALID_SCHEMA', message=str(exc)[:240])]
    errors = sorted(validator.iter_errors(value), key=lambda e: (str(list(e.absolute_path)), e.validator or ''))
    return [dict(path=list(e.absolute_path), keyword=e.validator, message=e.message[:240]) for e in errors[:20]]


def transport_failure(rec):
    """An explicit failed receipt cannot become a verdict by carrying valid JSON.

    Legacy replay fixtures may omit transport metadata. Complete schema-valid
    JSON at a length limit is accepted; explicit error/refusal finishes are not.
    """
    if rec.get('finish_reason') in ('error', 'content_filter', 'refusal'):
        return True
    transport = rec.get('transport')
    if transport is None:
        return False
    if not isinstance(transport, dict):
        return True
    if transport.get('error') or transport.get('ok') is False:
        return True
    status = transport.get('status')
    if status is None:
        return False
    if type(status) is int:
        return not 200 <= status < 300
    if isinstance(status, str):
        return status.upper() not in ('OK', 'SUCCESS') and not (status.isdigit() and 200 <= int(status) < 300)
    return True


def call(client, req, attempt, tag):
    rec = dict(client.call(req, attempt=attempt, tag=tag))
    if transport_failure(rec):
        rec['schema_validation'] = dict(status='TRANSPORT_FAILURE', errors=[])
        return rec, None, None
    value, valid, norm = decode_reply(rec.get('content'))
    schema = ((req.get('response_format') or {}).get('json_schema') or {}).get('schema')
    if not valid or not isinstance(value, dict):
        rec['schema_validation'] = dict(status='INVALID_JSON', errors=[])
        return rec, None, norm
    if schema is None:
        rec['schema_validation'] = dict(status='MISSING_REQUEST_SCHEMA', errors=[])
        return rec, None, norm
    errors = schema_errors(value, schema)
    rec['schema_validation'] = dict(status='INVALID_SCHEMA' if errors else 'VALID', errors=errors)
    return rec, (None if errors else value), norm


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
                request_bytes=len(json.dumps(req, ensure_ascii=False).encode()), raw_content=rec.get('content'),
                schema_validation=rec.get('schema_validation'))


MD = re.compile(r'\*\*|__|(?<!\w)\*(?!\s)|(?<!\s)\*(?!\w)')


def quote_q2(quote, texts):
    """Q2 admission (amendment 3) as used by V3: quote_fragments_ok against any one of the texts, after removing
    markdown emphasis markers the model adds (** __ *), case-insensitively; a short quote is admitted only if it is a WHOLE source
    text (e.g. a one-word user reply)."""
    q = MD.sub('', quote or '').lower()                    # case-insensitive: stitched pieces get re-capitalised
    ts = [MD.sub('', t).lower() for t in texts if t]
    if any(quote_fragments_ok(q, t) for t in ts):
        return True
    c = _clean_quote(q)
    return len(c) >= 2 and any(c == _clean_quote(t) for t in ts)
