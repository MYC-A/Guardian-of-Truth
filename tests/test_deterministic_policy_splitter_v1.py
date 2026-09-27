from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from deterministic_policy_splitter_v1 import split_policy  # noqa: E402


def test_do_not_split_quoted_or_parenthesized_examples() -> None:
    policy = 'Say "approve; then charge" only after review. Ask for confirmation.'
    cuts, segments = split_policy(policy)
    assert len(cuts) == 1
    assert "".join(segment["source_quote"] for segment in segments) == policy
    assert "approve; then charge" in segments[0]["source_quote"]
    assert split_policy("Use tool_name(args; kwargs) after approval.")[0] == []
    assert split_policy("The example is `can add but not remove`.")[0] == []


def test_explicit_contrast_and_independent_sentence_split() -> None:
    policy = "You may add but not remove bags. Ask before charging."
    cuts, segments = split_policy(policy)
    assert len(cuts) == 2
    assert "".join(segment["source_quote"] for segment in segments) == policy


def test_shared_if_and_and_conditions_stay_with_parent() -> None:
    policy = "Before refunding, verify identity and obtain approval."
    assert split_policy(policy)[0] == []
