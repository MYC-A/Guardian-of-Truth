"""Counterexamples for scope filtering and independent call-shape checks."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "searh_23"))

from call_scope_v1 import malformed_call, scoped_verdict
from call_scope_replay import replay


IDENTITY = ("Before modifying or cancelling any reservation you MUST verify "
            "the guest's identity: the name on the ID must match the name "
            "on the reservation.")


def item(action="process_refund", arguments=None):
    return {"policy": IDENTITY, "tools": {
        "process_refund": "- process_refund — Process a refund.\n"
                          "    reservation_id: string! — ID.\n"
                          "    amount: integer! — Dollars.\n",
        "modify_reservation": "- modify_reservation — Modify a reservation.\n"
                              "    reservation_id: string! — ID.\n"},
        "target": {"tool": action, "json_valid": True,
                   "arguments": arguments if arguments is not None else
                   {"reservation_id": "R-1", "amount": 250}}}


def test_identity_clause_does_not_govern_refund_but_does_govern_modification():
    accusation = {"verdict": "VIOLATION", "checks": [
        {"status": "BROKEN", "policy_quote": IDENTITY}]}
    assert scoped_verdict(accusation, item())["verdict"] == "UNKNOWN"
    assert scoped_verdict(accusation, item("modify_reservation",
             {"reservation_id": "R-1"}))["verdict"] == "VIOLATION"


def test_paraphrased_policy_quote_cannot_be_filtered():
    accusation = {"verdict": "VIOLATION", "checks": [
        {"status": "BROKEN", "policy_quote": "Before modifying or cancelling any reservation, verify the guest identity."}]}
    assert scoped_verdict(accusation, item())["verdict"] == "VIOLATION"


def test_structural_violation_survives_bad_model_reason():
    broken = item(arguments={"reservation_id": "R-1"})
    accusation = {"verdict": "VIOLATION", "checks": [
        {"status": "BROKEN", "policy_quote": IDENTITY}]}
    assert malformed_call(broken) == ["missing:amount"]
    result = scoped_verdict(accusation, broken)
    assert result["verdict"] == "VIOLATION"
    assert result["structural_errors"] == ["missing:amount"]


def test_replay_seal_survives_windows_text_checkout(tmp_path):
    source = (Path(__file__).resolve().parents[1] / "outputs" / "searh_23" /
              "call_condition_probe" / "service_desk_v1")
    for name in ("input.json", "predictions.jsonl", "score.json"):
        data = (source / name).read_bytes().replace(b"\r\n", b"\n")
        (tmp_path / name).write_bytes(data.replace(b"\n", b"\r\n"))
    report = replay(tmp_path / "input.json", tmp_path / "predictions.jsonl",
                    tmp_path / "score.json")
    assert report["counts"]["TP"] == 8
    assert report["counts"]["FN"] == 0
