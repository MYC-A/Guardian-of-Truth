"""Counterfactual action-stage controls for source-anchored clause matching."""

from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "experiments" / "searh_23"))

from action_trigger_v1 import bind_clause


CLAUSE = "Before dispatching any parcel, check the address for the same shipment."
CATALOG = {
    "read_address": "- read_address — Read the saved address for a shipment.\n"
                    "    shipment_id: string! — ID.\n",
    "send_parcel": "- send_parcel — Dispatch a parcel.\n"
                   "    shipment_id: string! — ID.\n",
    "read_and_dispatch": "- read_and_dispatch — Read address and dispatch parcel.\n"
                         "    shipment_id: string! — ID.\n",
}


def item(tool, quote=CLAUSE):
    return {"policy": "System rule: " + quote, "tools": CATALOG,
            "target": {"tool": tool, "json_valid": True,
                       "arguments": {"shipment_id": "PK-7"}}}


def test_checking_a_precondition_is_not_dispatching():
    assert bind_clause(item("read_address"), CLAUSE).status == "EXCLUDED"
    assert bind_clause(item("send_parcel"), CLAUSE).status == "MAY_APPLY"


def test_mixed_effect_tool_and_unsupported_clause_abstain():
    assert bind_clause(item("read_and_dispatch"), CLAUSE).status == "UNKNOWN"
    other = "Address checks should be timely and accurate."
    assert bind_clause(item("read_address", other), other).status == "UNKNOWN"


def test_quote_must_be_exact_unique_authoritative_source():
    paraphrase = "Before dispatching a parcel, check the address."
    assert bind_clause(item("read_address"), paraphrase).status == "UNKNOWN"
    duplicated = {**item("read_address"), "policy": CLAUSE + " " + CLAUSE}
    assert bind_clause(duplicated, CLAUSE).status == "UNKNOWN"


def test_ordered_second_action_is_not_the_prerequisite_action():
    quote = "After a replacement completes successfully, record an audit for the same case."
    tools = {"check_replacement": "- check_replacement — Read replacement status.\n",
             "log_audit": "- log_audit — Record a completion audit.\n"}
    case = {"policy": quote, "tools": tools,
            "target": {"tool": "log_audit", "arguments": {}, "json_valid": True}}
    decision = bind_clause(case, quote)
    assert decision.status == "MAY_APPLY"
    assert decision.governed_actions == ("audit",)
