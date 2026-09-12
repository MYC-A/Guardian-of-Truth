"""Immutable canonical types. Semantic proposals are never evidence records."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class CoreStatus(str, Enum):
    PROVED_ERROR = "PROVED_ERROR"
    PROVED_NO_ERROR = "PROVED_NO_ERROR"
    UNRESOLVED = "UNRESOLVED"
    INCONSISTENT = "INCONSISTENT"


class Truth(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    BOTH = "BOTH"
    UNKNOWN = "UNKNOWN"


class CoverageStatus(str, Enum):
    PROVABLY_CLOSED = "PROVABLY_CLOSED"
    EMPIRICALLY_COVERED = "EMPIRICALLY_COVERED"
    OPEN_SEMANTICS = "OPEN_SEMANTICS"


class Disposition(str, Enum):
    VERIFIABLE_TYPED = "VERIFIABLE_TYPED"
    NON_VERIFIABLE = "NON_VERIFIABLE"
    UNKNOWN_SEMANTICS = "UNKNOWN_SEMANTICS"


class Reason(str, Enum):
    POLICY_NO_INTERPRETATION = "POLICY_NO_INTERPRETATION"
    POLICY_AMBIGUOUS = "POLICY_AMBIGUOUS"
    POLICY_OPEN_SEMANTICS = "POLICY_OPEN_SEMANTICS"
    GOAL_PLAN_AMBIGUOUS = "GOAL_PLAN_AMBIGUOUS"
    CLAIM_UNTYPED = "CLAIM_UNTYPED"
    ENTITY_UNBOUND = "ENTITY_UNBOUND"
    ENTITY_AMBIGUOUS = "ENTITY_AMBIGUOUS"
    TIME_UNBOUND = "TIME_UNBOUND"
    SOURCE_UNBOUND = "SOURCE_UNBOUND"
    TOOL_EFFECT_UNKNOWN = "TOOL_EFFECT_UNKNOWN"
    TOOL_VERSION_MISMATCH = "TOOL_VERSION_MISMATCH"
    EVIDENCE_INCOMPLETE = "EVIDENCE_INCOMPLETE"
    TEMPORAL_AMBIGUITY = "TEMPORAL_AMBIGUITY"
    CAUSALITY_UNPROVED = "CAUSALITY_UNPROVED"
    TRANSPORT_ERROR = "TRANSPORT_ERROR"
    SCHEMA_ERROR = "SCHEMA_ERROR"


class ClaimKind(str, Enum):
    STATE = "STATE"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    CAUSAL_ATTRIBUTION = "CAUSAL_ATTRIBUTION"
    ACTION_FAILED = "ACTION_FAILED"
    ATTRIBUTION = "ATTRIBUTION"
    INTENT = "INTENT"
    REFUSAL = "REFUSAL"
    FACT = "FACT"
    ABSENCE = "ABSENCE"
    PERMISSION = "PERMISSION"
    OTHER_VERIFIABLE = "OTHER_VERIFIABLE"


class EffectStatus(str, Enum):
    TRUSTED_EFFECT = "TRUSTED_EFFECT"
    POSSIBLE_EFFECT = "POSSIBLE_EFFECT"
    AMBIGUOUS_EFFECT = "AMBIGUOUS_EFFECT"
    UNKNOWN_EFFECT = "UNKNOWN_EFFECT"


@dataclass(frozen=True)
class Span:
    document: str
    start: int
    end: int

    def __post_init__(self):
        if type(self.start) is not int or type(self.end) is not int or not 0 <= self.start < self.end:
            raise ValueError("non-empty deterministic source span required")


@dataclass(frozen=True)
class EntityRef:
    key: str
    value: str
    namespace: str = "source"


@dataclass(frozen=True)
class ToolIdentity:
    name: str
    provider: str | None = None
    version: str | None = None
    schema_sha256: str | None = None


@dataclass(frozen=True)
class LedgerEvent:
    event_id: str
    index: int
    actor: str
    kind: str
    source: Span
    raw_text: str
    payload_json: str | None = None
    tool: ToolIdentity | None = None
    call_id: str | None = None
    call_candidates: tuple[str, ...] = ()
    requestor: str | None = None
    timestamp: str | None = None
    entity_refs: tuple[EntityRef, ...] = ()
    pairing_issue: str | None = None

    @property
    def payload(self):
        # Always a fresh object: modifying this view cannot mutate the event.
        import json
        return json.loads(self.payload_json) if self.payload_json is not None else None


@dataclass(frozen=True)
class Observation:
    evidence_id: str
    event_id: str
    index: int
    actor: str
    predicate: str
    value_json: str
    source: Span
    entity_refs: tuple[EntityRef, ...] = ()
    provenance: str = "SOURCE_FIELD_OBSERVATION"
    call_id: str | None = None

    @property
    def value(self):
        import json
        return json.loads(self.value_json)


@dataclass(frozen=True)
class TypedClaim:
    claim_id: str
    span: Span
    disposition: Disposition
    kind: ClaimKind | None
    actor: str | None
    predicate: str | None
    object: str | None
    entity_refs: tuple[str, ...] = ()
    polarity: str | None = None
    modality: str | None = None
    time_anchor: str | None = None
    source_refs: tuple[str, ...] = ()
    unknown_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class EffectRecord:
    effect_id: str
    event_id: str
    call_id: str | None
    entity: EntityRef
    predicate: str
    value_json: str
    status: EffectStatus
    contract_sha256: str | None
    provenance: str
    causal_action_confirmed: bool = False


@dataclass(frozen=True)
class ClaimRelation:
    subject_claim_id: str
    relation: str
    object_claim_id: str
    grounding: tuple[Span, ...]


@dataclass(frozen=True)
class EvaluationHypothesis:
    hypothesis_id: str
    frontend: str  # policy and goal_plan have distinct parsers.
    behavioral_relation: str
    actor: str | None
    action_or_state: str
    resource: str | None
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    grounding: tuple[Span, ...]
    unresolved_terms: tuple[str, ...] = ()


@dataclass(frozen=True)
class SemanticCoverage:
    status: CoverageStatus
    universe_source: str | None
    enumeration_complete: bool
    unresolved_terms: tuple[str, ...] = ()
    discarded_hypotheses: tuple[tuple[str, str], ...] = ()
    challenger_alternatives: tuple[str, ...] = ()

    def __post_init__(self):
        if type(self.enumeration_complete) is not bool:
            raise ValueError("enumeration completeness must be explicit Boolean")
        if self.status is CoverageStatus.PROVABLY_CLOSED and (
                not self.universe_source or not self.enumeration_complete or self.unresolved_terms):
            raise ValueError("closed semantics requires authoritative universe and complete enumeration")


@dataclass(frozen=True)
class Diagnostics:
    primary_reason: Reason | None
    contributing_reasons: tuple[Reason, ...] = ()
    blocked_claims: tuple[str, ...] = ()
    blocked_hypotheses: tuple[str, ...] = ()
    missing_evidence: tuple[str, ...] = ()
    attempted_escalations: tuple[str, ...] = ()


def consensus(values: tuple[Truth, ...], *, material_space_complete: bool) -> CoreStatus:
    """Truth here is the proposition 'an error occurred', never LLM confidence."""
    if Truth.BOTH in values:
        return CoreStatus.INCONSISTENT
    if not material_space_complete or not values or Truth.UNKNOWN in values:
        return CoreStatus.UNRESOLVED
    if all(value is Truth.TRUE for value in values):
        return CoreStatus.PROVED_ERROR
    if all(value is Truth.FALSE for value in values):
        return CoreStatus.PROVED_NO_ERROR
    return CoreStatus.UNRESOLVED
