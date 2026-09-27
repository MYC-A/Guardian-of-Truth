from __future__ import annotations

import json
import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from policy_boundary_probe_v1 import BASE, candidate_cuts, segments_from_ids  # noqa: E402


def test_selected_boundaries_preserve_every_original_byte() -> None:
    policy = "You may add but not remove bags. Ask first."
    candidates = candidate_cuts(policy)
    selected = [candidate["id"] for candidate in candidates
                if candidate["right"].startswith("but") or candidate["right"].startswith("Ask")]
    segments = segments_from_ids(policy, candidates, selected)
    assert segments is not None and len(segments) == 3
    assert "".join(segment["source_quote"] for segment in segments) == policy
    assert [(segment["start"], segment["end"]) for segment in segments] == [
        (0, segments[0]["end"]), (segments[0]["end"], segments[1]["end"]),
        (segments[1]["end"], len(policy))]


def test_invalid_or_reordered_boundary_ids_abstain() -> None:
    policy = "A but B. C"
    candidates = candidate_cuts(policy)
    assert segments_from_ids(policy, candidates, ["invented"]) is None
    assert segments_from_ids(policy, candidates, [candidates[0]["id"]] * 2) is None
    assert segments_from_ids(policy, candidates, [candidates[1]["id"], candidates[0]["id"]]) is None


def test_frozen_gold_boundaries_are_offered_by_code() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    assert len(protocol["tasks"]) == 12
    for task in protocol["tasks"]:
        assert segments_from_ids(task["query"]["policy"], task["query"]["candidate_cuts"],
                                 task["expected_split_ids"]) is not None
