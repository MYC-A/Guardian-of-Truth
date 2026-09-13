"""Preserve full scored-case audit and explicit scope/performance limitations."""

import ast
from collections import Counter
import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, verify_files, write_new

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def main():
    frozen = json.loads((OUT / "binding_temporal_v2_freeze.json").read_text(encoding="utf-8"))
    if verify_files(ROOT, frozen["source_sha256"]):
        raise ValueError("frozen candidate source changed")
    report_path = OUT / "binding_temporal_v2_results.json"
    report = json.loads(report_path.read_text(encoding="utf-8"))
    predictions = json.loads((OUT / "binding_temporal_v2_predictions.json").read_text(encoding="utf-8"))
    by_id = {row["case_id"]: row for row in predictions}
    audited = []
    for case in report["cases"]:
        row = by_id[case["case_id"]]
        audited.append({"case_id": case["case_id"], "family": case["family"], "kind": case["kind"],
            "truth_correct": case["truth_correct"], "binding_correct": case["binding_correct"],
            "completeness_correct": case["completeness_correct"], "failure_components": case["failure_components"],
            "expected_unknown": case["gold"]["truth"] == "UNKNOWN", "unknown_preserved": case["unknown_preserved"],
            "diagnostics_not_semantic_failure": case["unresolved_reasons"],
            "certificate_scope": row["certificate"]["scope"] if row["certificate"] else None,
            "typed_receipt_valid": row["certificate_valid"], "core_certificate": "NOT_GENERATED",
            "runtime_ms": row["runtime_ms"], "source_event_count": row["source_event_count"],
            "source_record_count": row["source_record_count"], "binding_count": len(row["evidence"]["bindings"]),
            "searched_event_count": len(row["evidence"]["searched_event_ids"])})
    candidate_path = ROOT / "src/guardian_truth/vnext/temporal_queries_v4.py"
    tree = ast.parse(candidate_path.read_text(encoding="utf-8"))
    full_record_scans = [node.lineno for node in ast.walk(tree) if isinstance(node, (ast.ListComp, ast.SetComp, ast.GeneratorExp))
        and any(ast.unparse(generator.iter) == "self.records.observations" for generator in node.generators)]
    audit = {"scope": "FULL_TYPED_STAGE_CASE_AUDIT_NOT_NATIVE_CORE_OR_BLIND",
        "report_sha256": file_digest(report_path), "freeze_sha256": file_digest(OUT / "binding_temporal_v2_freeze.json"),
        "case_count": len(audited), "semantic_failures": sum(bool(case["failure_components"]) for case in audited),
        "expected_unknown_preserved": sum(case["unknown_preserved"] for case in audited),
        "failure_taxonomy": dict(Counter(component for case in audited for component in case["failure_components"])),
        "source_grounding": "explicit independent executable fixture only; not arbitrary competition tool authority",
        "limitations": ["native claim/goal/policy integration and whole-Core certificates NOT_RUN",
            "controlled observed development, not non-overlapping blind evaluation",
            "one positive causal proof is insufficient evidence for broad causal precision",
            "name and alias-history branches still scan cached alias observations; ID/method queries use indexes",
            "long-source timings include normalization/index construction and independent full-source replay; not per-query lookup latency"],
        "performance_source_analysis": {"candidate_sha256": file_digest(candidate_path),
            "full_alias_observation_scan_comprehension_lines": sorted(full_record_scans),
            "status": "DOCUMENTED_BEFORE_ANY_NEW_VERSION_OPTIMIZATION"},
        "candidate_frozen_source_changed": False, "api_requests": 0, "blind_gold_opened": False, "cases": audited}
    write_new(OUT / "binding_temporal_v2_failure_audit.json", audit)
    print(json.dumps({"case_count": len(audited), "semantic_failures": audit["semantic_failures"],
        "expected_unknown_preserved": audit["expected_unknown_preserved"], "full_alias_scan_branches": len(full_record_scans), "api_requests": 0}))


if __name__ == "__main__":
    main()
