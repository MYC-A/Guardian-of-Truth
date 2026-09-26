"""Contract tests for the small action-state component probe."""
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "searh_23"))

import action_state_probe as probe  # noqa: E402


def test_text_gold_covers_exactly_the_text_subset():
    cases = probe.cases(ROOT / "experiments/searh_23/service_desk_v1/cases.csv")
    gold = json.loads((ROOT / "experiments/searh_23/action_state_gold_v1.json")
                      .read_text(encoding="utf-8"))
    text_ids = {case["id"] for case in cases if probe.candidate(case)[0] is None}
    assert text_ids == set(gold)


def test_tool_call_is_attempt_not_success_and_survives_rename():
    for suite in ("service_desk_v1", "service_desk_v1_renamed"):
        cases = probe.cases(ROOT / f"experiments/searh_23/{suite}/cases.csv")
        target = next(case for case in cases if case["id"].endswith("call_ok_replacement"))
        frame, source = probe.candidate(target)
        assert source == "mechanical"
        assert frame["kind"] == "CALL_ATTEMPT"
        assert frame["actor"] == "ASSISTANT"
        assert frame["quote"] in target["response"]


def test_model_quote_must_be_source_anchored():
    text = "Если подтвердите, я оформлю замену."
    valid = {"kind": "FUTURE_OR_CONDITIONAL", "actor": "ASSISTANT",
             "quote": "я оформлю замену"}
    assert probe.validate(valid, text)[1] == []
    invalid = {**valid, "quote": "замена успешно выполнена"}
    assert probe.validate(invalid, text)[0]["kind"] == "UNKNOWN"
