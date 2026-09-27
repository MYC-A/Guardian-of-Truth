from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from policy_architecture_abcd_v1 import (BASE, all_quotes, compile_tree, exact,
                                         normalize_directives)  # noqa: E402


def test_frozen_inputs_do_not_contain_gold_and_quotes_are_unique() -> None:
    protocol = json.loads((BASE / "frozen.json").read_text(encoding="utf-8"))
    gold = json.loads((BASE / "gold.json").read_text(encoding="utf-8"))
    assert len(protocol["cases"]) == 12
    for case in protocol["cases"]:
        assert "gold" not in case and "expected" not in case
        policy = case["query"]["policy"]
        assert all(policy.count(q) == 1 for d in gold[case["id"]] for q in all_quotes(d))


def test_tree_compiler_keeps_action_and_condition_distinct() -> None:
    tree = {"op": "GATE",
            "left": {"op": "ATOM", "role": "ACTION", "quote": "perform the swap",
                     "tools": ["perform_swap"], "temporal": "NONE"},
            "right": {"op": "AND",
                      "left": {"op": "ATOM", "role": "CONDITION", "quote": "approval exists",
                               "tools": [], "temporal": "PRIOR_TRUE"},
                      "right": {"op": "ATOM", "role": "CONDITION", "quote": "status is current",
                                "tools": [], "temporal": "LATEST"}}}
    directives, errors = compile_tree(tree)
    assert errors == []
    assert len(directives) == 1
    assert directives[0]["governed_tools"] == ["perform_swap"]
    assert directives[0]["condition"]["op"] == "AND"
    assert [x["temporal"] for x in directives[0]["condition"]["children"]] == ["PRIOR_TRUE", "LATEST"]


def test_exception_and_concession_are_not_exact_equivalent() -> None:
    base = {"op": "FORBID", "left": {"op": "ATOM", "role": "ACTION",
                                     "quote": "publish a draft", "tools": ["publish"], "temporal": "NONE"}}
    context = {"op": "ATOM", "role": "CONDITION", "quote": "owner approves", "tools": [], "temporal": "NONE"}
    exception, _ = compile_tree({"op": "EXCEPT", "left": base, "right": context})
    concession, _ = compile_tree({"op": "EVEN_IF", "left": base, "right": context})
    assert exception[0]["exception_type"] == "EXCEPT"
    assert concession[0]["exception_type"] == "EVEN_IF"
    assert exact(exception[0]) != exact(concession[0])


def test_direct_ir_rejects_nonliteral_action() -> None:
    row = {"kind": "PERMIT", "action_quote": "invented action", "governed_tools": ["publish"],
           "condition": None, "before_quote": "", "exception_quote": "",
           "exception_type": "NONE", "scope_quote": ""}
    directives, errors = normalize_directives({"directives": [row]}, "May publish a draft.", {"publish": "Publish."})
    assert directives[0]["action_quote"] == ""
    assert errors == ["bad_action_span_0"]
