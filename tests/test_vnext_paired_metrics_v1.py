"""Post-seal statistics unit tests; synthetic labels only, never blind data."""

from dataclasses import replace

import pytest

from guardian_truth.vnext.paired_metrics_v1 import PairedOutcome, confusion, exact_mcnemar, hierarchical_bootstrap, summarize_paired_outcomes


def row(cid, gold, x0, candidate, *, status="UNRESOLVED", group=None, category="a", coverage="OPEN_SEMANTICS",
        certificate=False, valid=None, reasons=("EVIDENCE_INCOMPLETE",)):
    return PairedOutcome(cid, group or cid, category, gold, x0, candidate, status,
        status in {"UNRESOLVED", "INCONSISTENT"}, certificate, valid, coverage, reasons)


def test_confusion_and_unresolved_rate_are_reported_together():
    rows = (row("p1", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=True),
        row("p2", 1, 1, 0), row("n1", 0, 1, 0),
        row("n2", 0, 0, 1, status="PROVED_ERROR", certificate=True, valid=True))
    report = summarize_paired_outcomes(rows, draws=50)
    assert report["vnext"]["TP"] == report["vnext"]["FP"] == report["vnext"]["FN"] == report["vnext"]["TN"] == 1
    assert report["vnext"]["F1"] == .5 and report["vnext"]["balanced_error"] == .5
    assert report["core_resolution_rate"] == .5 and report["fallback_count"] == 2
    assert report["claimed_core_resolution_rate"] == .5
    assert report["uncertified_definitive_case_ids"] == []
    assert report["confident_wrong_case_ids"] == ["n2"]
    assert report["certificate_validation_by_verdict"]["PROVED_ERROR"] == {"definite": 2, "present": 2, "valid": 2,
        "validation_rate_all_definite": 1, "validation_rate_present": 1}
    assert report["certificate_validation_by_verdict"]["PROVED_NO_ERROR"]["validation_rate_all_definite"] is None
    assert report["unresolved_reason_distribution"] == {"EVIDENCE_INCOMPLETE": 2}


def test_missing_negative_class_never_yields_fake_fpr_or_balanced_error():
    rows = (row("a", 1, 0, 0), row("b", 1, 0, 0))
    measured = confusion(rows, "vnext_binary")
    assert measured["false_positive_rate"] is None and measured["balanced_error"] is None
    assert measured["F1"] == 0
    boot = hierarchical_bootstrap(rows, draws=30, seed=260913)
    assert boot["delta_intervals"]["false_positive_rate"] == {"defined_draws": 0, "total_draws": 30, "CI95": None}


def test_exact_mcnemar_uses_paired_discordance_not_independent_counts():
    rows = tuple(row(f"p{i}", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=True)
        for i in range(5))
    result = exact_mcnemar(rows)
    assert result == {"x0_only_correct": 0, "vnext_only_correct": 5, "discordant": 5, "two_sided_exact_p": .0625}
    tied = (row("a", 1, 1, 0), row("b", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=True))
    assert exact_mcnemar(tied)["two_sided_exact_p"] == 1


def test_hierarchical_bootstrap_is_reproducible_and_does_not_drop_degenerate_draws():
    rows = (row("a1", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=True, group="A"),
        row("a2", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=True, group="A"),
        row("b1", 0, 0, 0, group="B"))
    first = hierarchical_bootstrap(rows, draws=100, seed=7)
    assert first == hierarchical_bootstrap(rows, draws=100, seed=7)
    assert first["trajectory_groups"] == 2
    assert first["delta_intervals"]["recall"]["defined_draws"] < 100
    assert first["delta_intervals"]["recall"]["CI95"] is None


@pytest.mark.parametrize("bad", [
    {"vnext_binary": 1}, {"used_fallback": False}, {"certificate_present": True},
    {"certificate_valid": False}, {"gold": True}, {"coverage": "PROVABLY_CLOSED_FROM_SCHEMA"},
])
def test_invalid_binary_status_or_certificate_fields_are_rejected(bad):
    source = row("a", 0, 0, 0)
    with pytest.raises(ValueError):
        replace(source, **bad)


def test_duplicate_case_ids_and_missing_rows_are_rejected():
    source = row("a", 0, 0, 0)
    with pytest.raises(ValueError):
        summarize_paired_outcomes((source, source), draws=1)
    with pytest.raises(ValueError):
        summarize_paired_outcomes((), draws=1)


def test_undefined_baseline_metric_does_not_create_numeric_delta():
    rows = (row("a", 0, 0, 0), row("b", 0, 0, 0))
    report = summarize_paired_outcomes(rows, draws=20)
    assert report["delta"]["recall"] is None
    assert report["delta"]["F1"] is None
    assert report["paired_bootstrap"]["delta_intervals"]["F1"]["CI95"] is None


def test_uncertified_claimed_verdict_cannot_inflate_genuine_core_resolution():
    rows = (row("bad", 1, 0, 1, status="PROVED_ERROR", certificate=True, valid=False),
        row("unknown", 0, 0, 0))
    report = summarize_paired_outcomes(rows, draws=10)
    assert report["claimed_definitive_count"] == 1
    assert report["certified_definitive_count"] == 0
    assert report["claimed_core_resolution_rate"] == .5
    assert report["core_resolution_rate"] == 0
    assert report["uncertified_definitive_case_ids"] == ["bad"]
    assert report["certificate_validation_by_verdict"]["PROVED_ERROR"]["validation_rate_all_definite"] == 0
