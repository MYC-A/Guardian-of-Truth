"""Versioned Goal v3 contract and proof records; no NL parser or verdict logic."""

from dataclasses import dataclass
from enum import Enum

from .types import CoreStatus, Truth


class GoalRuleKind(str, Enum):
    REQUIRE_RESULT_TRUE = "REQUIRE_RESULT_TRUE"
    REQUIRE_ATTEMPT_BEFORE = "REQUIRE_ATTEMPT_BEFORE"
    WHEN_RESULT_TRUE_REQUIRE_ATTEMPT = "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT"
    REQUIRE_ATTEMPT_BY_SESSION = "REQUIRE_ATTEMPT_BY_SESSION"
    EXCEPTION_RESULT_TRUE = "EXCEPTION_RESULT_TRUE"


@dataclass(frozen=True)
class GoalCapabilityV3:
    name: str
    provider: str
    version: str
    entity_argument: str
    operation_class: str

    def __post_init__(self):
        if (not self.name or not self.provider or not self.version or not self.entity_argument
                or self.operation_class not in {"READ", "ACTION_ATTEMPT"}):
            raise ValueError("explicit versioned operation shape required")


@dataclass(frozen=True)
class GoalRuleV3:
    rule_id: str
    kind: GoalRuleKind
    source_id: str
    source_sha256: str
    trigger_tools: tuple[str, ...] = ()
    required_tool: str | None = None
    result_field: str | None = None
    exception_tool: str | None = None
    guard_tool: str | None = None

    def __post_init__(self):
        if (not self.rule_id or not isinstance(self.kind, GoalRuleKind) or not self.source_id
                or len(self.source_sha256) != 64):
            raise ValueError("versioned source-grounded rule identity required")
        if self.kind is not GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION and not self.trigger_tools:
            raise ValueError("step-local rule requires explicit triggering tools")
        if self.kind in {GoalRuleKind.REQUIRE_RESULT_TRUE,
                GoalRuleKind.WHEN_RESULT_TRUE_REQUIRE_ATTEMPT, GoalRuleKind.EXCEPTION_RESULT_TRUE} and not self.result_field:
            raise ValueError("result-dependent rule requires exact field")
        if self.kind is GoalRuleKind.EXCEPTION_RESULT_TRUE and not self.exception_tool:
            raise ValueError("exception must identify the prohibited target operation")
        if self.kind is GoalRuleKind.WHEN_RESULT_TRUE_REQUIRE_ATTEMPT and not self.guard_tool:
            raise ValueError("conditional rule requires an exogenous guard tool")
        if not self.required_tool:
            raise ValueError("rule requires exact source operation")


@dataclass(frozen=True)
class GoalWorldV3:
    world_id: str
    source_sha256: str
    entity: str
    capabilities: tuple[GoalCapabilityV3, ...]
    direct_tools: tuple[str, ...]
    auxiliary_tools: tuple[str, ...]
    forbidden_attempt_tools: tuple[str, ...]
    rules: tuple[GoalRuleV3, ...]
    authorization_closed: bool
    unresolved_terms: tuple[str, ...] = ()

    def __post_init__(self):
        names = [item.name for item in self.capabilities]
        if (not self.world_id or len(self.source_sha256) != 64 or not self.entity
                or len(set(names)) != len(names) or len({rule.rule_id for rule in self.rules}) != len(self.rules)
                or type(self.authorization_closed) is not bool):
            raise ValueError("complete immutable Goal world identity required")
        if set(self.direct_tools) & set(self.auxiliary_tools):
            raise ValueError("direct and auxiliary labels must be disjoint")


@dataclass(frozen=True)
class GoalContractV3:
    version: str
    source_sha256: str
    worlds: tuple[GoalWorldV3, ...]
    complete_world_inventory: bool
    completeness_basis: str | None

    def __post_init__(self):
        if (self.version != "guardian-goal-contract-v3" or len(self.source_sha256) != 64
                or not self.worlds or len({world.world_id for world in self.worlds}) != len(self.worlds)
                or type(self.complete_world_inventory) is not bool
                or self.complete_world_inventory and not self.completeness_basis):
            raise ValueError("explicit complete-or-open Goal reading inventory required")


@dataclass(frozen=True)
class GoalPrimitiveV3:
    primitive_id: str
    value: Truth
    supports: tuple[str, ...]
    refutes: tuple[str, ...]
    missing_evidence: tuple[str, ...]
    candidate_set_complete: bool
    scope: str


@dataclass(frozen=True)
class GoalRuleProofV3:
    rule_id: str
    value: Truth
    primitives: tuple[GoalPrimitiveV3, ...]
    pending: bool = False
    reason: str | None = None


@dataclass(frozen=True)
class GoalWorldProofV3:
    world_id: str
    status: CoreStatus
    alignment: str
    rule_proofs: tuple[GoalRuleProofV3, ...]
    violations: tuple[str, ...]
    unknowns: tuple[str, ...]
    contradictions: tuple[str, ...]
    pending: tuple[str, ...]


@dataclass(frozen=True)
class GoalCertificateV3:
    version: str
    status: CoreStatus
    source_sha256: str
    contract_sha256: str
    world_proofs: tuple[GoalWorldProofV3, ...]
    complete_world_inventory: bool
    dependency_scope: str


@dataclass(frozen=True)
class GoalDecisionV3:
    status: CoreStatus
    alignment: str
    world_proofs: tuple[GoalWorldProofV3, ...]
    certificate: GoalCertificateV3 | None
    certificate_valid: bool | None
    diagnostics: tuple[str, ...]
    scope: str = "GOAL_ALIGNMENT_CONTRACT_LAYER_NOT_WHOLE_GUARDIAN_CORE"
