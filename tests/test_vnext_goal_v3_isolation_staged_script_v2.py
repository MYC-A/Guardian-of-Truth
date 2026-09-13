"""Full artifact/scoring boundary tests with injected transport, zero network."""

from copy import deepcopy
import json
from pathlib import Path
import runpy

import pytest

from guardian_truth.vnext.goal_v3_isolation_runner_v2 import CONFIG, StageRunnerV2
from guardian_truth.vnext.integrity import digest, write_new
from test_vnext_goal_v3_isolation_runner_v2 import FakeClient, completion
from test_vnext_goal_v3_user_execution_v2 import source


def setup(tmp_path, monkeypatch, *, count=12, outcome=None):
    module = runpy.run_path(str(Path(__file__).resolve().parents[1] / "scripts/evaluate_goal_v3_isolation_v2.py"))
    globals_ = module["score"].__globals__
    s1 = [f"P{index:02d}:a" for index in range(1, count + 1)]
    frozen = {"architecture_commit": "a" * 40, "configuration": deepcopy(CONFIG),
        "stages": {"S1": s1, "S2": [], "S3": []}, "case_ids": s1,
        "case_inventory": [{"case_id": cid, "pair_id": cid.split(":")[0], "families": ["F1"]} for cid in s1]}
    monkeypatch.setitem(globals_, "OUT", tmp_path)
    monkeypatch.setitem(globals_, "verify", lambda: frozen)
    write_new(globals_["path"]("inference_freeze"), frozen)
    write_new(globals_["path"]("inputs"), [{"case_id": cid, "source": source()} for cid in s1])
    expected = {"expected_status": "PROVED_NO_ERROR", "expected_alignment": "DIRECT_GOAL",
        "expected_rule_outcomes": {}, "expected_temporal_status": {}, "expected_effect_status": {},
        "expected_decisive_violation": [], "expected_unknowns": [], "expected_entity": "ORDER-82",
        "expected_actor": "assistant", "expected_evidence_actor": None}
    write_new(globals_["path"]("gold"), {cid: expected for cid in s1})
    client = FakeClient([completion() if outcome is None else outcome for _ in s1])
    runner = StageRunnerV2(tmp_path, frozen, client, sleeper=lambda _: None)
    runner.run("S1", {cid: source() for cid in s1})
    return globals_, frozen, client


def test_full_smoke_scores_after_seal_and_admits_only_with_verified_artifacts(tmp_path, monkeypatch):
    globals_, frozen, client = setup(tmp_path, monkeypatch)
    report = globals_["score"]("S1")
    assert report["admission"]["verdict"] == "ADMIT_S2"
    assert report["metrics"]["behavioral_accuracy"] == 1
    assert report["metrics"]["correct_certified_resolution_rate"] == 1
    assert report["cost"]["admitted_physical_requests"] == 12
    assert globals_["score"]("S1") == report and len(client.calls) == 12


def test_partial_budget_stop_keeps_not_run_separate_from_unknown_predictions(tmp_path, monkeypatch):
    globals_, _, _ = setup(tmp_path, monkeypatch, outcome=completion(usage={}))
    report = globals_["score"]("S1")
    assert report["admission"]["verdict"] == "BUDGET_STOP"
    assert report["metrics"]["attempted_cases"] == 1
    assert len(report["not_run_case_ids"]) == 11
    assert report["cost"]["usage_complete"] is False


@pytest.mark.parametrize("artifact", ["seal", "boundary", "budget", "physical", "missing_result", "prediction"])
def test_artifact_tampering_rejected_before_gold_open(tmp_path, monkeypatch, artifact):
    globals_, frozen, _ = setup(tmp_path, monkeypatch)
    if artifact == "seal":
        target = globals_["path"]("S1_prediction_seal")
        data = json.loads(target.read_text(encoding="utf-8"))
        data["prediction_sha256"] = "0" * 64
    elif artifact in {"boundary", "budget"}:
        target = globals_["path"]("S1_boundary")
        data = json.loads(target.read_text(encoding="utf-8"))
        if artifact == "boundary":
            data["attempted_case_ids"] = ["invented"]
        else:
            data["budget"]["reported_tokens"] = 0
    elif artifact in {"physical", "missing_result"}:
        target = globals_["path"]("case_p01_a_request_000_result")
        if artifact == "missing_result":
            target.unlink()
            data = None
        else:
            data = json.loads(target.read_text(encoding="utf-8"))
            data["telemetry"]["usage"]["total_tokens"] = 999
    else:
        target = globals_["path"]("S1_predictions")
        data = json.loads(target.read_text(encoding="utf-8"))
        data[0]["proposal"]["status"] = "PROVED_ERROR"
    # Test fixture corruption, not production artifact editing.
    if data is not None:
        target.write_text(json.dumps(data), encoding="utf-8")
    original = globals_["read"]
    gold_opened = []

    def guarded(name):
        if name == "gold":
            gold_opened.append(name)
            raise AssertionError("gold must remain closed on invalid seal/capture")
        return original(name)

    monkeypatch.setitem(globals_, "read", guarded)
    with pytest.raises(ValueError):
        globals_["score"]("S1")
    assert not gold_opened
