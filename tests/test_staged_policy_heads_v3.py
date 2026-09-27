from __future__ import annotations

import json
import sys
from collections import Counter
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from staged_policy_heads_v3 import BASE, PUBLIC_GOLD, signature, valid_head  # noqa: E402
from staged_policy_tree_v1 import unique_span  # noqa: E402


def test_public_gold_keeps_permission_and_prohibition_separate() -> None:
    for name in ("airline_baggage", "airline_passenger_count"):
        heads = PUBLIC_GOLD[name]
        assert len(heads) == 2
        assert {h["kind"] for h in heads} == {"PERMISSION", "PROHIBITION"}
        assert heads[0]["governed_tools"] == heads[1]["governed_tools"]


def test_one_of_three_modification_tools_cannot_match_full_scope() -> None:
    expected = PUBLIC_GOLD["retail_modify"][0]
    selected = {**expected, "governed_tools": expected["governed_tools"][:1]}
    assert Counter([signature(expected)]) != Counter([signature(selected)])


def test_frozen_action_quote_is_unique_and_literal() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    assert len(protocol["tasks"]) == 12
    for task in protocol["tasks"]:
        for head in task["expected"]:
            assert unique_span(task["query"]["policy"], head["action_quote"]) is not None


def test_head_validator_rejects_undeclared_and_malformed_tools() -> None:
    tools = {"publish_archive": "Releases an archive."}
    head = {"kind": "PRECONDITION", "governed_tools": ["publish_archive"],
            "prerequisite_tools": [], "action_meaning": "publish"}
    assert valid_head(head, tools)
    assert not valid_head({**head, "governed_tools": ["invented"]}, tools)
    assert not valid_head({**head, "governed_tools": [{"tool": "publish_archive"}]}, tools)
    assert not valid_head({**head, "kind": ["PRECONDITION"]}, tools)
