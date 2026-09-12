"""Gold-isolated Policy Semantics V2 arm runner and paired scoring."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
from typing import Any, Iterable, Mapping

from guardian_truth.next.policy import compile_policy

from .policy_semantics import PolicyCase, PolicyDataset, score_policy_candidate


@dataclass(frozen=True)
class BlindPolicyCase:
    id: str
    family: str
    variant: str
    policy: str
    atom_catalog: tuple[str, ...]


def blind_policy_cases(dataset: PolicyDataset) -> tuple[BlindPolicyCase, ...]:
    """Return a proposal-safe view with no gold structure, program, or worlds."""
    return tuple(BlindPolicyCase(
        case.id, case.family, case.variant, case.policy, case.atom_catalog,
    ) for case in dataset.cases)


def _empty_structure(*, facet: str, target: str, relation: str = "UNCONDITIONAL",
                     identity: str = "ANY", quantification: str = "ANY") -> dict:
    return {
        "modality": "PROHIBITION",
        "actor": "assistant",
        "regulated_kind": "ACTION",
        "facet": facet,
        "target_clauses": [[target]],
        "relation": relation,
        "condition_literals": [],
        "exception_literals": [],
        "temporal": "NONE",
        "identity": identity,
        "provenance": "ANY",
        "quantification": quantification,
    }


def p0_proposal(case: BlindPolicyCase) -> dict:
    """Apply the unchanged exact compiler; no benchmark string list is used."""
    prefix = "⟦SYSTEM⟧\n<policy>"
    bundle = compile_policy(prefix + case.policy + "</policy>", arm="P0_CYCLE2")
    predicates = {rule.predicate for rule in bundle.rules}
    prediction = None
    if predicates == {"max_tool_calls"} and "turn:tool_call_count_gt_1" in case.atom_catalog:
        prediction = {
            "structure": _empty_structure(
                facet="tool_call_count", target="turn:tool_call_count_gt_1",
                quantification="AT_MOST_1_PER_TURN",
            ),
            "program": {
                "violation_clauses": [["turn:tool_call_count_gt_1"]],
                "permission_clauses": [],
            },
        }
    elif predicates == {"text_xor_tool_call"} and {
        "turn:has_message", "turn:has_tool_call",
    } <= set(case.atom_catalog):
        structure = _empty_structure(
            facet="turn_channels", target="turn:has_message",
            relation="AND_NOT_EACH", identity="SAME_TURN", quantification="NOT_BOTH",
        )
        structure["target_clauses"] = [["turn:has_message", "turn:has_tool_call"]]
        prediction = {
            "structure": structure,
            "program": {
                "violation_clauses": [["turn:has_message", "turn:has_tool_call"]],
                "permission_clauses": [],
            },
        }
    covered = sum(item.span.end - item.span.start for item in bundle.coverage
                  if item.status == "RULE")
    return {
        "case_id": case.id,
        "arm": "P0",
        "transport_status": "NOT_APPLICABLE",
        "schema_status": "VALID",
        "semantic_status": "PENDING_GOLD_JOIN",
        "representation_status": "SUPPORTED" if prediction else "UNSUPPORTED",
        "error_category": None,
        "prediction": prediction,
        "source_coverage": min(1.0, covered / len(case.policy)) if case.policy else 0.0,
        "served_model": None,
        "latency_ms": 0.0,
        "usage": {},
    }


def freeze_proposals(rows: Iterable[dict]) -> tuple[list[dict], str]:
    rows = list(rows)
    canonical = json.dumps(rows, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return rows, hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def score_proposals(rows: Iterable[dict], dataset: PolicyDataset) -> list[dict]:
    """Gold can enter only here, after proposal bytes have been frozen."""
    gold: Mapping[str, PolicyCase] = {case.id: case for case in dataset.cases}
    scored = []
    seen = set()
    for row in rows:
        key = (row["case_id"], row["arm"])
        if key in seen or row["case_id"] not in gold:
            raise ValueError("duplicate or unknown policy proposal")
        seen.add(key)
        item = {
            "case_id": row["case_id"],
            "arm": row["arm"],
            "family": gold[row["case_id"]].family,
            "variant": gold[row["case_id"]].variant,
            "transport_status": row["transport_status"],
            "schema_status": row["schema_status"],
            "representation_status": row["representation_status"],
            "semantic_outcome": "NOT_EVALUATED",
            "behavioral_semantic_correct": None,
            "behavioral_accuracy": None,
            "structural_accuracy": None,
            "exact_representation": None,
        }
        if row["schema_status"] == "VALID" and row["prediction"] is not None:
            score = score_policy_candidate(
                gold[row["case_id"]],
                row["prediction"]["structure"],
                row["prediction"]["program"],
            )
            item.update({
                "semantic_outcome": (
                    "SEMANTIC_CORRECT" if score["behavioral_semantic_correct"]
                    else "SEMANTIC_WRONG"
                ),
                "behavioral_semantic_correct": score["behavioral_semantic_correct"],
                "behavioral_accuracy": score["behavioral_accuracy"],
                "structural_accuracy": score["structural_accuracy"],
                "structural_fields": score["structural_fields"],
                "exact_representation": score["exact_representation"],
            })
        elif row["schema_status"] == "VALID":
            item.update({
                "semantic_outcome": "SEMANTIC_WRONG",
                "behavioral_semantic_correct": False,
                "behavioral_accuracy": 0.0,
                "structural_accuracy": 0.0,
                "exact_representation": False,
            })
        scored.append(item)
    return scored


def summarize_arm(proposals: Iterable[dict], scores: Iterable[dict], arm: str) -> dict:
    proposals = [row for row in proposals if row["arm"] == arm]
    scores = [row for row in scores if row["arm"] == arm]
    attempted = len(proposals)
    transport = sum(row["transport_status"] in {"SUCCESS", "NOT_APPLICABLE"} for row in proposals)
    valid = sum(row["schema_status"] == "VALID" for row in proposals)
    correct = sum(row["behavioral_semantic_correct"] is True for row in scores)
    evaluated = [row for row in scores if row["behavioral_semantic_correct"] is not None]
    return {
        "attempted": attempted,
        "transport_success": transport,
        "schema_valid": valid,
        "semantic_correct": correct,
        "reliability": valid / attempted if attempted else None,
        "conditional_semantic_quality": correct / valid if valid else None,
        "strict_operational_yield": correct / attempted if attempted else None,
        "mean_behavioral_accuracy": (
            sum(row["behavioral_accuracy"] for row in evaluated) / len(evaluated)
            if evaluated else None
        ),
        "mean_structural_accuracy": (
            sum(row["structural_accuracy"] for row in evaluated) / len(evaluated)
            if evaluated else None
        ),
        "exact_representation_accuracy": (
            sum(row["exact_representation"] is True for row in evaluated) / len(evaluated)
            if evaluated else None
        ),
        "supported_representations": sum(row["representation_status"] == "SUPPORTED" for row in proposals),
    }


def build_blocked_policy_report(dataset: PolicyDataset, gate_report: Mapping[str, Any]) -> dict:
    if gate_report.get("policy_benchmark_permitted") is not False:
        raise ValueError("blocked report requires a failed model gate")
    blind = blind_policy_cases(dataset)
    proposals, proposal_hash = freeze_proposals(p0_proposal(case) for case in blind)
    scores = score_proposals(proposals, dataset)
    return {
        "schema_version": "guardian-cycle2-policy-results-v1",
        "status": "EVALUATION_BLOCKED_BY_PROVIDER",
        "benchmark_sha256": dataset.digest,
        "cases_sha256": dataset.cases_digest,
        "gate_contract_sha256": gate_report.get("gate_contract_sha256"),
        "model_gate_status": gate_report.get("status"),
        "gold_visible_to_proposal_stage": False,
        "proposal_freeze_sha256": proposal_hash,
        "proposals_frozen_before_gold_join": True,
        "arms": {"P0": summarize_arm(proposals, scores, "P0")},
        "unavailable_arms": {
            "P1": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P2": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P3": "NOT_ESTABLISHED_PROVIDER_GATE_BLOCKED",
            "P4": "NOT_RUN_REQUIRES_VALID_P2",
        },
        "paired_p1_p2": {
            "status": "NO_CONCLUSION",
            "reason": "provider_reliability_gate_not_passed",
            "n_total": len(dataset.cases),
            "n_P1_valid": 0,
            "n_P2_valid": 0,
            "n_both_valid": 0,
            "P1_accuracy_on_both": None,
            "P2_accuracy_on_both": None,
            "P1_only_correct": 0,
            "P2_only_correct": 0,
            "both_correct": 0,
            "both_wrong": 0,
        },
        "proposals": proposals,
        "scores": scores,
    }
