"""Span/quote verification: does a quoted fragment exist in the source text?
Exact match first, then whitespace-normalized, then fuzzy (difflib) fallback.
Returns provenance: {status: exact|normalized|fuzzy|unanchored, start, end, score}
"""
import re, difflib


def _norm_ws(s):
    return re.sub(r"\s+", " ", s).strip()


def locate(quote: str, source: str, min_score: float = 0.72):
    q = (quote or "").strip()
    if not q:
        return {"status": "unanchored", "start": None, "end": None, "score": 0.0}
    # 1. exact
    i = source.find(q)
    if i >= 0:
        return {"status": "exact", "start": i, "end": i + len(q), "score": 1.0}
    # 2. whitespace-normalized scan
    ns, nq = _norm_ws(source), _norm_ws(q)
    if nq:
        i = ns.find(nq)
        if i >= 0:
            # approximate original offsets via prefix ratio (conservative)
            ratio = i / max(len(ns), 1)
            start = int(ratio * len(source))
            return {"status": "normalized", "start": start,
                    "end": start + len(q), "score": 0.95}
        # 3. fuzzy: sliding window of len(nq) over ns (coarse stride)
        if len(nq) >= 25:
            best, bpos = 0.0, -1
            stride = max(len(nq) // 8, 1)
            for j in range(0, max(len(ns) - len(nq), 0) + 1, stride):
                seg = ns[j:j + len(nq)]
                if abs(len(seg) - len(nq)) > len(nq) * 0.4:
                    continue
                s = difflib.SequenceMatcher(None, nq, seg).ratio()
                if s > best:
                    best, bpos = s, j
            if best >= min_score:
                ratio = bpos / max(len(ns), 1)
                start = int(ratio * len(source))
                return {"status": "fuzzy", "start": start,
                        "end": start + len(q), "score": round(best, 3)}
    return {"status": "unanchored", "start": None, "end": None, "score": 0.0}


def verify_spans(items, source):
    """items: list of dicts with 'quote' -> adds 'anchor' provenance."""
    out = []
    for it in items:
        d = dict(it)
        d["anchor"] = locate(it.get("quote", ""), source)
        out.append(d)
    return out
