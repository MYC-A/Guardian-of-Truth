"""Missing a planned arm must be rejected before any label scorer runs."""
import json
import sys
from pathlib import Path
import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] /
                      "experiments/searh_23/hybrid_service_v1"))
import score_sealed_complete as module


def test_partial_run_never_calls_label_scorer(tmp_path, monkeypatch):
    (tmp_path / "status.json").write_text('{"state":"RUNNING"}')
    (tmp_path / "summary.json").write_text('{"state":"SUCCEEDED"}')
    monkeypatch.setattr(module, "score", lambda _: pytest.fail("labels must stay closed"))
    with pytest.raises(ValueError, match="all planned sealed runs"):
        module.run([tmp_path], tmp_path / "score.json")


def test_succeeded_single_arm_cannot_open_gold_for_whole_shortlist(tmp_path, monkeypatch):
    protocol = json.loads((module.HERE / "dataset/sealed_hybrid_v1/protocol.json").read_text(
        encoding="utf-8"))
    ids = [r["id"] for r in map(json.loads,
        (module.DATA / "sealed_input.jsonl").read_text(encoding="utf-8").splitlines())]
    (tmp_path / "status.json").write_text('{"state":"SUCCEEDED","run_id":"mock"}')
    (tmp_path / "summary.json").write_text('{"state":"SUCCEEDED"}')
    (tmp_path / "run_config.json").write_text(json.dumps({"split": "sealed",
        "input_sha256": protocol["input_sha256"], "case_ids": ids}))
    (tmp_path / "results.jsonl").write_text("".join(json.dumps({"status": "COMPLETED",
        "run_id": "mock", "config_id": "g0-direct", "case_id": cid}) + "\n" for cid in ids))
    monkeypatch.setattr(module, "score", lambda _: pytest.fail("labels must stay closed"))
    with pytest.raises(ValueError, match="missing or extra registered arms"):
        module.run([tmp_path], tmp_path / "score.json")
