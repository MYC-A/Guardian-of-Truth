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
