"""Validate source-grounded, probabilistic error suspicions.

This module deliberately does not decide whether a suspicion is true.  It only
checks that the model's stated reason points at exact, recoverable input text.
Formal proof state remains separate from the probabilistic contest signal.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field as dataclass_field
from typing import Mapping


FORMAL_STATUSES = {"PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT"}
GROUNDING_STATUSES = {"ANCHORED", "UNANCHORED"}


@dataclass(frozen=True)
class SpanClaim:
    document: str
    quote: str
    start: int | None = None
    end: int | None = None


@dataclass(frozen=True)
class AtomicSuspicion:
    reason_type: str
    source_kind: str
    source: SpanClaim
    proposed_violation: str
    score: float
    target: SpanClaim | None = None
    entity: str | None = None
    time_scope: str | None = None
    field: str | None = None
    reason_attributes: Mapping[str, str] = dataclass_field(default_factory=dict)


@dataclass(frozen=True)
class GroundedSuspicion:
    grounding_status: str
    suspicion: AtomicSuspicion
    source_start: int | None
    source_end: int | None
    target_start: int | None
    target_end: int | None
    issues: tuple[str, ...]
    probabilistic_label: int
    formal_status: str = "UNRESOLVED"

    def __post_init__(self) -> None:
        if self.grounding_status not in GROUNDING_STATUSES:
            raise ValueError(f"invalid grounding status: {self.grounding_status}")
        if self.formal_status not in FORMAL_STATUSES:
            raise ValueError(f"invalid formal status: {self.formal_status}")
        if self.probabilistic_label not in (0, 1):
            raise ValueError("probabilistic_label must be 0 or 1")

    def to_dict(self) -> dict:
        return asdict(self)


def _anchor(span: SpanClaim, sources: Mapping[str, str], *, name: str) -> tuple[int | None, int | None, list[str]]:
    text = sources.get(span.document)
    if text is None:
        return None, None, [f"{name}_unknown_document"]
    if not span.quote:
        return None, None, [f"{name}_empty_quote"]

    has_start = span.start is not None
    has_end = span.end is not None
    if has_start != has_end:
        return None, None, [f"{name}_partial_offsets"]
    if has_start:
        assert span.start is not None and span.end is not None
        if span.start < 0 or span.end < span.start or span.end > len(text):
            return None, None, [f"{name}_offsets_out_of_bounds"]
        if text[span.start:span.end] != span.quote:
            return None, None, [f"{name}_quote_offset_mismatch"]
        return span.start, span.end, []

    first = text.find(span.quote)
    if first < 0:
        return None, None, [f"{name}_quote_not_found"]
    if text.find(span.quote, first + 1) >= 0:
        return None, None, [f"{name}_quote_ambiguous"]
    return first, first + len(span.quote), []


def validate_suspicion(
    suspicion: AtomicSuspicion,
    sources: Mapping[str, str],
    *,
    positive_threshold: float = 0.5,
) -> GroundedSuspicion:
    """Ground a model suspicion and gate its probabilistic positive label.

    A high score without an exact source anchor is recorded but cannot emit a
    positive label.  Attributes such as ``knowledge=unknown`` or
    ``execution=attempted`` are preserved verbatim; this layer never converts
    them to false/completed facts.
    """
    if not 0.0 <= suspicion.score <= 1.0:
        raise ValueError("score must be within [0, 1]")
    source_start, source_end, issues = _anchor(suspicion.source, sources, name="source")
    target_start = target_end = None
    if suspicion.target is not None:
        target_start, target_end, target_issues = _anchor(
            suspicion.target, sources, name="target"
        )
        issues.extend(target_issues)
    if not suspicion.reason_type.strip():
        issues.append("missing_reason_type")
    if not suspicion.proposed_violation.strip():
        issues.append("missing_proposed_violation")

    anchored = not issues
    return GroundedSuspicion(
        grounding_status="ANCHORED" if anchored else "UNANCHORED",
        suspicion=suspicion,
        source_start=source_start,
        source_end=source_end,
        target_start=target_start,
        target_end=target_end,
        issues=tuple(issues),
        probabilistic_label=int(anchored and suspicion.score >= positive_threshold),
        formal_status="UNRESOLVED",
    )
