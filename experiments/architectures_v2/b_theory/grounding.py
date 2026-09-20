"""Exact source checks. No fuzzy matching and no semantic validation."""

from __future__ import annotations

from .contracts import Clause, SourceDocument, SourceLink


def validate_link(link: SourceLink, sources: dict[str, SourceDocument]) -> tuple[bool, str]:
    source = sources.get(link.source_id)
    if source is None:
        return False, "UNKNOWN_SOURCE"
    if link.start < 0 or link.end < link.start or link.end > len(source.text):
        return False, "OFFSET_OUT_OF_RANGE"
    if source.text[link.start:link.end] != link.quote:
        return False, "QUOTE_OFFSET_MISMATCH"
    if not link.quote:
        return False, "EMPTY_QUOTE"
    return True, "ANCHORED"


def validate_clause(clause: Clause, sources: dict[str, SourceDocument]) -> tuple[bool, str]:
    return validate_link(clause.link, sources)


def resolve_unique_quote(*, source_id: str, quote: str,
                         sources: dict[str, SourceDocument],
                         start=None, end=None) -> tuple[SourceLink | None, str]:
    """Accept valid offsets, otherwise recover one unique verbatim occurrence."""
    source = sources.get(source_id)
    if source is None:
        return None, "UNKNOWN_SOURCE"
    if not isinstance(quote, str) or not quote:
        return None, "MISSING_QUOTE"
    if isinstance(start, int) and isinstance(end, int):
        proposed = SourceLink(source_id, start, end, quote)
        if validate_link(proposed, sources)[0]:
            return proposed, "MODEL_OFFSETS_EXACT"
    count = source.text.count(quote)
    if count == 1:
        recovered = source.text.index(quote)
        return SourceLink(source_id, recovered, recovered + len(quote), quote), \
            "UNIQUE_QUOTE_OFFSETS_RECOVERED"
    return None, "QUOTE_NOT_FOUND" if count == 0 else f"AMBIGUOUS_QUOTE:{count}"
