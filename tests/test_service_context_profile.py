"""Deployment must reject inputs before the judge loses source text."""
import json
from pathlib import Path
import sys

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO / "service"))
from runtime import GuardianServiceRuntime


def test_long_input_stops_before_model_or_replay(tmp_path, monkeypatch):
    import runtime
    def fail(*args, **kwargs):
        raise AssertionError("model should never be called on oversized input")
    monkeypatch.setattr(runtime, "_judge_stage", fail)
    result = GuardianServiceRuntime("r0-service-v1", audit_path=tmp_path / "audit.jsonl").check(
        {"case_id": "long", "prompt": "x" * 12001, "response": "OK"})
    assert result["decision"] == "UNKNOWN" and result["degraded"]
    assert result["usage"]["calls"] == 0
    assert result["audit_status"] == "WRITTEN"


def test_frozen_inputs_fit_the_deployment_budget():
    data = REPO / "experiments/searh_23/hybrid_service_v1/dataset/fresh_v1"
    for split in ("dev", "sealed"):
        for r in map(json.loads, (data / (split + "_input.jsonl")).read_text(encoding="utf-8").splitlines()):
            assert len(r["prompt"]) + len(r["response"]) <= 12000
