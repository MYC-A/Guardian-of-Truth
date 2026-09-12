import json
from pathlib import Path

from guardian_truth.vnext.integrity import digest, file_digest, verify_files


ROOT = Path(__file__).resolve().parents[1]


def test_frozen_t1_evaluation_artifacts_are_consistent():
    output = ROOT / "outputs/vnext"
    freeze = json.loads((output / "tool_t1_freeze_v1.json").read_text(encoding="utf-8"))
    report = json.loads((output / "tool_t1_results_v1.json").read_text(encoding="utf-8"))
    predictions = json.loads((output / "tool_t1_predictions_v1.json").read_text(encoding="utf-8"))
    assert verify_files(ROOT, freeze["source_sha256"]) == []
    assert report["freeze_sha256"] == file_digest(output / "tool_t1_freeze_v1.json")
    assert report["predictions_file_sha256"] == file_digest(output / "tool_t1_predictions_v1.json")
    assert predictions["prediction_sha256"] == digest(predictions["rows"])
    assert report["T1"]["evaluated"] == report["T1"]["correct"] == 16
    assert report["T1"]["not_applicable_missing_contract"] == 2
    assert report["T1"]["false_no_effect"] == report["T1"]["false_causal_action_confirmation"] == 0
    assert report["T2"]["status"] == "NOT_RUN"
    assert len(report["per_case"]) == len(predictions["rows"]) == 18
