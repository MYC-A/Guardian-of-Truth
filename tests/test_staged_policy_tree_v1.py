from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from build_policy_atoms_v1 import SPECS  # noqa: E402
from staged_source_role_gate_v1 import disjoint  # noqa: E402
from staged_policy_tree_v1 import inventory_spans, unique_span, unsupported_reason, valid_binding  # noqa: E402


def test_unsupported_constructs_abstain_before_model() -> None:
    assert unsupported_reason(SPECS["exception_holdout"]["policy"])
    assert unsupported_reason(SPECS["numeric_followup"]["policy"])
    assert unsupported_reason(SPECS["warehouse_dev"]["policy"]) is None


def test_quotes_must_be_unique_literal_substrings() -> None:
    assert unique_span("refund then refund", "refund") is None
    assert unique_span("refund", "Refund") is None
    assert unique_span("refund", "refund") == {"start": 0, "end": 6}


def test_explicit_and_requires_one_condition_on_each_side() -> None:
    policy = SPECS["warehouse_dev"]["policy"]
    hold = "its most recent hold check for that same order must say cleared"
    quality = "its most recent quality inspection must say passed"
    assert inventory_spans(policy, [hold, quality]) is not None
    assert inventory_spans(policy, [hold]) is None
    assert inventory_spans(policy, [hold, hold]) is None
    assert inventory_spans(policy, [policy]) is None


def test_binding_is_limited_to_declared_boolean_evidence() -> None:
    spec = SPECS["warehouse_dev"]
    good = {"evidence_tool": "check_hold", "join_key": "order_id",
            "result_field": "cleared", "required_value": True, "temporal": "LATEST"}
    assert valid_binding(good, spec["tools"], ["order_id"])
    assert not valid_binding({**good, "evidence_tool": "release_order"}, spec["tools"], ["order_id"])
    assert not valid_binding({**good, "required_value": 1}, spec["tools"], ["order_id"])
    assert not valid_binding({**good, "temporal": "CURRENT"}, spec["tools"], ["order_id"])
    numeric = SPECS["numeric_followup"]
    guess = {"evidence_tool": "get_authorization_limit", "join_key": "account_id",
             "result_field": "limit", "required_value": True, "temporal": "LATEST"}
    assert not valid_binding(guess, numeric["tools"], ["account_id"])


def test_action_quote_cannot_reuse_prerequisite_source_span() -> None:
    action = {"start": 10, "end": 20}
    assert not disjoint(action, {"start": 12, "end": 16})
    assert disjoint(action, {"start": 20, "end": 25})
