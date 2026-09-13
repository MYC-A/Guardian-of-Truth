"""Recheck sealed S1 and prove the frozen core pair-score upper bound offline.

This is a post-hoc audit, not a new preregistered stop rule or a rescore.
It never sends model requests and does not modify any v1 freeze or prediction.
"""

import json
import math
from pathlib import Path

from guardian_truth.vnext.goal_v3_isolation_scoring_v1 import summarize_goal_v3_stage
from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, write_new
from scripts.evaluate_goal_v3_isolation_v1 import path, read, verify_freeze


ROOT = Path(__file__).resolve().parents[1]
THRESHOLD = 0.90  # Frozen core gate in goal_v3_isolation_scoring_v1.py.


def audit():
    frozen, benchmark = verify_freeze()
    stage_ids = benchmark["stages"]["S1_smoke"]
    remaining_ids = benchmark["stages"]["S2_remaining_core"]
    stress_ids = benchmark["stages"]["S3_stress"]
    predictions = read("S1_smoke_predictions")
    seal = read("S1_smoke_prediction_seal")
    expected_seal = prediction_seal(predictions, stage_ids,
        architecture_commit=frozen["architecture_commit"],
        configuration_sha256=digest(frozen))
    if seal != expected_seal:
        raise ValueError("S1 predictions are not sealed")
    report = read("S1_smoke_results")
    if (report["prediction_seal_sha256"] != file_digest(path("S1_smoke_prediction_seal"))
            or report["inference_freeze_sha256"] != file_digest(path("inference_freeze"))
            or report["benchmark_freeze_sha256"] != file_digest(path("benchmark_freeze"))):
        raise ValueError("S1 report lineage changed")
    # Gold is opened only after both freeze and exact prediction-seal checks.
    summary = summarize_goal_v3_stage(read("inputs"), read("gold"), predictions,
        benchmark["case_inventory"], stage_ids)
    if summary != report["summary"]:
        raise ValueError("S1 reported metrics differ from deterministic replay")
    pair_members = {}
    for row in benchmark["case_inventory"]:
        if row["pair_id"] is not None:
            pair_members.setdefault(row["pair_id"], set()).add(row["case_id"])
    if len(pair_members) != 24 or any(len(members) != 2 for members in pair_members.values()):
        raise ValueError("frozen core does not contain exactly 24 minimal pairs")
    failed_observed_pairs = sorted({row["pair_id"] for row in summary["failure_taxonomy"]
        if row["pair_id"] is not None and not row["behavioral_correct"]})
    max_correct = len(pair_members) - len(failed_observed_pairs)
    required = math.ceil(THRESHOLD * len(pair_members))
    if (len(stage_ids) != 12 or len(remaining_ids) != 36 or len(stress_ids) != 12
            or set(stage_ids) & set(remaining_ids)
            or set(stage_ids) & set(stress_ids)
            or set(remaining_ids) & set(stress_ids)):
        raise ValueError("frozen stage inventory changed")
    if report["not_run_case_ids"] != [case_id for case_id in frozen["case_ids"]
            if case_id not in set(stage_ids)]:
        raise ValueError("S1 NOT_RUN inventory changed")
    result = {"schema_version": "guardian-goal-v3-isolation-s1-bound-audit-v1",
        "scope": "POST_HOC_DETERMINISTIC_AUDIT_NOT_PREREGISTERED_STOP_RULE",
        "inference_freeze_sha256": file_digest(path("inference_freeze")),
        "prediction_seal_sha256": file_digest(path("S1_smoke_prediction_seal")),
        "stage_result_sha256": file_digest(path("S1_smoke_results")),
        "auditor_source_sha256": file_digest(ROOT / "scripts/audit_goal_v3_isolation_s1_bound_v1.py"),
        "stage_admitted_s2_under_preregistered_rules": report["admission"]["admit_S2"],
        "s1_cases": len(stage_ids), "core_not_run": len(remaining_ids),
        "stress_not_run": len(stress_ids),
        "observed_failed_pair_ids": failed_observed_pairs,
        "optimistic_max_correct_pairs": max_correct,
        "total_core_pairs": len(pair_members),
        "optimistic_max_pair_correct_rate": max_correct / len(pair_members),
        "frozen_required_correct_pairs": required,
        "frozen_pair_gate_reachable": max_correct >= required,
        "reported_provider_usage": summary["provider"]["usage"],
        "formal_verdict": "NOT_ESTABLISHED_S2_NOT_RUN"}
    write_new(path("S1_bound_audit"), result)
    print(json.dumps({"max_pairs": max_correct, "required_pairs": required,
        "gate_reachable": result["frozen_pair_gate_reachable"]}))


if __name__ == "__main__":
    audit()
