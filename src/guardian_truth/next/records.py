"""Typed, serialisable records for the Compiled Evidential Monitor.

These records encode the soundness boundaries in their types.  In particular,
an attempted call is not an observed effect and an unknown proposition is not
false.  No record executes input text or model output.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from enum import Enum
from typing import Any


class FourValue(str, Enum):
    TRUE = "true"
    FALSE = "false"
    BOTH = "both"
    UNKNOWN = "unknown"


class EvidenceStatus(str, Enum):
    OBSERVED = "observed"
    ASSERTED = "asserted"
    ATTEMPTED = "attempted"
    CONFIRMED = "confirmed"
    FAILED = "failed"
    SUPERSEDED = "superseded"
    UNKNOWN = "unknown"


class ClaimKind(str, Enum):
    ACTION = "action"
    STATE = "state"
    ATTRIBUTION = "attribution"
    INTENT = "intent"
    REFUSAL = "refusal"
    FACT = "fact"
    ABSENCE = "absence"


class PolicyModality(str, Enum):
    """Normative force of a policy meaning, independent of any trace."""

    PERMISSION = "permission"
    PROHIBITION = "prohibition"
    REQUIREMENT = "requirement"
    DEFINITION = "definition"
    CONTEXT = "context"


class RegulatedKind(str, Enum):
    ACTION = "action"
    STATE = "state"
    INFORMATION = "information"
    OUTCOME = "outcome"


class SemanticUncertainty(str, Enum):
    CERTAIN = "certain"
    AMBIGUOUS = "ambiguous"
    UNSUPPORTED = "unsupported"


@dataclass(frozen=True)
class Span:
    document: str
    start: int
    end: int


@dataclass(frozen=True)
class CoverageItem:
    segment_id: str
    span: Span
    status: str
    reason: str
    rule_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class PolicySegment:
    id: str
    span: Span
    kind: str
    text: str
    ordinal: int
    parent_id: str | None = None
    heading_level: int | None = None


@dataclass(frozen=True)
class PolicyRule:
    id: str
    kind: str
    subject: str
    predicate: str
    object: Any
    source: Span
    compiler: str
    confidence: float | None = None
    executable: bool = False


@dataclass(frozen=True)
class PolicySubject:
    """Actor or role regulated by a policy; not a bound trace entity."""

    kind: str
    identifier: str


@dataclass(frozen=True)
class RegulatedMatter:
    """Natural semantic target, deliberately not a solver proposition."""

    kind: RegulatedKind
    predicate: str
    object: str


@dataclass(frozen=True)
class SemanticQualifier:
    """A source-grounded condition or exception attached to a meaning."""

    text: str
    source: Span


@dataclass(frozen=True)
class TemporalConstraint:
    relation: str
    anchor: str = ""
    duration: str = ""


@dataclass(frozen=True)
class IdentityConstraint:
    entity_type: str
    key: str
    relation: str
    value: str


@dataclass(frozen=True)
class PolicyQuantification:
    kind: str
    amount: int | None = None


@dataclass(frozen=True)
class PolicyProvenance:
    source: Span
    quote: str
    occurrence: int
    extractor: str


@dataclass(frozen=True)
class PolicyMeaning:
    """Trace-independent semantic interpretation proposed for policy text.

    It contains no truth value, evidence identifier, solver predicate, or final
    verdict.  Compilation from this semantic IR into executable obligations is
    a separate, deterministic boundary.
    """

    id: str
    modality: PolicyModality
    subject: PolicySubject
    regulated: RegulatedMatter
    conditions: tuple[SemanticQualifier, ...]
    exceptions: tuple[SemanticQualifier, ...]
    temporal: TemporalConstraint
    identity_constraints: tuple[IdentityConstraint, ...]
    quantification: PolicyQuantification
    uncertainty: SemanticUncertainty
    unsupported_reason: str
    provenance: PolicyProvenance


@dataclass(frozen=True)
class PolicyBundle:
    version: str
    source_hash: str
    segments: tuple[PolicySegment, ...]
    rules: tuple[PolicyRule, ...]
    coverage: tuple[CoverageItem, ...]
    compiler_arm: str
    trace_independent: bool = True


@dataclass(frozen=True)
class ToolEffectContract:
    tool: str
    tool_version: str = "unknown"
    inputs: tuple[str, ...] = ()
    preconditions: tuple[str, ...] = ()
    success_predicate: tuple[str, ...] = ()
    guaranteed_effects: tuple[str, ...] = ()
    possible_effects: tuple[str, ...] = ()
    failure_no_effect: FourValue = FourValue.UNKNOWN
    reads: tuple[str, ...] = ()
    writes: tuple[str, ...] = ()
    entity_fields: tuple[str, ...] = ()
    freshness: str = "unknown"
    idempotent: FourValue = FourValue.UNKNOWN
    entity_key_mapping: tuple[tuple[str, str], ...] = ()
    provenance_transform: str = "preserve"
    evidence_source: str = "SCHEMA_EXPLICIT"
    provenance: str = "schema_only"


@dataclass(frozen=True)
class NormalizedEvent:
    id: str
    index: int
    role: str
    kind: str
    name: str | None
    value: Any
    json_valid: bool
    source: Span
    call_id: str | None = None


@dataclass(frozen=True)
class EvidenceRecord:
    id: str
    event_id: str
    subject: str
    predicate: str
    object: Any
    status: EvidenceStatus
    source: Span
    entities: tuple[tuple[str, Any], ...] = ()
    freshness: int | None = None
    provenance: str = "trace"
    completeness_certificate: str | None = None


@dataclass(frozen=True)
class Claim:
    id: str
    kind: ClaimKind
    subject: str
    predicate: str
    object: Any
    source: Span
    modality: str = "asserted"
    entities: tuple[tuple[str, Any], ...] = ()
    extractor: str = "deterministic"


@dataclass(frozen=True)
class ClaimCoverageItem:
    span: Span
    status: str
    reason: str
    claim_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class ClaimExtraction:
    claims: tuple[Claim, ...]
    coverage: tuple[ClaimCoverageItem, ...]
    extractor: str


@dataclass(frozen=True)
class Binding:
    claim_id: str
    evidence_ids: tuple[str, ...]
    status: FourValue
    reason: str


@dataclass(frozen=True)
class PropositionResult:
    proposition: str
    value: FourValue
    evidence_ids: tuple[str, ...] = ()
    rule_ids: tuple[str, ...] = ()
    reason: str = ""


@dataclass
class MonitorResult:
    status: FourValue
    label: int
    used_fallback: bool
    policy: PolicyBundle
    events: list[NormalizedEvent] = field(default_factory=list)
    evidence: list[EvidenceRecord] = field(default_factory=list)
    claims: list[Claim] = field(default_factory=list)
    bindings: list[Binding] = field(default_factory=list)
    propositions: list[PropositionResult] = field(default_factory=list)
    diagnostics: list[str] = field(default_factory=list)
    internal_verdict: str = "UNRESOLVED"
    binary_mapping_version: str = "strict-v1"

    def to_dict(self) -> dict[str, Any]:
        return asdict(self)
