import json
import base64
import hashlib
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, prediction_seal, verify_files


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_goal_stage_has_full_pre_gold_seal_and_unmodified_sources():
    output = ROOT / "outputs/vnext"
    freeze = json.loads((output / "goal_plan_v1_freeze.json").read_text(encoding="utf-8"))
    rows = json.loads((output / "goal_plan_v1_predictions.json").read_text(encoding="utf-8"))
    seal = json.loads((output / "goal_plan_v1_prediction_seal.json").read_text(encoding="utf-8"))
    assert len(rows) == len(freeze["case_ids"]) == 22
    assert seal == prediction_seal(rows, freeze["case_ids"], architecture_commit=freeze["architecture_commit"],
        configuration_sha256=digest(freeze))
    archive = json.loads((output / "goal_plan_v1_source_archive.json").read_text(encoding="utf-8"))
    assert archive["freeze_sha256"] == file_digest(output / "goal_plan_v1_freeze.json")
    assert archive["architecture_commit"] == freeze["architecture_commit"]
    assert set(archive["sources"]) == set(freeze["source_sha256"])
    for path, expected in freeze["source_sha256"].items():
        assert archive["sources"][path]["sha256"] == expected
        assert hashlib.sha256(base64.b64decode(archive["sources"][path]["bytes_base64"], validate=True)).hexdigest() == expected
    assert all(row["configuration_sha256"] == digest(freeze) for row in rows)


def test_frozen_goal_audit_metrics_do_not_claim_safety_or_full_schema_success():
    output = ROOT / "outputs/vnext"
    report_path = output / "goal_plan_v1_results.json"
    result = json.loads(report_path.read_text(encoding="utf-8"))
    audit = json.loads((output / "goal_plan_v1_failure_audit.json").read_text(encoding="utf-8"))
    assert audit["source_report_sha256"] == file_digest(report_path)
    assert len(audit["cases"]) == 22
    assert result["provider"]["attempts"] == result["provider"]["transport_success"] == 22
    assert result["provider"]["schema_valid"] == 15
    assert result["core"]["counts"] == {"UNRESOLVED": 22}
    assert result["core"]["unresolved_rate"] == 1
    assert result["core"]["certificate_validation"]["PROVED_ERROR"]["rate"] is None
    assert result["competition_binary"]["F1"] == result["baseline_x0_binary"]["F1"] == 0
    assert result["blind_cases_read"] == 0
