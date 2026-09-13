import json
from pathlib import Path

from guardian_truth.vnext.integrity import file_digest

ROOT = Path(__file__).resolve().parents[1]


def test_binding_input_audit_does_not_upgrade_symbolic_gold_to_source_evidence():
    path = ROOT / "outputs/vnext/binding_temporal_v1_source_audit.json"
    report = json.loads(path.read_text(encoding="utf-8"))
    assert report["benchmark_sha256"] == file_digest(ROOT / "benchmarks/vnext/binding_temporal_v1.json")
    assert report["case_count"] == report["source_grounding_not_established"] == 32
    assert report["distinct_symbolic_inputs"] == 16
    assert report["core_predictions"] == "NOT_RUN"
    assert report["metrics"] == "NOT_ESTABLISHED_NO_EXECUTABLE_BINDING_EVALUATION"
    assert report["api_requests"] == 0
    assert all(not case["structured_trace"] and not case["completeness_premise_supplied"] for case in report["cases"])
