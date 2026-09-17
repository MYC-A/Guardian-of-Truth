"""Auditable wire types for source, RuleIR, bindings, and interpretation sets."""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any


@dataclass(frozen=True)
class SourceSegment:
    segment_id: str
    source_type: str
    actor: str
    event_index: int
    turn_index: int
    start_char: int
    end_char: int
    exact_text: str
    document: str = "prompt"
    call_id: str | None = None
    paired_call_id: str | None = None
    tool_name: str | None = None
    parent_segment_id: str | None = None

    def __post_init__(self) -> None:
        if self.event_index < 0 or self.turn_index < 0:
            raise ValueError("source ordering indices must be non-negative")
        if not 0 <= self.start_char <= self.end_char:
            raise ValueError("invalid source coordinates")
        if self.end_char - self.start_char != len(self.exact_text):
            raise ValueError("source coordinates must exactly bound exact_text")


@dataclass(frozen=True)
class SourceTimeline:
    prompt_sha256: str
    response_sha256: str
    segments: tuple[SourceSegment, ...]


@dataclass(frozen=True)
class RetrievedFragment:
    segment_id: str
    exact_text: str
    reasons: tuple[str, ...]
    lexical_score: float = 0.0
    embedding_score: float | None = None


@dataclass(frozen=True)
class RetrievalResult:
    fragments: tuple[RetrievedFragment, ...]
    routed_segment_ids: tuple[str, ...]
    unrouted_segment_ids: tuple[str, ...]
    source_coverage: tuple[dict, ...]


@dataclass(frozen=True)
class SourceSpan:
    segment_id: str
    start: int
    end: int
    quote: str

    def __post_init__(self) -> None:
        if not 0 <= self.start < self.end or self.end - self.start != len(self.quote):
            raise ValueError("invalid exact source span")


@dataclass(frozen=True)
class RuleTerm:
    kind: str
    name: str | None = None
    value: Any = None
    entity_ref: str | None = None
    field: str | None = None


@dataclass(frozen=True)
class RuleExpression:
    """A compositional expression tree; leaves use ``term``."""

    operator: str
    term: RuleTerm | None = None
    operands: tuple["RuleExpression", ...] = ()
    comparator: str | None = None
    left: RuleTerm | None = None
    right: RuleTerm | None = None
    cardinality: str | None = None
    count: int | None = None


@dataclass(frozen=True)
class RuleIR:
    modality: str
    subject: str | None
    target: RuleTerm
    relation: str = "NONE"
    condition: RuleExpression | None = None
    exception: RuleExpression | None = None
    temporal: str = "NONE"
    values: tuple[Any, ...] = ()
    entity_references: tuple[str, ...] = ()
    unresolved_references: tuple[str, ...] = ()


@dataclass(frozen=True)
class NLIEvidence:
    label: str
    scores: dict[str, float]
    logits: tuple[float, ...]
    model: str
    rendering: str


@dataclass(frozen=True)
class BindingAlternative:
    kind: str
    semantic_name: str
    candidate: str
    lexical_score: float
    embedding_score: float | None
    reranker_score: float | None
    source_grounded_alias: bool = False


@dataclass(frozen=True)
class RuleCandidate:
    candidate_id: str
    rule: RuleIR
    source_spans: tuple[SourceSpan, ...]
    source_segment_ids: tuple[str, ...]
    extractors: tuple[str, ...]
    nli_evidence: tuple[NLIEvidence, ...] = ()
    binding_alternatives: tuple[BindingAlternative, ...] = ()
    unresolved_components: tuple[str, ...] = ()
    canonical_digest: str = ""


@dataclass(frozen=True)
class SemanticInterpretationSet:
    interpretations: tuple[RuleCandidate, ...]
    unresolved: tuple[str, ...]
    source_coverage: tuple[dict, ...]


def to_wire(value):
    if hasattr(value, "__dataclass_fields__"):
        return {key: to_wire(item) for key, item in asdict(value).items()}
    if isinstance(value, dict):
        return {str(key): to_wire(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [to_wire(item) for item in value]
    return value
