"""Write Policy-stage machine summary only after complete postseal integrity audit."""

import json
from pathlib import Path

from audit_vnext_policy_artifacts_v1 import audit
from guardian_truth.vnext.integrity import file_digest, write_new
from guardian_truth.vnext.policy_stage_summary_v1 import summarize_audited_policy_programs


ROOT = Path(__file__).resolve().parents[1]


def main():
    out = ROOT / "outputs/vnext"
    report_path = out / "policy_programs_v1_results.json"
    audit_path = out / "policy_programs_v1_artifact_audit.json"
    summary_path = out / "policy_phi_results.json"
    result = audit(ROOT)
    if result["status"] != "INTEGRITY_VALID":
        raise ValueError("Policy artifact audit not valid: " + json.dumps(result, ensure_ascii=False))
    report = json.loads(report_path.read_text(encoding="utf-8"))
    # The audit is an independently reproducible post-run receipt. An existing
    # copy must match; neither it nor the summary may be silently overwritten.
    if audit_path.exists():
        existing = json.loads(audit_path.read_text(encoding="utf-8"))
        if existing != result:
            raise ValueError("persisted Policy audit differs from current replay")
    else:
        write_new(audit_path, result)
    summary = summarize_audited_policy_programs(report, result,
        report_sha256=file_digest(report_path), audit_sha256=file_digest(audit_path))
    if summary_path.exists():
        if json.loads(summary_path.read_text(encoding="utf-8")) != summary:
            raise ValueError("existing Policy summary differs from audited report")
    else:
        write_new(summary_path, summary)
    print(json.dumps({"status": summary["status"], "cases": summary["case_count"],
        "artifact_integrity": summary["artifact_integrity"]}, ensure_ascii=False))


if __name__ == "__main__":
    main()
