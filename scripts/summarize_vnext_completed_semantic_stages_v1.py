"""Create required Claim/T1+T2 summary JSON from sealed completed DEV reports.

No model calls, label reads, new scoring, rewriting, or whole-Core promotion.
"""

import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, write_new

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def read(path):
    return json.loads(path.read_text(encoding="utf-8"))


def source(root, name):
    path = root / "outputs/vnext" / name
    return path, read(path)


def linked_report(root, stem, *, prediction_name, audit_name):
    report_path, report = source(root, stem + "_results.json")
    freeze_path, _ = source(root, stem + "_freeze.json")
    prediction_path, _ = source(root, prediction_name)
    audit_path, audit = source(root, audit_name)
    if report["freeze_sha256"] != file_digest(freeze_path):
        raise ValueError(stem + " frozen source/report mismatch")
    recorded = report.get("predictions_sha256", report.get("predictions_file_sha256"))
    if recorded != file_digest(prediction_path):
        raise ValueError(stem + " prediction/report mismatch")
    if audit["source_report_sha256"] != file_digest(report_path):
        raise ValueError(stem + " per-case audit/report mismatch")
    return report_path, report, audit_path, audit


def claim_summary(root=ROOT):
    root = Path(root).resolve()
    path, report, audit_path, audit = linked_report(root, "claim_graph_v1",
        prediction_name="claim_graph_v1_predictions.json", audit_name="claim_graph_v1_failure_audit.json")
    seal_path, seal = source(root, "claim_graph_v1_prediction_seal.json")
    detail_path, detail = source(root, "claim_graph_v1_detailed_audit.json")
    if (report["prediction_seal_sha256"] != file_digest(seal_path) or seal["count"] != 41
            or detail["source_report_sha256"] != file_digest(path)
            or detail["prediction_seal_sha256"] != file_digest(seal_path)
            or len(audit["cases"]) != report["case_count"] or len(detail["cases"]) != report["case_count"]):
        raise ValueError("claim sealed inventory/audit mismatch")
    return {"schema_version": "guardian-vnext-claim-stage-summary-v1", "status": "COMPLETED_CONTROLLED_DEV_NOT_PROMOTED",
        "scope": "VERSIONED_CLAIM_STAGE_ONLY_NOT_CONTEXTUAL_FACTUAL_OR_CORE_GAIN",
        "source_report_sha256": file_digest(path), "source_failure_audit_sha256": file_digest(audit_path),
        "source_detailed_audit_sha256": file_digest(detail_path), "source_prediction_seal_sha256": file_digest(seal_path),
        "case_count": report["case_count"], "span_detection": report["span_detection"],
        "disposition_coverage": report["disposition_coverage"], "unknown_typed_nodes": report["unknown_typed_nodes"],
        "field_metrics": report["field_metrics"], "paired_shared_field_gain": report["paired_shared_field_gain"],
        "admission": report["admission"], "unsupported_claim_recall": report["unsupported_claim_recall"],
        "provider": report["provider"], "downstream_core_gain": "NOT_RUN", "blind_cases_read": 0}


def tool_summary(root=ROOT):
    root = Path(root).resolve()
    # T1 v1 was frozen before the generic per-case audit naming convention.
    t1path, t1 = source(root, "tool_t1_results_v1.json")
    t1freeze, _ = source(root, "tool_t1_freeze_v1.json")
    t1pred, _ = source(root, "tool_t1_predictions_v1.json")
    if (t1["freeze_sha256"] != file_digest(t1freeze) or t1["predictions_file_sha256"] != file_digest(t1pred)
            or len(t1["per_case"]) != t1["T1"]["total_cases"] or not t1["proposals_persisted_before_gold_join"]):
        raise ValueError("T1 frozen report/prediction/per-case mismatch")
    t2path, t2, t2audit_path, t2audit = linked_report(root, "tool_t2_v1",
        prediction_name="tool_t2_v1_predictions.json", audit_name="tool_t2_v1_failure_audit.json")
    t2seal, seal = source(root, "tool_t2_v1_prediction_seal.json")
    if (t2["prediction_seal_sha256"] != file_digest(t2seal) or seal["count"] != t2["case_count"]
            or t2audit["cases"] != t2["failure_taxonomy"]):
        raise ValueError("T2 sealed inventory/audit mismatch")
    return {"schema_version": "guardian-vnext-tool-stage-summary-v1", "status": "T1_COMPLETE_T2_COMPLETE_CONTROLLED_DEV",
        "scope": "EXPLICIT_EXECUTABLE_FIXTURES_NOT_REAL_PROVIDER_GENERALIZATION_OR_CORE_GAIN",
        "T1": {"source_report_sha256": file_digest(t1path), "case_count": t1["T1"]["total_cases"],
            "evaluated": t1["T1"]["evaluated"], "correct": t1["T1"]["correct"],
            "not_applicable_missing_contract": t1["T1"]["not_applicable_missing_contract"],
            "false_no_effect": t1["T1"]["false_no_effect"],
            "false_causal_action_confirmation": t1["T1"]["false_causal_action_confirmation"],
            "api_requests": t1["api_requests"]},
        "T2": {"source_report_sha256": file_digest(t2path), "source_failure_audit_sha256": file_digest(t2audit_path),
            "case_count": t2["case_count"], "provider": t2["provider"],
            "known_true_candidate_recall": t2["known_true_candidate_recall"],
            "known_true_candidate_reference_precision": t2["known_true_candidate_reference_precision"],
            "full_candidate_precision": t2["full_candidate_precision"],
            "unsafe_trusted_effects": t2["unsafe_trusted_effects"],
            "ledger_pollution_cases": t2["ledger_pollution_cases"],
            "false_state_action_causal_support": t2["false_state_action_causal_support"],
            "effect_status_distribution": t2["effect_status_distribution"],
            "grounding_rejections": t2["grounding_rejections"],
            "downstream_gain": t2["downstream_gain"]},
        "joint_downstream_core_gain": "NOT_RUN", "blind_cases_read": 0}


def main():
    for name, value in (("claim_graph_results.json", claim_summary()),
            ("tool_semantics_results.json", tool_summary())):
        write_new(OUT / name, value)
        print(json.dumps({"created": name, "status": value["status"]}))


if __name__ == "__main__":
    main()
