"""An unavailable audit sink must be visible while retaining the verdict."""
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "service"))
from runtime import GuardianServiceRuntime


def test_audit_sink_failure_is_reported_without_erasing_verdict(tmp_path):
    blocker = tmp_path / "regular-file"
    blocker.write_text("not a directory")
    rt = GuardianServiceRuntime("structural-v02", audit_path=blocker / "audit.jsonl")
    result = rt._finish("audit-check", "ERROR", "structural", [], [],
                        {"structural": "confirmed"}, False, "trace", {}, time.time())
    assert result["decision"] == "ERROR"
    assert result["audit_status"] == "WRITE_FAILED"
    assert result["degraded"] is True
    assert result["coverage"]["audit"] == "WRITE_FAILED"


def test_over_budget_request_keeps_full_coverage_in_audit(tmp_path):
    import json
    path = tmp_path / "audit.jsonl"
    rt = GuardianServiceRuntime("structural-v02", audit_path=path)
    result = rt.check({"case_id": "large", "prompt": "x" * 200001, "response": "OK"})
    assert result["decision"] == "UNKNOWN"
    assert result["audit_status"] == "WRITTEN"
    record = json.loads(path.read_text(encoding="utf-8"))
    assert record["coverage"]["reason"] == "context_budget_exceeded"
    assert record["trace_id"] == result["trace_id"]
