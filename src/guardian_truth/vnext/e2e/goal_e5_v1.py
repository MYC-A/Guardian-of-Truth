"""E5: strictly deterministic identity resolver for extractive references
(spec 74, 75). No edit distance, no fuzzy match, no embeddings, no nearest
span, no LLM fix, no choosing among duplicates."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class E5Status(str, Enum):
    RESOLVED_EXACT = "RESOLVED_EXACT"
    RESOLVED_UNIQUE_QUOTE = "RESOLVED_UNIQUE_QUOTE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


@dataclass(frozen=True)
class E5Resolution:
    status: E5Status
    start: int | None
    end: int | None
    quote: str


def resolve(source_text: str, start: int | None, end: int | None, quote: str) -> E5Resolution:
    if not quote:
        return E5Resolution(E5Status.UNRESOLVED, None, None, quote or "")
    if (type(start) is int and type(end) is int and 0 <= start < end <= len(source_text)
            and source_text[start:end] == quote):
        return E5Resolution(E5Status.RESOLVED_EXACT, start, end, quote)
    occurrences = []
    position = source_text.find(quote)
    while position >= 0:
        occurrences.append(position)
        position = source_text.find(quote, position + 1)
    if len(occurrences) == 1:
        return E5Resolution(E5Status.RESOLVED_UNIQUE_QUOTE, occurrences[0],
                            occurrences[0] + len(quote), quote)
    if len(occurrences) > 1:
        return E5Resolution(E5Status.AMBIGUOUS, None, None, quote)
    return E5Resolution(E5Status.UNRESOLVED, None, None, quote)


def resolve_ref(source_text: str, ref) -> E5Resolution:
    return resolve(source_text, ref.get("start"), ref.get("end"), ref.get("quote") or "")
