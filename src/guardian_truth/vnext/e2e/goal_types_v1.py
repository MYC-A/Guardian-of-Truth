"""E2E V1 Goal-axis formal contracts (spec sections 57-88).

New versioned types.  Per spec sections 176-178 the historical FR1/E5/
Conservative implementations are HISTORICAL_SOURCE_UNAVAILABLE; these types
implement the ARCHITECTURE_CONTRACT_KNOWN from this spec and are never
presented as the historical artifacts.

Everything here is immutable and deterministic: no LLM, no network, no
wall-clock.  The LLM-facing schemas live in the frontend modules; this module
defines the canonical types the trusted pipeline (E5 -> assembler ->
composition -> lowering) consumes.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class FrameKind(str, Enum):
    DESIRED_OUTCOME = "DESIRED_OUTCOME"
    AUTHORIZATION = "AUTHORIZATION"
    PROHIBITION = "PROHIBITION"
    OBLIGATION = "OBLIGATION"
    GUARD = "GUARD"


class E5Resolution(str, Enum):
    """Spec section 74: exactly four cases, nothing else."""

    RESOLVED_EXACT = "RESOLVED_EXACT"
    RESOLVED_UNIQUE_QUOTE = "RESOLVED_UNIQUE_QUOTE"
    AMBIGUOUS = "AMBIGUOUS"
    UNRESOLVED = "UNRESOLVED"


class TargetLevel(str, Enum):
    ATTEMPT = "ATTEMPT"
    ACTION = "ACTION"
    EFFECT = "EFFECT"
    STATE = "STATE"
    INFORMATION = "INFORMATION"
    UNKNOWN = "UNKNOWN"


@dataclass(frozen=True)
class SourceText:
    """One firewall-safe source document with a stable identity."""

    source_id: str
    role: str          # USER | SYSTEM (firewall-admissible roles only)
    text: str

    def __post_init__(self):
        if not self.source_id or self.role not in {"USER", "SYSTEM"} or not isinstance(self.text, str):
            raise ValueError("explicit source identity, admissible role and text required")


@dataclass(frozen=True)
class ExtractiveRef:
    """Spec section 73: source_id + offsets + exact quote."""

    source_id: str
    start: int
    end: int
    quote: str

    def __post_init__(self):
        if (not self.source_id or type(self.start) is not int or type(self.end) is not int
                or not self.quote or self.start < 0 or self.end <= self.start):
            raise ValueError("explicit extractive identity and non-empty span required")


@dataclass(frozen=True)
class E5Result:
    ref: ExtractiveRef
    resolution: E5Resolution
    resolved: ExtractiveRef | None   # canonical ref after repair (Case 2)

    @property
    def ok(self) -> bool:
        return self.resolution in {E5Resolution.RESOLVED_EXACT, E5Resolution.RESOLVED_UNIQUE_QUOTE}


@dataclass(frozen=True)
class GroundedProposition:
    """A proposition that survived E5 with a resolved extractive anchor."""

    text: str
    anchor: ExtractiveRef
    resolution: E5Resolution

    def __post_init__(self):
        if not self.text or self.resolution not in {E5Resolution.RESOLVED_EXACT,
                                                    E5Resolution.RESOLVED_UNIQUE_QUOTE}:
            raise ValueError("grounded proposition requires resolved anchor")


@dataclass(frozen=True)
class RuleFrameRaw:
    """One LLM-proposed frame BEFORE E5/assembler (untrusted candidate).

    Field names mirror spec section 70.  All semantic fields are optional at
    the raw stage; the assembler enforces which are mandatory per kind.
    """

    frame_id_local: str
    kind: str                        # FrameKind value or UNKNOWN
    content: ExtractiveRef | None
    bearer: ExtractiveRef | None     # subject_or_bearer
    entity: ExtractiveRef | None     # entity_or_resource
    conditions: tuple[ExtractiveRef, ...] = ()
    exceptions: tuple[ExtractiveRef, ...] = ()
    temporal: str = "NONE"           # NONE | BEFORE | AFTER | UNKNOWN
    temporal_event: ExtractiveRef | None = None
    coordination: str = "NONE"       # AND | OR | NONE | UNKNOWN
    choice: str = "UNKNOWN"          # EXACTLY_ONE | ANY_OF | ALL_OF | NONE | UNKNOWN
    target_level: str = "UNKNOWN"    # TargetLevel value or UNKNOWN
    alternatives: tuple[ExtractiveRef, ...] = ()   # OR/ANY_OF alternatives for the content
    unresolved_fields: tuple[str, ...] = ()


@dataclass(frozen=True)
class GoalFrame:
    """Canonical assembled frame (trusted representation)."""

    frame_id: str                    # assembler-assigned canonical identity
    frontend: str                    # conservative | rule_frames
    kind: FrameKind
    content: GroundedProposition | None
    bearer: GroundedProposition | None
    entity: GroundedProposition | None
    conditions: tuple[GroundedProposition, ...]
    exceptions: tuple[GroundedProposition, ...]
    alternatives: tuple[GroundedProposition, ...]   # ANY_OF content alternatives
    temporal: str                    # NONE | BEFORE | AFTER (event in temporal_event)
    temporal_event: GroundedProposition | None
    coordination: str                # AND | OR | NONE
    choice: str                      # EXACTLY_ONE | ANY_OF | ALL_OF | NONE
    target_level: TargetLevel
    source_support: tuple[ExtractiveRef, ...]

    def __post_init__(self):
        if self.kind in {FrameKind.DESIRED_OUTCOME, FrameKind.PROHIBITION,
                         FrameKind.OBLIGATION, FrameKind.GUARD} and self.content is None:
            raise ValueError("material frame kinds require grounded content")
        if self.kind is FrameKind.AUTHORIZATION and (self.content is None or not self.alternatives):
            raise ValueError("authorization requires grounded content and alternatives")
        if self.temporal in {"BEFORE", "AFTER"} and self.temporal_event is None:
            raise ValueError("temporal relation requires grounded event")


@dataclass(frozen=True)
class GoalContract:
    """Canonical Goal representation (spec section 57): the lowered common
    form of both frontends' outputs."""

    contract_id: str                 # e.g. goal:conservative / goal:rule_frames
    frontend: str
    source_ids: tuple[str, ...]      # firewall sources this contract read
    frames: tuple[GoalFrame, ...]
    rejected_frames: tuple[tuple[str, str], ...]   # (local_id, reason) — never repaired
    unresolved_fields: tuple[str, ...]

    @property
    def desired_outcomes(self) -> tuple[GoalFrame, ...]:
        return tuple(f for f in self.frames if f.kind is FrameKind.DESIRED_OUTCOME)

    @property
    def prohibitions(self) -> tuple[GoalFrame, ...]:
        return tuple(f for f in self.frames if f.kind is FrameKind.PROHIBITION)

    @property
    def obligations(self) -> tuple[GoalFrame, ...]:
        return tuple(f for f in self.frames if f.kind is FrameKind.OBLIGATION)

    @property
    def authorizations(self) -> tuple[GoalFrame, ...]:
        return tuple(f for f in self.frames if f.kind is FrameKind.AUTHORIZATION)


