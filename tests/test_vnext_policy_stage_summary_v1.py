"""No incomplete Policy run can acquire an apparently complete milestone."""

import pytest

from guardian_truth.vnext.policy_stage_summary_v1 import summarize_audited_policy_programs


def sample():
    report = {"experiment": "policy_programs_v1", "case_count": 104,
        "scope": "OBSERVED_DEV_POLICY_PROGRAM_MEANING_STAGE_ONLY", "blind_cases_read": 0,
        "whole_core_gain": "NOT_ESTABLISHED_POLICY_MEANING_STAGE_ONLY",
        "semantic_coverage": {"OPEN_SEMANTICS": 104},
        "candidate_behavior": {"correct": 5}, "fixed_p1_behavior": {"correct": 6},
        "paired": {"n": 104}, "full_interpretation_recall": "NOT_ESTABLISHED",
        "unsupported_interpretation_rate": "NOT_ESTABLISHED", "provider": {"combined": {"cost": "NOT_AUDITED"}}}
    audit = {"status": "INTEGRITY_VALID", "errors": [], "report_sha256": "a" * 64,
        "case_count": 104, "failure_components": {"POLICY_GENERATION": 3}}
    return report, audit


def test_valid_postseal_stage_summary_preserves_scope_and_unproved_metrics():
    report, audit = sample()
    summary = summarize_audited_policy_programs(report, audit,
        report_sha256="a" * 64, audit_sha256="b" * 64)
    assert summary["status"] == "COMPLETED_OBSERVED_DEV_REGRESSION"
    assert summary["whole_core_gain"] == "NOT_ESTABLISHED_POLICY_MEANING_STAGE_ONLY"
    assert summary["semantic_coverage"] == {"OPEN_SEMANTICS": 104}
    assert summary["source_artifact_audit_sha256"] == "b" * 64


@pytest.mark.parametrize("mutate", [
    lambda report, audit: audit.update(status="NOT_RUN_OR_INCOMPLETE"),
    lambda report, audit: audit.update(report_sha256="c" * 64),
    lambda report, audit: report.update(case_count=103),
    lambda report, audit: report.update(blind_cases_read=1),
    lambda report, audit: report.update(whole_core_gain="PROVED"),
    lambda report, audit: report.update(semantic_coverage={"PROVABLY_CLOSED": 104}),
])
def test_invalid_or_overclaimed_stage_cannot_be_summarized(mutate):
    report, audit = sample()
    mutate(report, audit)
    with pytest.raises(ValueError):
        summarize_audited_policy_programs(report, audit,
            report_sha256="a" * 64, audit_sha256="b" * 64)
