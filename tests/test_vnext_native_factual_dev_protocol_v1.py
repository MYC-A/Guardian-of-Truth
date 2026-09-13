"""Protocol/source tests, not model predictions or Core quality measurements."""

import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]


def load(relative, name):
    spec = importlib.util.spec_from_file_location(name, ROOT / relative)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


RUNNER = load("scripts/evaluate_vnext_native_factual_v5_dev_v1.py", "native_dev_runner")
REFERENCE = load("benchmarks/vnext/binding_fixture_reference_v2.py", "native_dev_reference")


def test_source_backed_fixture_expectations_are_not_handwritten_model_gold():
    spec = json.loads(RUNNER.SPEC.read_text(encoding="utf-8"))
    assert len(spec["cases"]) == 12
    assert len({case["id"] for case in spec["cases"]}) == 12
    truths = [REFERENCE.reference_query(REFERENCE.execute_fixture(RUNNER.fixture_input(spec, case)))["truth"]
        for case in spec["cases"]]
    assert truths == ["TRUE", "TRUE", "FALSE", "TRUE", "UNKNOWN", "UNKNOWN", "FALSE", "TRUE", "FALSE", "TRUE", "TRUE", "FALSE"]


def test_model_source_projection_excludes_case_metadata_and_latent_reference_knowledge():
    spec = json.loads(RUNNER.SPEC.read_text(encoding="utf-8"))
    projected = RUNNER.source_input(spec, spec["cases"][5], REFERENCE)
    assert set(projected) == {"source", "response"}
    encoded = json.dumps(projected)
    assert "latent_apply" not in encoded and "timeout_late_read" not in encoded
    assert "reference_knowledge" not in encoded


def test_network_admission_rejects_incomplete_preceding_policy_stage(tmp_path, monkeypatch):
    monkeypatch.setattr(RUNNER, "OUT", tmp_path)
    with pytest.raises(ValueError, match="Policy frozen evaluation"):
        RUNNER.assert_policy_admission()


def test_abandoned_capture_is_not_counted_as_semantic_wrong_or_zero_latency():
    records = [{"remote_outcome": "UNKNOWN_NO_AUTOMATIC_RETRY", "transport_status": "ERROR",
        "schema_status": "NOT_EVALUATED", "latency_ms": 0, "usage": {}},
        {"transport_status": "SUCCESS", "schema_status": "VALID", "latency_ms": 500, "usage": {"total_tokens": 20}}]
    summary = RUNNER.provider_summary(records)
    assert summary["requests"] == 2 and summary["unknown_remote_capture"] == 1
    assert summary["latency_ms_p50"] == 500
    assert summary["schema_valid"] == 1 and "semantic_wrong" not in summary
