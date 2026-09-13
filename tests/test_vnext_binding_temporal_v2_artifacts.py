"""Completed typed-stage integrity; deliberately no claims about native Core."""

import hashlib
import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_completed_34_case_predictions_are_sealed_with_exact_source_inputs():
    frozen = read("binding_temporal_v2_freeze.json")
    rows = read("binding_temporal_v2_predictions.json")
    report = read("binding_temporal_v2_results.json")
    seal = prediction_seal(rows, frozen["case_ids"], architecture_commit=frozen["architecture_commit"],
        configuration_sha256=frozen["configuration_sha256"])
    assert seal == read("binding_temporal_v2_prediction_seal.json") == report["seal"]
    assert verify_files(ROOT, frozen["source_sha256"]) == []
    assert report["predictions_sha256"] == file_digest(OUT / "binding_temporal_v2_predictions.json")
    assert [{"case_id": row["case_id"], "input_sha256": row["input_sha256"]} for row in rows] == read("binding_temporal_v2_spec_freeze.json")["candidate_input_hashes"]
    assert report["metrics"]["case_count"] == 34 and report["metrics"]["truth_correct"] == 34
    assert report["metrics"]["truth_distribution"] == {"TRUE": 14, "FALSE": 8, "UNKNOWN": 12}
    assert report["metrics"]["whole_core_resolution"] == "NOT_RUN" and report["metrics"]["core_certificate_validation"] is None


def test_archived_130_executable_source_bytes_reproduce_every_frozen_hash():
    archive = read("binding_temporal_v2_source_archive.json")
    frozen = read("binding_temporal_v2_freeze.json")
    assert len(archive["files"]) == 130
    assert archive["source_sha256"] == frozen["source_sha256"]
    for relative, contents in archive["files"].items():
        assert hashlib.sha256(contents.encode("utf-8")).hexdigest() == frozen["source_sha256"][relative]
        assert relative.endswith(".py") and not any(part in relative for part in (".env", "NVIDIA_API", "model/vnext_blind_gold"))


def test_all_scored_cases_have_full_audit_with_expected_unknown_not_false_failure():
    report = read("binding_temporal_v2_results.json")
    audit = read("binding_temporal_v2_failure_audit.json")
    assert audit["report_sha256"] == file_digest(OUT / "binding_temporal_v2_results.json")
    assert [case["case_id"] for case in audit["cases"]] == [case["case_id"] for case in report["cases"]]
    assert audit["expected_unknown_preserved"] == 12 and audit["semantic_failures"] == 0
    assert len(audit["performance_source_analysis"]["full_alias_observation_scan_comprehension_lines"]) == 2
    assert all(case["core_certificate"] == "NOT_GENERATED" for case in audit["cases"])
