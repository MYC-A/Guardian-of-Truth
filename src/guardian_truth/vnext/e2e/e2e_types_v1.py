"""E2E V1 formal contracts (Phase 1).

Frozen, versioned, immutable types shared by the E2E frontends, the compiled
program space, the goal contract space and the composition core. These records
are SEMANTIC CANDIDATES, never evidence. Every source-linked part carries an
exact quote; offsets are resolved only by the deterministic E5 resolver.
"""

from __future__ import annotations

from dataclasses import dataclass, field

POLICY_FRONTENDS = ("h0", "grs")
GOAL_FRONTENDS = ("conservative", "rule_frames")
LITERAL_KINDS = ("ACTION", "STATE", "ACTOR", "ENTITY", "CLAIM", "EVIDENCE", "VALUE", "EFFECT")
MODALITIES = ("PERMIT", "FORBID", "REQUIRE")
RELATIONS = ("NONE", "IF", "ONLY_IF", "UNLESS", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN")
FRAME_KINDS = ("DESIRED_OUTCOME", "AUTHORIZATION", "PROHIBITION", "OBLIGATION", "GUARD", "UNKNOWN")
TARGET_LEVELS = ("ATTEMPT", "ACTION", "EFFECT", "STATE", "INFORMATION", "UNKNOWN")


# ---------------------------------------------------------------- policy: H0

@dataclass(frozen=True)
class SemanticLiteral:
    """Spec 30: typed semantic leaf with exact source support."""
    kind: str
    polarity: str            # POSITIVE | NEGATED
    normalized_key: str | None
    quote: str

    def __post_init__(self):
        if self.kind not in LITERAL_KINDS or self.polarity not in ("POSITIVE", "NEGATED"):
            raise ValueError("typed literal kind/polarity required")
        if not self.quote:
            raise ValueError("exact source quote required")


@dataclass(frozen=True)
class PolicyFlatStructure:
    """Spec 29: flat conservative single-structure H0 parse of the whole policy."""
    modality: str            # PERMISSION | PROHIBITION | REQUIREMENT | UNKNOWN
    actor: str               # grounded actor key or UNKNOWN
    regulated_kind: str
    facet: str
    relation: str
    target_clauses: tuple[SemanticLiteral, ...]
    condition_literals: tuple[SemanticLiteral, ...]
    exception_literals: tuple[SemanticLiteral, ...]
    condition_mode: str      # ALL | ANY | UNKNOWN
    exception_mode: str      # ALL | ANY | UNKNOWN
    quantification: str      # ALL | ANY | EXACTLY_ONE | AT_LEAST_ONE | UNKNOWN
    source_quotes: tuple[str, ...]
    unresolved_terms: tuple[str, ...]


@dataclass(frozen=True)
class FrontendCandidate:
    """One frontend attempt outcome. UNAVAILABLE is never safe (spec 34)."""
    frontend: str
    available: bool
    failure: str | None      # TRANSPORT | SCHEMA | COMPILE | None
    detail: str | None = None


# ----------------------------------------------------------------- policy: GRS

@dataclass(frozen=True)
class InventoryAtom:
    atom_id: str             # F# only
    kind: str                # LITERAL_KINDS
    meaning: str | None      # normalized key
    quote: str


@dataclass(frozen=True)
class SurfaceMarker:
    marker_id: str           # M# / R# only
    surface: str
    quote: str


@dataclass(frozen=True)
class GroundedInventory:
    facts: tuple[InventoryAtom, ...]
    modality_markers: tuple[SurfaceMarker, ...]
    relation_markers: tuple[SurfaceMarker, ...]


# GRS DSL: closed grammar (spec 45). AST nodes are immutable tuples.
# Expr := ("F", fact_id) | ("NOT", expr) | ("AND", expr, ...) | ("OR", expr, ...)

@dataclass(frozen=True)
class DslRule:
    modality: str            # PERMIT | FORBID | REQUIRE
    target: str              # F#
    modifiers: tuple[tuple[str, str], ...]   # (name, serialized_expr); name in MODIFIER set

    def __post_init__(self):
        if self.modality not in MODALITIES or not self.target.startswith("F"):
            raise ValueError("closed DSL vocabulary required")
        for name, _ in self.modifiers:
            if name not in {"WHEN", "UNLESS", "ACTOR", "BEFORE", "AFTER", "UNTIL", "SCOPE", "TOGETHER", "CHOICE"}:
                raise ValueError("closed DSL modifier set required")


@dataclass(frozen=True)
class DslRuleset:
    rules: tuple[DslRule, ...]


# ------------------------------------------------- compiled common program space

@dataclass(frozen=True)
class CompiledCondition:
    """Condition/exception literal compiled to a deterministic atom spec."""
    key: str                 # tool name (catalog match) or semantic key
    negated: bool            # True => atom expected false (UNLESS / NEGATED polarity)
    bound: str               # "HISTORY" (call attempted before target) | "UNKNOWN"
    quote: str
    literal_kind: str = "ACTION"   # ACTION => call semantics; STATE => observation semantics


@dataclass(frozen=True)
class CompiledRule:
    """Common behavioral program space entry shared by H0, GRS and goal lowering.

    kind:
      FORBID_CALL       - prohibition of invoking a tool (attempt level)
      REQUIRE_PRESERVE  - field-preservation: FORBID(modify F) compiled with a
                          trusted state contract into REQUIRE(F in values)
      REQUIRE_CALL      - existential requirement that a tool was invoked
      GOAL_CALL         - goal action authorization: every target call must be
                          this action within scope (scope expansion violates)
      GOAL_ALTERNATIVES - authorization alternatives: per call, OR over the
                          alternative action atoms (allowed alternatives, not
                          an instruction to execute all of them)
      PERMIT            - recorded, produces no obligation (permission is not
                          an obligation; NO_VIOLATION != PERMITTED)
    """
    rule_id: str
    kind: str
    modality: str           # original frontend modality (PERMIT|FORBID|REQUIRE)
    action_key: str | None  # semantic action key (tool-name-like)
    actor: str              # assistant | user | UNKNOWN
    relation: str
    conditions: tuple[CompiledCondition, ...]
    exceptions: tuple[CompiledCondition, ...]
    scope: tuple[tuple[str, tuple[str, ...]], ...]   # field -> allowed canonical values
    source_quotes: tuple[str, ...]
    unresolved_terms: tuple[str, ...]
    frontend: str
    alternatives: tuple[str, ...] = ()   # GOAL_ALTERNATIVES: alternative action keys


@dataclass(frozen=True)
class PolicyReading:
    """One admissible whole-policy interpretation = a behavioral program."""
    reading_id: str          # policy:h0:r0 | policy:grs:r1 ...
    frontend: str
    rules: tuple[CompiledRule, ...]
    unresolved_terms: tuple[str, ...]


# ---------------------------------------------------------------------- goal

@dataclass(frozen=True)
class ExtractiveRef:
    """Spec 73: source-linked part. Offsets are hints; E5 resolves truth."""
    source_id: str
    start: int
    end: int
    quote: str


@dataclass(frozen=True)
class ScopeEntry:
    field: str
    values: tuple[str, ...]  # canonical JSON literals
    support: ExtractiveRef | None


@dataclass(frozen=True)
class GoalFrame:
    """Spec 70 RuleFrame (V1 field set). LLM fills semantics, never canonical IDs."""
    frame_kind: str
    target_level: str
    actor: str | None
    content_key: str | None
    entity_key: str | None
    scope: tuple[ScopeEntry, ...]
    conditions: tuple[str, ...]
    exceptions: tuple[str, ...]
    temporal: str            # NONE | BEFORE | AFTER | UNKNOWN
    coordination: str        # AND | OR | NONE | UNKNOWN
    choice: str              # EXACTLY_ONE | ANY_OF | ALL_OF | NONE | UNKNOWN
    support: tuple[ExtractiveRef, ...]
    unresolved_fields: tuple[str, ...]
    alternatives: tuple[str, ...] = ()   # explicitly authorized alternative action keys
    frame_id_local: int = -1


@dataclass(frozen=True)
class GoalContract:
    """Canonical assembled goal representation (spec 57 kinds)."""
    contract_id: str         # goal:conservative:r0 | goal:rule_frames:r1 ...
    frontend: str
    frames: tuple[GoalFrame, ...]
    unresolved_terms: tuple[str, ...]


# ------------------------------------------------------------ composition core

@dataclass(frozen=True)
class E2ESemantics:
    """Cycle-3 semantic gates for the causal ablation arms B0-B4.

    B0 (all False) reproduces the frozen E2E V1 semantics exactly.
    conservative_state : only trusted fresh reads and verified effects are
        state evidence; cross-time support/refutation is historical (BOTH
        only under proven persistence, UNKNOWN when an unproven mutation
        separates the evidence).
    alternative_groups : ANY_OF authorizations and multi-choice goal
        satisfactions lower into ONE disjunctive satisfaction group instead
        of independent obligations (authorization is not obligation).
    inconsistent_status : an obligation whose atom evidence is BOTH makes
        the world verdict BOTH so consensus surfaces INCONSISTENT instead of
        silently absorbing the contradiction.
    claim_typing : deterministic claim-adapter guards (entity-ref anchoring
        guard, flag-channel evidence for value-anchored state claims,
        representation-preserving literal coercion)."""
    conservative_state: bool = False
    alternative_groups: bool = False
    inconsistent_status: bool = False
    claim_typing: bool = False


FULL_SEMANTICS = E2ESemantics(conservative_state=True, alternative_groups=True,
                              inconsistent_status=True, claim_typing=True)

SEMANTICS_ARMS = {
    "B0": E2ESemantics(),
    "B1": E2ESemantics(conservative_state=True),
    "B2": E2ESemantics(conservative_state=True, alternative_groups=True),
    "B3": E2ESemantics(conservative_state=True, alternative_groups=True,
                       inconsistent_status=True, claim_typing=True),
    "B4": E2ESemantics(conservative_state=True, alternative_groups=True,
                       inconsistent_status=True, claim_typing=True),
}


@dataclass(frozen=True)
class DisjunctiveGroup:
    """Authorization alternatives: per target call, OR over allowed atoms.
    satisfaction_choices (B2): OR over alternative satisfaction bundles -
    each bundle is a conjunction of atoms; the group holds when ANY bundle
    holds (alternative ways to satisfy one goal, never independent
    obligations)."""
    group_id: str
    rule_id: str
    must_be_true: bool
    per_call_atoms: tuple[tuple[str, tuple[object, ...]], ...]   # (event_id, atoms)
    satisfaction_choices: tuple[tuple[object, ...], ...] = ()    # B2: OR over bundles


@dataclass(frozen=True)
class UnresolvedMarker:
    """World-level UNKNOWN conjunct: blocks NO_ERROR, never creates ERROR."""
    marker_id: str
    reason: str


@dataclass(frozen=True)
class ReadingOption:
    """One axis choice: obligations of one whole reading plus its unknowns."""
    option_id: str
    obligations: tuple[object, ...]           # Obligation records
    disjunctive_groups: tuple[DisjunctiveGroup, ...]
    unresolved_markers: tuple[UnresolvedMarker, ...]


@dataclass(frozen=True)
class E2ECaseInput:
    """Corpus case: full trajectory with trusted application metadata."""
    case_id: str
    family: str
    system_policy: str
    user_request: str
    history: tuple[str, ...]                  # marker-syntax events before the target
    target_response: str                      # marker-syntax target assistant output
    tool_metadata: tuple[dict, ...] = ()
    tool_schemas: tuple[dict, ...] = ()
    t1_contracts: tuple[dict, ...] = ()
    state_contract: dict | None = None        # trusted current field values (preservation)
    history_complete: bool = False
    completeness_basis: str | None = None
    authoritative_policy_readings: tuple[dict, ...] = ()   # oracle substitution (rule/frame rows)
    authoritative_goal_readings: tuple[dict, ...] = ()
    authoritative_policy_behaviors: tuple[dict, ...] = ()  # semantic closure (behavioral rows)
    authoritative_goal_behaviors: tuple[dict, ...] = ()
    gold_core_status: str = ""
    gold_binary: int | None = None
    notes: str = ""


@dataclass(frozen=True)
class E2EArmConfig:
    arm_id: str
    policy_frontends: tuple[str, ...]
    goal_frontends: tuple[str, ...]


ARMS = (
    E2EArmConfig("E0", ("h0",), ("conservative",)),
    E2EArmConfig("E1", ("grs",), ("conservative",)),
    E2EArmConfig("E2", ("h0",), ("rule_frames",)),
    E2EArmConfig("E3", ("grs",), ("rule_frames",)),
    E2EArmConfig("E4", ("h0", "grs"), ("conservative", "rule_frames")),
)
