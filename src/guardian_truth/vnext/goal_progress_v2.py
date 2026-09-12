"""Source-protocol fresh-plan evidence, distinct from a guessed business fact."""

from dataclasses import dataclass
from enum import Enum

from .types import Reason, Truth


@dataclass(frozen=True)
class PlanActivation:
    event_index: int
    authority_basis: str
    source_completeness_basis: str

    def __post_init__(self):
        if (type(self.event_index) is not int or self.event_index < 0
                or self.authority_basis not in {"USER_DECLARED_FRESH_PLAN", "SOURCE_PROTOCOL_FRESH_PLAN"}
                or not self.source_completeness_basis):
            raise ValueError("explicit application/source activation contract required; never LLM-inferred")


class PlanProgressKind(str, Enum):
    ACTIVE_STEP = "ACTIVE_STEP"
    COMPLETED_STEP = "COMPLETED_STEP"


@dataclass(frozen=True)
class PlanProgressAtom:
    atom_id: str
    source_id: str
    expected_step: int
    before_index: int
    kind: PlanProgressKind = PlanProgressKind.ACTIVE_STEP
    actor: str = "assistant"

    @property
    def time_index(self):
        return self.before_index - 1

    def __post_init__(self):
        if (not self.atom_id or not self.source_id or type(self.expected_step) is not int
                or self.expected_step < 0 or type(self.before_index) is not int or self.before_index < 0):
            raise ValueError("typed source progress premise required")
        if not isinstance(self.kind, PlanProgressKind) or self.actor not in {"assistant", "user", "entity"}:
            raise ValueError("typed logical plan-progress kind and actor required")


@dataclass(frozen=True)
class PlanProgressProof:
    atom: PlanProgressAtom
    value: Truth
    supports: tuple[str, ...]
    refutes: tuple[str, ...]
    reasons: tuple[Reason, ...] = ()


def prove_plan_progress(atom, context, ledger):
    activation = context.plan_activation
    source = context.parsed.source(atom.source_id)
    unknown = PlanProgressProof(atom, Truth.UNKNOWN, (), (), (Reason.EVIDENCE_INCOMPLETE,))
    if (activation is None or not ledger.history_complete
            or ledger.completeness_basis != activation.source_completeness_basis
            or source is None or source.kind != "PLAN_STEP"
            or source.plan_index != atom.expected_step
            or not 0 <= activation.event_index < atom.before_index < len(ledger.events)):
        return unknown
    event = ledger.events[activation.event_index]
    target = ledger.events[atom.before_index]
    if (event.actor != "system" or event.kind != "text" or event.source.document != "prompt"
            or context.declared_goal not in event.raw_text
            or any(step not in event.raw_text for step in context.ordered_plan)
            or target.source.document != "response" or target.kind != "call"):
        return unknown
    # Completeness is relative to the explicit FRESH activation boundary. A bare
    # empty retrieval, an arbitrary truncated prefix or a model step index is NOT
    # such a boundary. Any intervening event needs separate progress semantics.
    if ledger.events[activation.event_index + 1:atom.before_index]:
        return unknown
    value = (Truth.TRUE if atom.expected_step == 0 else Truth.FALSE) if atom.kind is PlanProgressKind.ACTIVE_STEP else Truth.FALSE
    witness = ("source-plan-activation:" + event.event_id, "complete-empty-plan-prefix:" + target.event_id)
    return PlanProgressProof(atom, value, witness if value is Truth.TRUE else (), witness if value is Truth.FALSE else ())
