"""Completed frozen stages remain evidence, not relabelled v3 predictions."""

import base64
import hashlib
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files

ROOT = Path(__file__).resolve().parents[1]
OUTPUT = ROOT / "outputs/vnext"


def read(name):
    return json.loads((OUTPUT / name).read_text(encoding="utf-8"))


def test_completed_stages_preserve_full_seals_sources_and_audits():
    for prefix, count in (("goal_plan_v2", 22), ("tool_t2_v1", 18)):
        freeze, rows = read(prefix + "_freeze.json"), read(prefix + "_predictions.json")
        assert len(rows) == len(freeze["case_ids"]) == count
        assert read(prefix + "_prediction_seal.json") == prediction_seal(rows, freeze["case_ids"],
            architecture_commit=freeze["architecture_commit"], configuration_sha256=digest(freeze))
        assert not verify_files(ROOT, freeze["source_sha256"])
        report, audit = read(prefix + "_results.json"), read(prefix + "_failure_audit.json")
        assert audit["source_report_sha256"] == file_digest(OUTPUT / (prefix + "_results.json"))
        assert audit["cases"] == report["failure_taxonomy"]


def test_goal_v2_archive_and_unknown_schema_outcomes():
    freeze, archive = read("goal_plan_v2_freeze.json"), read("goal_plan_v2_source_archive.json")
    assert len(archive["sources"]) == 113
    assert set(archive["sources"]) == set(freeze["source_sha256"])
    for path, expected in freeze["source_sha256"].items():
        assert hashlib.sha256(base64.b64decode(archive["sources"][path]["bytes_base64"], validate=True)).hexdigest() == expected
    result = read("goal_plan_v2_results.json")
    assert result["goal_layer"]["counts"] == {"UNRESOLVED": 22}
    assert result["provider"]["attempts"] == result["provider"]["transport_success"] == 190
    assert result["provider"]["schema_valid"] == 176
    for kind in ("PROVED_ERROR", "PROVED_NO_ERROR"):
        assert result["goal_layer"]["certificate_validation"][kind]["rate"] is None
    audit = read("goal_plan_v2_detailed_audit.json")
    assert audit["case_count"] == 22
    assert audit["parser_changed_declared_goal_values"] == 0
    assert audit["raw_declared_goal_nulls"] == 19
    assert audit["schema_invalid_by_task"]["goal_v2_extra_constraints"] == 11


def test_t2_candidate_quality_is_separate_from_trust_boundary():
    report = read("tool_t2_v1_results.json")
    assert report["provider"]["attempts"] == report["provider"]["schema_valid"] == 18
    assert report["known_true_candidate_recall"]["rate"] == 0.25
    assert report["unsafe_trusted_effects"] == {"count": 0, "candidates": 19, "rate": 0.0}
    assert report["ledger_pollution_cases"] == report["false_state_action_causal_support"] == 0
