"""E5 — strictly deterministic identity resolver for extractive refs.

Spec section 74 (exactly four cases) and section 75 (forbidden recovery).
No edit distance, no fuzzy match, no embeddings, no nearest span, no LLM fix,
no choosing among duplicates, no searching other authority sources.

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from .goal_types_v1 import E5Resolution, E5Result, ExtractiveRef, SourceText


def _normalize_for_search(text: str) -> str:
    """CRLF/CR in sources and quotes normalize to LF before offset math.

    Offsets in the canonical source are computed over the LF-normalized text;
    the source text stored in SourceText must already be LF-normalized (the
    source adapter enforces this), so this helper is the single place that
    documents the invariant.
    """
    return text.replace("\r\n", "\n").replace("\r", "\n")


def resolve_ref(ref: ExtractiveRef, sources: dict[str, SourceText]) -> E5Result:
    """Resolve ONE extractive ref against the firewall-safe source set.

    Case 1  source[start:end] == quote                        -> RESOLVED_EXACT
    Case 2  offsets wrong, quote occurs exactly once          -> RESOLVED_UNIQUE_QUOTE
    Case 3  quote occurs 2+ times                             -> AMBIGUOUS
    Case 4  quote absent (or source absent)                   -> UNRESOLVED
    """
    source = sources.get(ref.source_id)
    if source is None:
        # Forbidden recovery (section 75): never search another authority source.
        return E5Result(ref, E5Resolution.UNRESOLVED, None)
    text = _normalize_for_search(source.text)
    if 0 <= ref.start < ref.end <= len(text) and text[ref.start:ref.end] == ref.quote:
        return E5Result(ref, E5Resolution.RESOLVED_EXACT, ref)
    occurrences = []
    cursor = 0
    while True:
        position = text.find(ref.quote, cursor)
        if position < 0:
            break
        occurrences.append(position)
        cursor = position + 1
        if len(occurrences) > 1:
            break
    if len(occurrences) == 1:
        start = occurrences[0]
        canonical = ExtractiveRef(ref.source_id, start, start + len(ref.quote), ref.quote)
        return E5Result(ref, E5Resolution.RESOLVED_UNIQUE_QUOTE, canonical)
    if len(occurrences) > 1:
        return E5Result(ref, E5Resolution.AMBIGUOUS, None)
    return E5Result(ref, E5Resolution.UNRESOLVED, None)


def resolve_all(refs, sources: dict[str, SourceText]) -> dict[tuple[str, int, int, str], E5Result]:
    results = {}
    for ref in refs:
        key = (ref.source_id, ref.start, ref.end, ref.quote)
        if key not in results:
            results[key] = resolve_ref(ref, sources)
    return results


def proposition_from_ref(text: str, result: E5Result):
    """Build a GroundedProposition from a resolved ref, or None."""
    from .goal_types_v1 import GroundedProposition

    if not result.ok or result.resolved is None:
        return None
    return GroundedProposition(text, result.resolved, result.resolution)
