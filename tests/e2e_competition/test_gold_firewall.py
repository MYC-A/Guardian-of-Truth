"""Gold firewall invariance tests for the competition adapter (§6 of the
competition-real-input-audit cycle).

Invariants under test (offline deterministic backend, no LLM):
1. Changing label/explanation while prompt+response stay byte-identical
   -> predictions byte-identical.
2. Renaming id -> per-case prediction labels byte-identical (id is an
   output-joining key only and must never influence the semantic decision).
3. firewall_rows physically drops every column except id/prompt/response.
4. Crash containment: a crashing case is UNRESOLVED (label 0), never a
   fabricated verdict.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pandas as pd
import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "scripts"))

from predict_e2e_competition import (OfflineMissBackend, analyze_case,  # noqa: E402
                                     build_guardian, firewall_rows)
from guardian_truth.vnext.e2e.backend_v1 import E2ECachingBackend  # noqa: E402
from guardian_truth.vnext.e2e.competition_adapter_v1 import (  # noqa: E402
    parse_competition_case, to_e2e_case)

VALID = ROOT / "valid.parquet"


@pytest.fixture(scope="module")
def sample_rows() -> list[dict]:
    df = pd.read_parquet(VALID).head(3)
    return df.to_dict("records")


def _labels(records: list[dict]) -> list[tuple[str, int]]:
    backend = E2ECachingBackend(OfflineMissBackend(), cache_path=None)
    guardian = build_guardian("C2", backend, None)
    out = []
    for row in records:
        comp = parse_competition_case(row["id"], row["prompt"], row["response"])
        record = analyze_case(guardian, comp, "C2")
        out.append((row["id"], int(record["binary_label"]), record["core_status"]))
    return out


def test_firewall_drops_extra_columns(sample_rows):
    kept = firewall_rows(sample_rows)
    for original, filtered in zip(sample_rows, kept):
        assert set(filtered) == {"id", "prompt", "response"}
        assert filtered["prompt"] == str(original["prompt"])
        assert filtered["response"] == str(original["response"])
        # label/explanation values physically absent from the inference frame
        assert "label" not in filtered
        assert "explanation" not in filtered


def test_label_explanation_invariance(sample_rows):
    """Flip labels, replace explanations -> identical predictions."""
    baseline = _labels(sample_rows)
    mutated = []
    for i, row in enumerate(sample_rows):
        mutated.append({**row, "label": 1 - int(row["label"]),
                        "explanation": f"fabricated explanation {i}"})
    mutated_labels = _labels(mutated)
    assert [(cid, label) for cid, label, _ in baseline] == \
           [(cid, label) for cid, label, _ in mutated_labels]
    assert [status for _, _, status in baseline] == \
           [status for _, _, status in mutated_labels]


def test_id_rename_invariance(sample_rows):
    """Rename ids -> per-case labels and core statuses identical."""
    baseline = _labels(sample_rows)
    renamed = [{**row, "id": str(row["id"]) + "_renamed"} for row in sample_rows]
    renamed_labels = _labels(renamed)
    assert [label for _, label, _ in baseline] == [label for _, label, _ in renamed_labels]
    assert [status for _, _, status in baseline] == [status for _, _, status in renamed_labels]


def test_gold_fields_never_populated(sample_rows):
    row = sample_rows[0]
    comp = parse_competition_case(str(row["id"]), str(row["prompt"]), str(row["response"]))
    case = to_e2e_case(comp)
    assert case.gold_core_status == ""
    assert case.gold_binary is None
    assert case.t1_contracts == ()
    assert case.state_contract is None
    assert case.authoritative_policy_readings == ()
    assert case.authoritative_goal_readings == ()
    assert case.authoritative_policy_behaviors == ()
    assert case.authoritative_goal_behaviors == ()


def test_crash_is_unresolved_never_fabricated():
    backend = E2ECachingBackend(OfflineMissBackend(), cache_path=None)
    guardian = build_guardian("C2", backend, None)

    class ExplodingCase:
        pass

    record = analyze_case(guardian, ExplodingCase(), "C2")
    assert record["core_status"] == "UNRESOLVED"
    assert record["binary_label"] == 0
    assert record["diagnostics"]["primary"] == "EXECUTION_ERROR"
