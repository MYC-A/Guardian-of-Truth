"""Audited Policy-program stage -> honest machine-readable milestone summary."""

from .integrity import digest


def summarize_audited_policy_programs(report, audit, *, report_sha256, audit_sha256):
    """Summarize the completed observed-dev stage, never manufacture Core gain."""
    if audit.get("status") != "INTEGRITY_VALID" or audit.get("errors"):
        raise ValueError("Policy stage cannot be summarized before a valid artifact audit")
    if audit.get("report_sha256") != report_sha256 or report.get("experiment") != "policy_programs_v1":
        raise ValueError("Policy report and audit do not link to the same experiment")
    if report.get("case_count") != 104 or audit.get("case_count") != 104:
        raise ValueError("frozen 104-case regression inventory is incomplete")
    if report.get("scope") != "OBSERVED_DEV_POLICY_PROGRAM_MEANING_STAGE_ONLY":
        raise ValueError("unexpected Policy result scope")
    if report.get("blind_cases_read") != 0:
        raise ValueError("observed-dev Policy stage must not contain blind gold")
    if report.get("whole_core_gain") != "NOT_ESTABLISHED_POLICY_MEANING_STAGE_ONLY":
        raise ValueError("meaning-stage result cannot claim whole-Core gain")
    coverage = report["semantic_coverage"]
    if sum(coverage.values()) != 104:
        raise ValueError("semantic coverage inventory does not cover all cases")
    if coverage.get("PROVABLY_CLOSED", 0):
        raise ValueError("no authoritative closed policy universe was supplied")
    return {
        "schema_version": "guardian-vnext-policy-stage-summary-v1",
        "status": "COMPLETED_OBSERVED_DEV_REGRESSION",
        "scope": "POLICY_MEANING_LAYER_ONLY_NOT_CERTIFIED_CORE_OR_BLIND_GAIN",
        "source_report_sha256": report_sha256,
        "source_artifact_audit_sha256": audit_sha256,
        "case_count": 104,
        "candidate_behavior": report["candidate_behavior"],
        "fixed_p1_behavior": report["fixed_p1_behavior"],
        "paired": report["paired"],
        "semantic_coverage": coverage,
        "full_interpretation_recall": report["full_interpretation_recall"],
        "unsupported_interpretation_rate": report["unsupported_interpretation_rate"],
        "whole_core_gain": report["whole_core_gain"],
        "provider": report["provider"],
        "failure_component_counts": audit["failure_components"],
        "artifact_integrity": audit["status"],
        "blind_cases_read": 0,
        "limitations": [
            "observed Policy Semantics V2 regression, not new blind evidence",
            "finite atom catalog and challenger silence do not close natural-language policy meaning",
            "candidate behavioral correctness is not interpretation reasonableness adjudication",
            "no Goal v3, factual integration or certified whole-Core verdict in this stage",
            "provider cost not asserted without audited billing basis",
        ],
        "summary_content_sha256": digest({"report_sha256": report_sha256, "audit_sha256": audit_sha256}),
    }
