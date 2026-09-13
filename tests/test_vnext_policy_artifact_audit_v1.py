"""Read-only Policy artifact chain tests; no new model/gold access."""

import importlib.util
import json
from pathlib import Path

import pytest

from guardian_truth.vnext.integrity import digest

ROOT = Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location("policy_artifact_auditor", ROOT / "scripts/audit_vnext_policy_artifacts_v1.py")
AUDITOR = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(AUDITOR)


def test_incomplete_report_is_not_misrepresented_as_terminal(tmp_path):
    assert AUDITOR.audit(tmp_path)["status"] == "NOT_RUN_OR_INCOMPLETE"
    assert "policy_programs_v1_results.json" in AUDITOR.audit(tmp_path)["missing"]


def test_saved_request_link_rejects_changed_telemetry_or_prompt(tmp_path):
    stem = "policy_programs_v1_case_000_native"
    request = {"configuration_sha256": "a" * 64, "ordinal": 0, "prompt_sha256": "b" * 64,
        "schema_sha256": "c" * 64}
    telemetry = {"prompt_sha256": "b" * 64, "schema_sha256": "c" * 64,
        "transport_status": "SUCCESS", "schema_status": "VALID", "usage": {}, "latency_ms": 10}
    result = {"request_sha256": digest(request), "telemetry": telemetry}
    (tmp_path / (stem + "_request_000.json")).write_text(json.dumps(request), encoding="utf-8")
    (tmp_path / (stem + "_request_000_result.json")).write_text(json.dumps(result), encoding="utf-8")
    assert AUDITOR.verify_request_link(tmp_path, stem, 0, telemetry, "a" * 64) == result
    with pytest.raises(ValueError, match="linkage"):
        AUDITOR.verify_request_link(tmp_path, stem, 0, {**telemetry, "latency_ms": 9}, "a" * 64)
    with pytest.raises(ValueError, match="linkage"):
        AUDITOR.verify_request_link(tmp_path, stem, 0, telemetry, "d" * 64)


def test_current_frozen_policy_is_not_claimed_complete_before_full_report():
    # This test remains valid after the run: then the auditor must have an
    # integrity verdict, but never a synthetic semantic-correctness verdict.
    result = AUDITOR.audit(ROOT)
    assert result["status"] in {"NOT_RUN_OR_INCOMPLETE", "INTEGRITY_VALID"}
    assert result["scope"].endswith("NOT_NL_CORRECTNESS_OR_CORE_GAIN")
