"""Frozen Goal-layer proof records; meanings are conditional, never T1 facts."""

from dataclasses import dataclass

from .goal_native import NativeGoalParse
from .goal_call_membership_v2 import GoalCallMembershipAtom, GoalCallMembershipProof
from .goal_progress_v2 import PlanActivation, PlanProgressAtom, PlanProgressProof
from .proof_records import AbsenceScope, PrimitiveProof, ProofAtom
from .types import CoreStatus, Reason, ToolIdentity, Truth


@dataclass(frozen=True)
class GoalRoleBinding:
    source_id: str
    role: str
    atom: ProofAtom | PlanProgressAtom | GoalCallMembershipAtom
    meaning_source_ids: tuple[str, ...]


@dataclass(frozen=True)
class GoalBindingChoice:
    choice_id: str
    reading_id: str
    bindings: tuple[GoalRoleBinding, ...]


@dataclass(frozen=True)
class GoalProofContext:
    declared_goal: str
    ordered_plan: tuple[str, ...]
    allowed_scope_json: str
    prompt: str
    response: str
    tool_metadata: tuple[ToolIdentity, ...]
    parsed: NativeGoalParse
    choices: tuple[GoalBindingChoice, ...]
    # Completeness relative to SUPPLIED meaning candidates, not all NL meanings.
    candidate_basis: str
    candidate_enumeration_complete: bool
    absence_scopes: tuple[AbsenceScope, ...] = ()
    plan_activation: PlanActivation | None = None


@dataclass(frozen=True)
class GoalWorldProof:
    choice_id: str
    reading_id: str
    clause_safety: tuple[tuple[str, Truth], ...]
    primitives: tuple[PrimitiveProof | PlanProgressProof | GoalCallMembershipProof, ...]
    error_value: Truth


@dataclass(frozen=True)
class GoalProofCertificate:
    version: str
    status: CoreStatus
    source_sha256: str
    ledger_sha256: str
    registry_sha256: str
    world_proofs: tuple[GoalWorldProof, ...]
    assumptions: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class GoalLayerDecision:
    status: CoreStatus
    world_proofs: tuple[GoalWorldProof, ...]
    reasons: tuple[Reason, ...]
    certificate: GoalProofCertificate | None
    certificate_valid: bool | None
    certificate_errors: tuple[str, ...] = ()


ASSUMPTIONS = (
    ("SEMANTIC_SCOPE", "conditional on every supplied grounded Goal reading and binding candidate; unrestricted NL closure not asserted"),
    ("PRIMITIVE_FACTS", "reconstructed original source and independently re-proved argument/result/trusted-effect premises"),
    ("PLAN_ACTIVATION", "fresh-plan progress is used only under an explicit trusted source protocol and complete empty prefix; not an LLM estimate or general absence proof"),
    ("VERDICT_SCOPE", "Goal-layer obligation violations only; not a complete policy/claim Core safety decision"),
)
