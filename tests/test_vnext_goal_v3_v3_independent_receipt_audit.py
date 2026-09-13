"""Gold-free audit tests, added after inference freeze; not scorer changes."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from guardian_truth.llm_client import ChatClientError
from guardian_truth.vnext.goal_v3_isolation_frontend_v3 import PROMPT_SHA256, SCHEMA_SHA256, VERSION
from guardian_truth.vnext.goal_v3_isolation_runner_v3 import CONFIG, StageRunnerV3
from guardian_truth.vnext.integrity import file_digest, write_new
from test_vnext_goal_v3_isolation_runner_v2 import FakeClient, completion
from test_vnext_goal_v3_user_execution_v2 import source


AUDIT = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/audit_goal_v3_isolation_v3_receipts.py"))["audit_receipts_v3"]


def fixture(tmp_path, outcomes=None):
    frozen = {"architecture_commit": "a" * 40, "configuration": deepcopy(CONFIG),
        "stages": {"S1": ["p1:a", "p2:a"]}, "source_sha256": {},
        "frontend_version": VERSION, "prompt_sha256": PROMPT_SHA256, "schema_sha256": SCHEMA_SHA256}
    inputs = {cid: source() for cid in frozen["stages"]["S1"]}
    path = tmp_path / "goal_v3_isolation_v3_inputs.json"
    write_new(path, [{"case_id": cid, "source": value} for cid, value in inputs.items()])
    frozen["inputs_sha256"] = file_digest(path)
    write_new(tmp_path / "goal_v3_isolation_v3_inference_freeze.json", frozen)
    run = StageRunnerV3(tmp_path, frozen, FakeClient(outcomes or [completion(), completion()]), sleeper=lambda _: None)
    run.run("S1", inputs)
    return run


def test_sealed_physical_audit_needs_no_gold_file_and_calls_no_model(tmp_path):
    run = fixture(tmp_path)
    audit = AUDIT(tmp_path, tmp_path, "S1")
    assert not audit["gold_opened"] and audit["model_calls"] == 0
    assert audit["sealed_cases"] == audit["physical_requests"] == audit["successful_deliveries"] == 2
    assert audit["reported_usage"]["total_tokens"] == 300
    assert len(audit["physical_artifact_sha256"]) == 4


def test_valid_transport_retry_and_unknown_usage_are_reported_not_guessed(tmp_path):
    fixture(tmp_path, [ChatClientError("timeout", retryable=True), completion(), completion()])
    audit = AUDIT(tmp_path, tmp_path, "S1")
    assert audit["transport_retries"] == 1 and audit["physical_requests"] == 3
    assert not audit["usage_complete"] and audit["successful_deliveries"] == 2


@pytest.mark.parametrize("part", ["inputs", "seal", "request", "result"])
def test_physical_or_seal_tampering_cannot_pass_gold_free_audit(tmp_path, part):
    run = fixture(tmp_path)
    names = {"inputs": "inputs", "seal": "S1_prediction_seal",
        "request": "case_p1_a_request_000", "result": "case_p1_a_request_000_result"}
    path = run.path(names[part])
    data = json.loads(path.read_text(encoding="utf-8"))
    if part == "inputs":
        data[0]["source"]["history_complete"] = False
    elif part == "seal":
        data["prediction_sha256"] = "0" * 64
    elif part == "request":
        data["payload_sha256"] = "0" * 64
    else:
        data["telemetry"]["usage"]["total_tokens"] = 999
    path.write_text(json.dumps(data), encoding="utf-8")
    with pytest.raises(ValueError):
        AUDIT(tmp_path, tmp_path, "S1")
