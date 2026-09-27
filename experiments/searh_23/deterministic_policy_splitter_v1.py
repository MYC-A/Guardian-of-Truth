"""Conservative source-preserving segmentation of explicit directive markers.

This recognizes a narrow, code-owned grammar. It is evaluated once against
the separately frozen original-clause holdout; unsupported implicit syntax
must not be treated as fully covered by this splitter.
"""
from __future__ import annotations

import argparse
import json
import re

from build_policy_atoms_v1 import ROOT
from policy_model_ab_v1 import sha


SOURCE = ROOT / "experiments/searh_23/deterministic_segmentation_holdout_v1/frozen.json"
OUT = ROOT / "outputs/searh_23/deterministic_policy_splitter_v1"
SENTENCE = re.compile(r"[.!?;]\s+(?=\S)")
INDEPENDENT_AFTER_COMMA = re.compile(
    r",\s+(?=(?:and\s+(?:you\b|the\s+agent\b|the\s+user\b|do\s+not\b|never\b|must\b|should\b)"
    r"|but\b|you\s+must\b|you\s+should\b|the\s+agent\s+must\b|the\s+user\s+should\b))",
    re.I,
)
BUT = re.compile(r"\bbut\b", re.I)
PRIOR_MODAL = re.compile(r"\b(?:can|may|must|should)\b", re.I)
NEGATIVE_FACET = re.compile(r"(?:not\b|cannot\b|must\s+not\b|never\b|you\s+must\b)", re.I)


def protected_characters(policy: str) -> set[int]:
    """Keep quoted examples, inline code and parenthesized text together."""
    protected = set()
    quote = None
    depth = 0
    escaped = False
    for index, char in enumerate(policy):
        if quote is not None:
            protected.add(index)
            if char == quote and not escaped:
                quote = None
            escaped = char == "\\" and not escaped
        elif char in {'"', '`'}:
            quote = char
            protected.add(index)
            escaped = False
        elif char == "(":
            depth += 1
            protected.add(index)
        elif char == ")" and depth:
            protected.add(index)
            depth -= 1
        elif depth:
            protected.add(index)
    return protected


def split_policy(policy: str) -> tuple[list[int], list[dict]]:
    """Return selected offsets and a complete byte-for-byte source partition."""
    if not isinstance(policy, str) or not policy:
        raise ValueError("original nonempty policy required")
    protected = protected_characters(policy)
    offsets = {match.end() for match in SENTENCE.finditer(policy) if match.start() not in protected}
    offsets.update(match.end() for match in INDEPENDENT_AFTER_COMMA.finditer(policy)
                   if match.start() not in protected)
    for match in BUT.finditer(policy):
        if match.start() in protected:
            continue
        left = policy[max(0, match.start() - 90):match.start()]
        right = policy[match.end():match.end() + 45].lstrip()
        if PRIOR_MODAL.search(left) and NEGATIVE_FACET.match(right):
            offsets.add(match.start())
    cuts = sorted(position for position in offsets if 0 < position < len(policy))
    positions = [0, *cuts, len(policy)]
    segments = [{"start": left, "end": right, "source_quote": policy[left:right]}
                for left, right in zip(positions, positions[1:])]
    assert "".join(segment["source_quote"] for segment in segments) == policy
    return cuts, segments


def score() -> dict:
    protocol = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        cuts, segments = split_policy(task["policy"])
        rows.append({"id": task["id"], "source": task["source"],
                     "expected_cut_offsets": task["expected_cut_offsets"],
                     "actual_cut_offsets": cuts, "exact": cuts == task["expected_cut_offsets"],
                     "segments": segments, "global_verdict": "UNKNOWN"})
    result = {"source_protocol_sha256": sha(protocol), "rows": rows,
              "exact": sum(row["exact"] for row in rows), "total": len(rows),
              "note": "post-hoc selected holdout; narrow explicit marker grammar"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("phase", choices=("score",))
    parser.parse_args()
    print(json.dumps(score()))
