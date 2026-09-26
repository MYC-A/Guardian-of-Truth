from __future__ import annotations

import sys
from pathlib import Path


sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments/searh_23"))

from build_policy_atoms_v1 import SPECS, rows  # noqa: E402
from policy_atoms_probe_v1 import guarded_verdict, optimistic_verdict, source_guard_reason, valid_atom  # noqa: E402


def test_oracle_atoms_match_frozen_contrasts() -> None:
    for spec in SPECS.values():
        if spec.get("expected_unsupported"):
            continue
        for case in rows(spec):
            expected = "VIOLATION" if case["gold"] else "SAFE"
            assert optimistic_verdict(case, spec["gold_atoms"]) == expected


def test_source_guard_rejects_unrepresented_operators() -> None:
    assert source_guard_reason(SPECS["exception_holdout"]["policy"], [])
    assert source_guard_reason(SPECS["numeric_followup"]["policy"], [])
    assert source_guard_reason(SPECS["booking_followup"]["policy"],
                               SPECS["booking_followup"]["gold_atoms"][:2])
    assert source_guard_reason(SPECS["booking_followup"]["policy"],
                               SPECS["booking_followup"]["gold_atoms"]) is None
    spec = SPECS["warehouse_dev"]
    assert source_guard_reason(spec["policy"], [spec["gold_atoms"][0]] * 2) == "explicit_conjunction_atom_missing"


def test_numeric_result_cannot_be_a_boolean_atom() -> None:
    spec = SPECS["numeric_followup"]
    guessed = {"source_quote": "the invoice amount does not exceed the numeric authorization limit",
               "governs_tool": "pay_invoice", "evidence_tool": "get_authorization_limit",
               "join_key": "account_id", "result_field": "limit", "required_value": True,
               "temporal": "LATEST"}
    assert not valid_atom(guessed, spec)
    malformed = {**SPECS["warehouse_dev"]["gold_atoms"][0],
                 "source_quote": "most recent hold check", "temporal": []}
    assert not valid_atom(malformed, SPECS["warehouse_dev"])


def test_wrong_governed_action_cannot_gain_guarded_safe() -> None:
    spec = SPECS["warehouse_dev"]
    atoms = [{**a, "governs_tool": spec["request"]} for a in spec["gold_atoms"]]
    case = next(c for c in rows(spec) if c["name"] == "all_missing")
    assert optimistic_verdict(case, atoms) == "SAFE"
    assert guarded_verdict(case, atoms, source_guard_reason(spec["policy"], atoms)) == "UNKNOWN"


def test_one_wrong_governed_atom_remains_an_unsolved_false_safe() -> None:
    spec = SPECS["warehouse_dev"]
    atoms = [
        {**spec["gold_atoms"][0],
         "source_quote": "its most recent hold check for that same order must say cleared"},
        {**spec["gold_atoms"][1], "governs_tool": spec["request"],
         "source_quote": "its most recent quality inspection must say passed"},
    ]
    case = next(c for c in rows(spec) if c["name"] == "atom1_missing")
    assert case["gold"] == 1
    assert all(valid_atom(atom, spec) for atom in atoms)
    assert source_guard_reason(spec["policy"], atoms) is None
    assert guarded_verdict(case, atoms, None) == "SAFE"


def test_prior_true_requires_actual_boolean_result() -> None:
    spec = SPECS["finance_holdout"]
    case = next(c for c in rows(spec) if c["name"] == "all_satisfied")
    case["history"][1]["result"]["verified"] = 1
    assert optimistic_verdict(case, spec["gold_atoms"]) == "UNKNOWN"


def test_temporal_misread_is_visible_on_post_hoc_contrast() -> None:
    spec = SPECS["records_dev"]
    case = next(c for c in rows(spec) if c["name"] == "all_satisfied")
    case["history"].append({"tool": "check_owner_approval",
                            "arguments": {"document_id": "D-1"},
                            "result": {"document_id": "D-1", "approved": False}})
    incorrect = [{**spec["gold_atoms"][0], "temporal": "LATEST"}, spec["gold_atoms"][1]]
    assert optimistic_verdict(case, spec["gold_atoms"]) == "SAFE"
    assert optimistic_verdict(case, incorrect) == "VIOLATION"


def test_exception_model_conjunction_rejects_a_valid_emergency() -> None:
    spec = SPECS["exception_holdout"]
    atoms = [
        {"governs_tool": "dispatch_shipment", "evidence_tool": name,
         "join_key": "shipment_id", "result_field": field,
         "required_value": value, "temporal": "LATEST"}
        for name, field, value in (("check_customs", "cleared", True),
                                   ("check_supervisor", "approved", True),
                                   ("check_emergency", "active", False))]
    case = {"target_tool": "dispatch_shipment", "target_arguments": spec["ids"],
            "history": [{"tool": "check_emergency",
                         "arguments": {"shipment_id": "S-1"},
                         "result": {"shipment_id": "S-1", "active": True}}]}
    assert optimistic_verdict(case, atoms) == "VIOLATION"
    assert source_guard_reason(spec["policy"], atoms) is not None
