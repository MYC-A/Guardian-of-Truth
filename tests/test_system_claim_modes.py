"""A model's claim proposal must keep exact response provenance."""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from guardian_truth.integration.claim_modes import validate_claim_proposal


def test_exact_claim_modes_and_source_offsets():
    response = "I checked R-2. After approval, I can publish R-2."
    raw = json.dumps({"claims": [
        {"quote": "I checked R-2.", "mode": "CLAIMED_COMPLETED", "actor": "ASSISTANT"},
        {"quote": "After approval, I can publish R-2.",
         "mode": "CONDITIONAL", "actor": "ASSISTANT"}]})
    claims, issues = validate_claim_proposal(response, raw)
    assert not issues and len(claims) == 2
    assert all(response[x.start:x.end] == x.quote for x in claims)


def test_paraphrase_and_ambiguous_duplicate_quote_are_rejected():
    claims, issues = validate_claim_proposal(
        "Done. Done.", json.dumps({"claims": [
            {"quote": "I did it", "mode": "CLAIMED_COMPLETED", "actor": "ASSISTANT"},
            {"quote": "Done.", "mode": "CLAIMED_COMPLETED", "actor": "ASSISTANT"}]}))
    assert not claims and issues == ("0:quote_not_in_source", "1:ambiguous_quote")
