from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from policy_segmentation_probe_v1 import segment_spans  # noqa: E402


def test_literal_disjoint_segments_can_cover_contrasting_directions() -> None:
    policy = "You may add but not remove bags."
    spans, missing = segment_spans(policy, [{"quote": "You may add"},
                                            {"quote": "not remove bags"}])
    assert spans is not None and missing == []


def test_missing_operator_or_content_is_visible() -> None:
    policy = "Only if approved may you publish."
    spans, missing = segment_spans(policy, [{"quote": "approved"}, {"quote": "publish"}])
    assert spans is not None and {"Only", "if", "may", "you"} <= set(missing)


def test_repeated_or_overlapping_quotes_are_rejected() -> None:
    assert segment_spans("check then check", [{"quote": "check"}])[0] is None
    assert segment_spans("You may add but not remove bags.",
                         [{"quote": "You may add but"}, {"quote": "but not remove bags"}])[0] is None