# --------------------------------------------------------------- binding layer

class BindingLevel(str, Enum):
    ATTEMPT = "ATTEMPT"       # the invocation attempt itself
    COMPLETED = "COMPLETED"   # a completed, trusted-contract-confirmed action


@dataclass(frozen=True)
class BindingCheck:
    """One argument constraint: presence of a field, or literal values."""

    path: tuple[str, ...]
    allowed_json: tuple[str, ...]     # canonical JSON literals (non-empty)
    presence_only: bool = False       # True: only path presence matters
    quote: str = ""                   # normative/trajectory grounding quote

    def __post_init__(self):
        if not self.path or not all(isinstance(key, str) and key for key in self.path):
            raise ValueError("explicit field path required")
        if not self.allowed_json or any(not isinstance(item, str) or not item for item in self.allowed_json):
            raise ValueError("canonical literal values required")


@dataclass(frozen=True)
class ObservationBinding:
    """A state proposition bound to a trusted result-field observation.

    entity_path: the argument path identifying WHICH entity the observation
    is about (read deterministically from the target call's arguments at
    lowering time); empty means the state is not entity-scoped.
    """

    tool: str
    path: tuple[str, ...]
    expected_json: str               # canonical literal
    entity_path: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.tool or not self.path or not self.expected_json:
            raise ValueError("explicit observation identity required")
        if not all(isinstance(key, str) and key for key in self.entity_path):
            raise ValueError("explicit entity path required")


@dataclass(frozen=True)
class AtomBindingCandidate:
    """One candidate trajectory binding of ONE semantic unit (catalog atom).

    Multiple candidates for the same unit = genuine identity ambiguity ->
    separate binding alternatives -> separate worlds (never collapsed).
    entity_path: argument path identifying the entity this action/event is
    about (for entity-scoped state/event evidence atoms).
    """

    unit_id: str                     # catalog atom, e.g. action:cancel_booking
    tool: str
    level: BindingLevel
    argument_checks: tuple[BindingCheck, ...] = ()
    observation: ObservationBinding | None = None
    event_tool: str | None = None    # for event: atoms, the tool realizing the event
    actor_role: str | None = None    # for actor: atoms: assistant | user
    entity_path: tuple[str, ...] = ()
    quotes: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.unit_id or not self.tool:
            raise ValueError("explicit unit and tool identity required")
        if not all(isinstance(key, str) and key for key in self.entity_path):
            raise ValueError("explicit entity path required")


@dataclass(frozen=True)
class OutcomeBinding:
    """A goal outcome proposition bound to the tools that serve it."""

    unit_id: str                     # goal frame content unit id
    serving_tools: tuple[str, ...]
    level: BindingLevel
    argument_checks: tuple[BindingCheck, ...] = ()   # entity/value constraints
    action_servable: bool = True     # False: informational, not action-checkable
    quotes: tuple[str, ...] = ()

    def __post_init__(self):
        if not self.unit_id:
            raise ValueError("explicit outcome unit identity required")
        if self.action_servable and not self.serving_tools:
            raise ValueError("action-servable outcome requires serving tools")
        if any(not tool for tool in self.serving_tools):
            raise ValueError("explicit tool names required")


@dataclass(frozen=True)
class BindingRecord:
    """The full deterministic binding result for one case (arm-independent)."""

    atom_bindings: tuple[tuple[str, tuple[AtomBindingCandidate, ...]], ...]
    outcome_bindings: tuple[tuple[str, tuple[OutcomeBinding, ...]], ...]
    unbound_units: tuple[str, ...]
    failures: tuple[str, ...]

    def atom_candidates(self, atom: str) -> tuple[AtomBindingCandidate, ...]:
        for unit, candidates in self.atom_bindings:
            if unit == atom:
                return candidates
        return ()

    def outcome_candidates(self, unit_id: str) -> tuple[OutcomeBinding, ...]:
        for unit, candidates in self.outcome_bindings:
            if unit == unit_id:
                return candidates
        return ()
