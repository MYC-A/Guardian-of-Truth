"""The frame-gated completion probe receives policy and declared tools only."""
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))

import action_state_probe as frames  # noqa: E402
import completion_frame_probe as probe  # noqa: E402


def test_policy_and_catalog_are_present_for_completed_claim():
    cases = frames.cases(ROOT / "experiments/searh_23/service_desk_v1/cases.csv")
    case = next(row for row in cases if row["id"] == "desk_v1__text_bad_done")
    policy, tools = probe.policy_and_tools(case)
    assert "must never state" in policy
    assert "execute_replacement" in tools
    assert "transfer_specialist" in tools
