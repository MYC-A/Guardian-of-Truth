from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23/hybrid_service_v1"))

import campaign  # noqa: E402
from score_campaign import score  # noqa: E402


def test_runner_resume_and_complete_gate(tmp_path, monkeypatch):
    calls = []

    class FakeRuntime:
        def __init__(self, config_id, audit_path=None):
            self.config_id = config_id

        def check(self, case):
            calls.append((self.config_id, case["case_id"]))
            return {"decision": "NO_ERROR", "findings": [],
                    "usage": {"calls": 1, "tokens": 5}}

    monkeypatch.setattr(campaign, "GuardianServiceRuntime", FakeRuntime)
    monkeypatch.setattr(campaign.subprocess, "check_output",
                        lambda cmd, text: "a" * 40 if "rev-parse" in cmd else "")
    arms = ("g0-direct", "g1-ge")
    directory = campaign.run("dev", arms, max_calls=10, max_tokens=100,
                             max_minutes=1, output_root=tmp_path, max_cases=2)
    assert len(calls) == 4
    assert json.loads((directory / "status.json").read_text())["state"] == "SUCCEEDED"
    # A second launch with the same commit/config/input set uses the journal.
    assert campaign.run("dev", arms, max_calls=10, max_tokens=100,
                        max_minutes=1, output_root=tmp_path, max_cases=2) == directory
    assert len(calls) == 4
    report = score(directory)
    assert report["n"] == 2
    assert set(report["arms"]) == set(arms)


def test_scorer_refuses_partial_run(tmp_path):
    path = tmp_path / "run"
    path.mkdir()
    (path / "run_config.json").write_text(json.dumps({"split": "dev"}))
    (path / "status.json").write_text(json.dumps({"state": "PARTIAL"}))
    (path / "summary.json").write_text(json.dumps({"state": "PARTIAL"}))
    with pytest.raises(ValueError, match="incomplete"):
        score(path)
