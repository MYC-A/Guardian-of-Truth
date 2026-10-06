"""Exact source support (contract 2). A quote is supported when it is
(a) an addressed JSON leaf set of the source payload (sourcejson.addressed), or
(b) a whitespace/markdown/case-normalised verbatim substring, or stitched from verbatim pieces of ONE source, or
(c) a near-verbatim word match (V3 Q2 rule) ONLY if the matched source window has exactly the same polarity and
    quantifier tokens (not/no/never/except/unless/only/... ) and every number of the quote is in the source.
A quote that looks like JSON pairs on a JSON source must satisfy (a): pairs scattered over different objects fail."""
from __future__ import annotations

from collections import Counter
from difflib import SequenceMatcher
import re

from ..verification.common import MD, _clean_quote, norm_ws
from ..verification.proof import numbers_grounded
from . import sourcejson as J

POL = re.compile(r"(?<!\w)(not|no|never|none|nothing|nor|cannot|can't|won't|don't|doesn't|isn't|aren't|mustn't|shouldn't|"
                 r"without|except|unless|only|neither|n't|не|нет|ни|никогда|без|кроме|только|нельзя|запрещ\w*|исключ\w*)(?!\w)", re.I)


def polarity(s):
    return Counter(m.lower() for m in POL.findall(s or ''))


def _norm(s):
    return norm_ws(MD.sub('', s or '')).lower()


def verbatim(quote, text):
    q = _clean_quote(_norm(quote))
    t = _norm(text)
    if len(q) < 2:
        return False
    if q in t:
        return len(q) >= 8 or q == _clean_quote(t)
    parts = [p.strip(' "«»“”\'.;,') for p in re.split(r'\.\.\.|…|:\s+|\s+-\s+|;\s+', q)]
    parts = [p for p in parts if p]
    return len(parts) >= 2 and max(len(p) for p in parts) >= 20 and all(len(p) >= 4 and p in t for p in parts)


def near_verbatim(quote, text, threshold=0.9, min_words=6):
    """V3 fuzzy rule, but the best window must keep the quote's polarity tokens exactly (no deleted NOT)."""
    q = _clean_quote(_norm(quote))
    qw, tw = re.findall(r'\w+', q), re.findall(r'\w+', _norm(text))
    if len(qw) < min_words:
        return False
    qs, pq = set(qw), polarity(' '.join(qw))
    for n in range(max(1, len(qw) - 3), len(qw) + 4):
        for i in range(0, max(1, len(tw) - n + 1)):
            win = tw[i:i + n]
            if len(qs.intersection(win)) < threshold * len(qs):
                continue
            if SequenceMatcher(None, qw, win, autojunk=False).ratio() < threshold:
                continue
            ctx = polarity(' '.join(tw[max(0, i - 3):i + n + 3]))     # a NOT just outside the window counts too
            if polarity(' '.join(win)) == pq and not any(pq[k] == 0 for k in ctx):
                return True
    return False


def looks_json(quote):
    pairs, pure = J.quote_pairs(quote)
    return bool(pairs) and pure


def support(quote, text):
    """-> dict(status SUPPORTED|UNSUPPORTED, how, address) — contract 2 receipt for one piece."""
    if not quote or not text:
        return dict(status='UNSUPPORTED', how='EMPTY')
    if J.payload(text) is not None and looks_json(quote):
        a = J.addressed(quote, text)
        return dict(status='SUPPORTED', how='JSON_ADDRESSED', address=a) if a else dict(status='UNSUPPORTED', how='JSON_NOT_ONE_OBJECT')
    if verbatim(quote, text) and numbers_grounded(quote, text):
        return dict(status='SUPPORTED', how='VERBATIM')
    if near_verbatim(quote, text) and numbers_grounded(quote, text):
        return dict(status='SUPPORTED', how='NEAR_VERBATIM_POLARITY_KEPT')
    return dict(status='UNSUPPORTED', how='NOT_FOUND')


def ok(quote, text):
    return support(quote, text)['status'] == 'SUPPORTED'


def ok_any(quote, texts):
    return any(ok(quote, t) for t in texts if t)


PIECES = re.compile(r'\n+|\s+/\s+|\s*\.\.\.\s*|\s*…\s*|\s*;\s+(?=\S)')


def pieces_ok(quote, texts):
    ps = [p.strip(' \t"\'«»') for p in PIECES.split(quote or '')]
    ps = [p for p in ps if p]
    return len(ps) >= 2 and all(ok_any(p, texts) for p in ps)
