"""Post-seal deterministic component audit. No inference, correction or rescore."""

from collections import Counter
import json
from pathlib import Path
import runpy

from guardian_truth.vnext.goal_v3_user_contract_v2 import parse_user_contract_v2
from guardian_truth.vnext.integrity import file_digest, write_new

ROOT = Path(__file__).resolve().parents[1]


def audit():
    evaluator = runpy.run_path(str(ROOT / "scripts/evaluate_goal_v3_isolation_v3.py"))
    # Replays the exact sealed scorer; never rewrites candidates or gold.
    result = evaluator["score"]("S1")
    frozen = evaluator["verify"]()
    predictions, _ = evaluator["sealed_stage"]("S1", frozen)
    sources = {row["case_id"]: row["source"] for row in evaluator["read"]("inputs")}
    fields = ("status_correct", "alignment_correct", "obligation_correct", "temporal_correct",
        "effect_correct", "violation_correct", "unknown_correct", "entity_correct",
        "target_actor_correct", "actor_correct", "reference_correct", "world_consistency_correct")
    per_case = []
    for scored, prediction in zip(result["case_scores"], predictions):
        if scored["case_id"] != prediction["case_id"]:
            raise ValueError("case order differs")
        contract = parse_user_contract_v2(sources[scored["case_id"]])
        clauses = {clause.rule_id: clause.kind for clause in contract.clauses} if contract else {}
        classified = []
        for world_index, world in enumerate((prediction.get("proposal") or {}).get("worlds", [])):
            for rule in world["obligations"]:
                rid = rule["rule_id"]
                if rid.isdigit():
                    rid = "user:0:clause:" + rid
                classified.append({"world_index": world_index, "rule_id": rid,
                    "source_clause_kind": clauses.get(rid, "NO_MATCHING_EXPLICIT_CLAUSE"),
                    "proposed_obligation_kind": rule["kind"]})
        per_case.append({"case_id": scored["case_id"], "expected_status": scored["expected_status"],
            "candidate_status": scored["candidate_status"],
            "failed_components": [name for name in fields if scored[name] is False],
            "unsafe_definitive": scored["unsafe_definitive"],
            "certified_definitive": scored["certified_definitive"],
            "obligation_source_classification": classified})
    return {"schema_version": "guardian-goal-v3-v3-postseal-component-audit-v1",
        "model_calls": 0, "repairs": 0, "gold_or_prediction_changes": 0,
        "inference_freeze_sha256": result["inference_freeze_sha256"],
        "prediction_seal_sha256": result["prediction_seal_sha256"],
        "failed_component_counts": dict(Counter(name for row in per_case for name in row["failed_components"])),
        "case_audit": per_case}


if __name__ == "__main__":
    receipt = audit()
    write_new(ROOT / "outputs/vnext/goal_v3_isolation_v3_S1_component_audit.json", receipt)
    print(json.dumps({key: value for key, value in receipt.items() if key != "case_audit"}))
