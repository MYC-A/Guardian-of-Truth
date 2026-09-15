"""Small immutable proof language. It contains no natural-language interpreter."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum

from .types import CoreStatus, EntityRef, Reason, Truth


class AtomKind(str, Enum):
    TARGET_CALL_MATCH = "TARGET_CALL_MATCH"
    OBSERVED_STATE = "OBSERVED_STATE"
    RESULT_FIELD = "RESULT_FIELD"
    CALL_ATTEMPTED = "CALL_ATTEMPTED"
    ACTION_COMPLETED = "ACTION_COMPLETED"
    HISTORICAL_ACTION = "HISTORICAL_ACTION"
    CAUSAL_ATTRIBUTION = "CAUSAL_ATTRIBUTION"


class TimeMode(str, Enum):
    AT = "AT"
    THROUGH = "THROUGH"
    LATEST_OBSERVATION = "LATEST_OBSERVATION"


@dataclass(frozen=True)
class ArgumentConstraint:
    """Exact argument membership, not an assertion about external state.

    presence_only (E2E V1 additive extension, default False preserves the
    baseline semantics exactly): when True the constraint is satisfied by the
    mere presence of the field path in the call arguments — the semantic
    action IS the setting of that field — and the field being absent proves
    the constraint FALSE (the action did not happen), never UNKNOWN.  When
    False the baseline value-membership semantics applies (absent path ->
    UNKNOWN, present path -> membership test).
    """
    path: tuple[str, ...]
    allowed_json: tuple[str, ...]
    presence_only: bool = False

    def __post_init__(self):
        from guardian_truth.parsing import decode_json
        from .integrity import canonical
        if not self.path or not all(isinstance(key, str) and key for key in self.path) or not self.allowed_json:
            raise ValueError("explicit field path and nonempty allowed values required")
        if type(self.presence_only) is not bool:
            raise ValueError("explicit presence flag required")
        for encoded in self.allowed_json:
            value, valid = decode_json(encoded)
            if not valid or canonical(value).decode("utf-8") != encoded:
                raise ValueError("canonical finite argument values required")


@dataclass(frozen=True)
class ProofAtom:
    atom_id: str
    kind: AtomKind
    entity: EntityRef
    predicate: str
    expected_json: str
    actor: str | None
    time_mode: TimeMode
    time_index: int
    call_id: str | None = None
    effect_predicate: str | None = None
    effect_expected_json: str | None = None
    argument_constraints: tuple[ArgumentConstraint, ...] = ()

    def __post_init__(self):
        from guardian_truth.parsing import decode_json
        from .integrity import canonical
        if not isinstance(self.kind, AtomKind) or not isinstance(self.time_mode, TimeMode) or not isinstance(self.entity, EntityRef):
            raise ValueError("canonical typed atom required")
        value, valid = decode_json(self.expected_json)
        if not valid or canonical(value).decode("utf-8") != self.expected_json:
            raise ValueError("canonical finite JSON expected value required")
        if type(self.time_index) is not int or not self.atom_id or not self.predicate:
            raise ValueError("explicit atom identity/predicate/time required")
        if self.kind not in {AtomKind.OBSERVED_STATE, AtomKind.RESULT_FIELD} and self.time_mode is TimeMode.LATEST_OBSERVATION:
            raise ValueError("latest observation is not an action or causality time mode")
        if self.kind is AtomKind.HISTORICAL_ACTION and self.time_mode is not TimeMode.THROUGH:
            raise ValueError("historical action is queried over history, not sampled state")
        if self.kind is AtomKind.TARGET_CALL_MATCH and (self.time_mode is not TimeMode.AT or type(value) is not bool):
            raise ValueError("target invocation comparison requires an exact event and Boolean expectation")
        if self.argument_constraints and self.kind is not AtomKind.TARGET_CALL_MATCH:
            raise ValueError("argument conditions cannot masquerade as business effects")


@dataclass(frozen=True)
class AbsenceScope:
    scope_id: str
    entity: EntityRef
    predicate: str
    actor: str
    through_index: int
    universe_source: str
    # This is a trusted product/source assumption, never an LLM-generated flag.
    closed_action_universe: tuple[str, ...]


@dataclass(frozen=True)
class PrimitiveProof:
    atom: ProofAtom
    value: Truth
    supports: tuple[str, ...]
    refutes: tuple[str, ...]
    absence_scope_id: str | None = None
    reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True)
class Obligation:
    obligation_id: str
    hypothesis_id: str
    claim_id: str | None
    atom: ProofAtom
    must_be_true: bool
    # Conjunctive antecedent; empty means unconditional. No string eval.
    conditions: tuple[ProofAtom, ...] = ()

    def __post_init__(self):
        if type(self.must_be_true) is not bool:
            raise ValueError("explicit obligation polarity required")


@dataclass(frozen=True)
class InterpretationAxis:
    name: str
    choice_ids: tuple[str, ...]
    universe_source: str | None
    enumeration_complete: bool


@dataclass(frozen=True)
class WorldPlan:
    world_id: str
    choices: tuple[str, ...]
    obligations: tuple[Obligation, ...]
    unresolved_reasons: tuple[Reason, ...] = ()


@dataclass(frozen=True)
class WorldProof:
    world_id: str
    choices: tuple[str, ...]
    error_value: Truth
    obligation_safety: tuple[tuple[str, Truth], ...]
    primitives: tuple[PrimitiveProof, ...]


@dataclass(frozen=True)
class ProofProblem:
    axes: tuple[InterpretationAxis, ...]
    worlds: tuple[WorldPlan, ...]
    absence_scopes: tuple[AbsenceScope, ...] = ()


@dataclass(frozen=True)
class ProofCertificate:
    version: str
    status: CoreStatus
    source_sha256: str
    ledger_sha256: str
    registry_sha256: str
    problem_sha256: str
    world_proofs: tuple[WorldProof, ...]
    completeness_assumptions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class SolverResult:
    status: CoreStatus
    world_proofs: tuple[WorldProof, ...]
    reasons: tuple[Reason, ...]
    certificate: ProofCertificate | None = None


def truth_bits(value: Truth) -> tuple[bool, bool]:
    return {Truth.TRUE: (True, False), Truth.FALSE: (False, True),
            Truth.BOTH: (True, True), Truth.UNKNOWN: (False, False)}[value]


def bits_truth(positive: bool, negative: bool) -> Truth:
    return {(True, False): Truth.TRUE, (False, True): Truth.FALSE,
            (True, True): Truth.BOTH, (False, False): Truth.UNKNOWN}[positive, negative]


def negate(value: Truth) -> Truth:
    positive, negative = truth_bits(value)
    return bits_truth(negative, positive)


def conjunction(values: tuple[Truth, ...]) -> Truth:
    bits = [truth_bits(value) for value in values]
    return bits_truth(all(positive for positive, _ in bits), any(negative for _, negative in bits))


def disjunction(values: tuple[Truth, ...]) -> Truth:
    bits = [truth_bits(value) for value in values]
    return bits_truth(any(positive for positive, _ in bits), all(negative for _, negative in bits))
