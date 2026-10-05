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


def step_record(rec, tag, req):
    from ..integrated.transport import sha
    return dict(tag=tag, key=rec.get('key'), cached=rec.get('cached'), usage=rec.get('usage'), transport=rec.get('transport'),
                finish_reason=rec.get('finish_reason'), seconds=rec.get('seconds'), request_sha256=sha(req),
                request_bytes=len(json.dumps(req, ensure_ascii=False).encode()), raw_content=rec.get('content'))
