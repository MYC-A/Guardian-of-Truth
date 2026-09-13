"""Actual event-count scaling receipts, never native Core latency/accuracy."""

import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest, prediction_seal, verify_files

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "outputs/vnext"


def read(name):
    return json.loads((OUT / name).read_text(encoding="utf-8"))


def test_all_nine_scaling_predictions_are_sealed_and_sources_unchanged():
    frozen = read("binding_scaling_v1_freeze.json")
    rows = read("binding_scaling_v1_predictions.json")
    report = read("binding_scaling_v1_results.json")
    assert verify_files(ROOT, frozen["source_sha256"]) == []
    seal = prediction_seal(rows, frozen["case_ids"], architecture_commit=frozen["architecture_commit"], configuration_sha256=frozen["configuration_sha256"])
    assert seal == read("binding_scaling_v1_prediction_seal.json") == report["prediction_seal"]
    assert report["predictions_sha256"] == file_digest(OUT / "binding_scaling_v1_predictions.json")
    assert report["correct_full_rows"] == report["primitive_receipts_valid"] == report["case_count"] == 9
    assert report["api_requests"] == 0 and report["whole_core_evaluation"] == "NOT_RUN"


def test_10000_real_events_preserve_all_4998_method_calls_not_top_k():
    report = read("binding_scaling_v1_results.json")
    assert {case["event_count"] for case in report["cases"]} == {100, 1000, 10000}
    case = next(case for case in report["cases"] if case["case_id"] == "scale:10000:mutation-count")
    assert case["candidate_method_calls"] == case["expected_method_calls"] == 4998
    assert case["searched_event_count"] == 9996
    assert case["candidate_bindings"] == 1 and case["candidate_set_complete"] is True
    assert case["core_certificate"] == "NOT_GENERATED" and not case["failure_components"]
