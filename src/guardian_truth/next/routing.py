"""Observable slow-path triggers and progress/stop contracts."""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class SlowTrigger(str, Enum):
    UNKNOWN_POLICY_FIELD = "unknown_policy_field"
    UNSUPPORTED_RULE = "unsupported_rule"
    UNRESOLVED_REFERENCE = "unresolved_document_reference"
    ORPHAN_QUALIFIER = "orphan_qualifier"
    CANDIDATE_DISAGREEMENT = "policy_candidate_disagreement"
    PARSER_MODEL_DISAGREEMENT = "parser_model_disagreement"
    CONDITION_AMBIGUITY = "condition_exception_ambiguity"
    TEMPORAL_AMBIGUITY = "temporal_ambiguity"
    FRESHNESS_AMBIGUITY = "freshness_ambiguity"
    PROVENANCE_REQUIRED = "provenance_requirement"
    TOOL_EFFECT_UNKNOWN = "tool_effect_unknown"
    BUSINESS_SUCCESS_UNKNOWN = "business_success_unknown"
    ENTITY_BINDING_CHANGES_VERDICT = "entity_binding_changes_verdict"
    CLAIM_COVERAGE_INCOMPLETE = "claim_coverage_incomplete"
    ABSENCE_WITHOUT_COMPLETENESS = "absence_without_completeness_certificate"
    COUNTEREXAMPLE_FOUND = "counterexample_found"
    JUDGE_DISAGREEMENT = "query_conditioned_judge_disagreement"
    REFUSAL_FEASIBILITY = "false_refusal_feasibility_needed"


class StopReason(str, Enum):
    EQUIVALENT_CANDIDATES = "remaining_candidates_equivalent"
    INDEPENDENT_WITNESS = "independent_witness_resolved"
    REPRESENTATION_GAP = "representation_gap"
    BUDGET_EXHAUSTED = "budget_exhausted"
    HUMAN_INTENT_REQUIRED = "human_author_intent_required"


@dataclass(frozen=True)
class SlowPathStep:
    trigger: SlowTrigger
    method: str
    evidence_before: tuple[str, ...]
    evidence_after: tuple[str, ...]
    calls_used: int
    stop_reason: StopReason | None = None

    @property
    def added_evidence(self) -> tuple[str, ...]:
        before = set(self.evidence_before)
        return tuple(item for item in self.evidence_after if item not in before)


def validate_step(step: SlowPathStep, *, max_calls: int = 2) -> None:
    if step.calls_used < 0 or step.calls_used > max_calls:
        raise ValueError("slow-path call budget exceeded")
    if step.stop_reason is None and not step.added_evidence:
        raise ValueError("slow path must add evidence or stop")
