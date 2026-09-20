"""Exact source checks. No fuzzy matching and no semantic validation."""

from __future__ import annotations

from .contracts import Clause, SourceDocument, SourceLink


def validate_link(link: SourceLink, sources: dict[str, SourceDocument]) -> tuple[bool, str]:
    source = sources.get(link.source_id)
    if source is None:
        return False, "UNKNOWN_SOURCE"
    if link.end > len(source.text):
        return False, "OFFSET_OUT_OF_RANGE"
    if source.text[link.start:link.end] != link.quote:
        return False, "QUOTE_OFFSET_MISMATCH"
    if not link.quote:
        return False, "EMPTY_QUOTE"
    return True, "ANCHORED"


def validate_clause(clause: Clause, sources: dict[str, SourceDocument]) -> tuple[bool, str]:
    return validate_link(clause.link, sources)
