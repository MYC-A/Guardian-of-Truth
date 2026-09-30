from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.integration.candidate_claims import MeaningCandidate, validate_proposal


def test_candidate_model_cannot_invent_missing_quote_or_id():
    c = (MeaningCandidate("c0", "task.done", "task", ("Completes a task",)),)
    rows, issues = validate_proposal("I can finish it later.", c, json.dumps({
        "candidates": [
            {"id": "c0", "mode": "CLAIMED_COMPLETED", "quote": "I finished it."},
            {"id": "c1", "mode": "NONE", "quote": ""}]}))
    assert rows == ()
    assert "0:quote_not_unique_source" in issues
    assert "1:invalid_candidate_or_mode" in issues


def test_complete_candidate_rows_accept_exact_proposal():
    c = (MeaningCandidate("c0", "task.done", "task", ("Completes a task",)),)
    response = "I can finish it later."
    rows, issues = validate_proposal(response, c, json.dumps({"candidates": [
        {"id": "c0", "mode": "PROPOSED", "quote": response}]}))
    assert not issues and rows[0]["predicate"] == "task.done"
    assert rows[0]["start"] == 0 and rows[0]["end"] == len(response)
