"""Freeze 16 manually audited SYSTEM rules without reading labels/explanations."""

import argparse
import hashlib
import json
from pathlib import Path

import pandas as pd

from guardian_truth.parsing import parse_events


# Meanings below were manually frozen before model runs.  They are scoring data
# and must never be included in an inference request.
CASES = [
    ("confirm_before_db_update", "airline__21::t7",
     "Before taking any actions that update the booking database (booking, modifying flights, editing baggage, changing cabin class, or updating passenger information), you must list the action details and obtain explicit user confirmation (yes) to proceed.",
     True, ["ONLY_IF"], ["REQUIRED"], ["BEFORE", "AND"], "MUST", "ALL", False, False,
     ["update action", "list action details before action", "explicit yes confirmation before same action"]),
    ("turn_tool_message_exclusion", "airline__23::t10",
     "You should only make one tool call at a time, and if you make a tool call, you should not respond to the user simultaneously. If you respond to the user, you should not make a tool call at the same time.",
     True, ["UNCONDITIONAL"], ["REQUIRED"], ["LE", "COUNT", "NOT", "AND"], "SHOULD", "ALL", True, False,
     ["tool calls in one turn <= 1", "tool call and user message are mutually exclusive in a turn"]),
    ("reservation_passenger_cap", "airline__10::t19",
     "Each reservation can have at most five passengers.",
     True, ["UNCONDITIONAL"], ["ASSERTED"], ["LE", "COUNT"], "MUST", "ALL", False, False,
     ["per reservation", "passenger count <= 5"]),
    ("reservation_payment_cardinality", "airline__24::t14",
     "Each reservation can use at most one travel certificate, at most one credit card, and at most three gift cards.",
     True, ["UNCONDITIONAL"], ["ASSERTED"], ["AND", "LE", "COUNT"], "MUST", "ALL", False, False,
     ["travel certificate count <= 1", "credit card count <= 1", "gift card count <= 3", "same reservation"]),
    ("cancellation_or_conditions", "airline__44::t22",
     "Otherwise, flight can be cancelled if any of the following is true:\n- The booking was made within the last 24 hrs\n- The flight is cancelled by airline\n- It is a business flight\n- The user has travel insurance and the reason for cancellation is covered by insurance.",
     False, ["IF"], ["PERMITTED"], ["OR", "AND", "LE"], "MAY", "ANY", False, True,
     ["requires preceding otherwise branch", "booking age <= 24 hours", "airline cancellation", "business flight", "insurance and covered reason"]),
    ("partial_segment_retention", "airline__8::t7",
     "Some flight segments can be kept, but their prices will not be updated based on the current price.",
     False, ["UNCONDITIONAL"], ["PERMITTED", "REQUIRED"], ["NOT", "EQ"], "MAY", "SOME", True, False,
     ["permission to keep a subset", "kept segment price remains original"]),
    ("identity_two_of_four", "banking_knowledge__task_005::t6",
     "To verify the identity of the user, call the appropriate read tools, and ensure that they are able to give correctly any 2 out of the following values: date of birth, email, phone number, address. Knowing full name or userID is not enough to verify. After verification, you must call the verification logging tool to properly log the information into the verification records. Do not leak any information about the user before they are verified.",
     False, ["ONLY_IF", "IF"], ["REQUIRED", "PROHIBITED"], ["GE", "COUNT", "BEFORE", "AFTER", "NOT"], "MUST", "ANY", True, False,
     ["2 of dob/email/phone/address correct", "full name/user id insufficient", "log after verification", "no leak before verification"]),
    ("discoverable_tool_unlock_sequence", "banking_knowledge__task_083::t10",
     "First, unlock the tool using `unlock_discoverable_agent_tool(agent_tool_name)` with the exact tool name from the knowledge base: you must unlock the tool before using it to get information on the proper params. IMPORTANT: Do not unlock tools that you do not plan on actually using: this causes issues in database logging.\n2. Then, call the tool using `call_discoverable_agent_tool(agent_tool_name, arguments)` with the required arguments\n3. The unlock step is required before calling - you cannot call a tool that hasn't been unlocked",
     False, ["ONLY_IF"], ["REQUIRED", "PROHIBITED"], ["BEFORE", "SAME_ENTITY", "AND", "NOT"], "MUST", "ALL", True, False,
     ["exact KB tool name", "unlock before call", "do not unlock unless planned use", "same agent_tool_name"]),
    ("single_user_scope", "retail__108::t1",
     "You can only help one user per conversation (but you can handle multiple requests from the same user), and must deny any requests for tasks related to any other user.",
     False, ["UNCONDITIONAL", "IF"], ["REQUIRED"], ["LE", "COUNT", "NOT", "EQ"], "MUST", "ALL", True, False,
     ["distinct users per conversation <= 1", "multiple requests by same user allowed", "deny other-user task"]),
    ("cancel_pending_only_if", "retail__12::t4",
     "An order can only be cancelled if its status is 'pending', and you should check its status before taking the action.",
     False, ["ONLY_IF"], ["PERMITTED", "REQUIRED"], ["FIELD_EQUALS", "BEFORE", "AND"], "SHOULD", "ALL", False, False,
     ["latest status pending is necessary", "check same order status before cancellation"]),
    ("cancellation_reason_enum", "retail__14::t1",
     "The user needs to confirm the order id and the reason (either 'no longer needed' or 'ordered by mistake') for cancellation. Other reasons are not acceptable.",
     True, ["ONLY_IF"], ["PERMITTED"], ["AND", "EQ", "OR"], "MUST", "ALL", True, False,
     ["confirm order id", "confirm reason", "reason is no longer needed or ordered by mistake"]),
    ("same_product_different_option", "retail__36::t10",
     "For a pending order, each item can be modified to an available new item of the same product but of different product option. There cannot be any change of product types, e.g. modify shirt to shoe.",
     True, ["ONLY_IF"], ["PERMITTED"], ["FIELD_EQUALS", "AND", "NOT", "EQ"], "MUST", "ALL", True, False,
     ["latest order status pending", "new item available", "same product", "different option", "aligned item pair"]),
    ("expired_contract_resume_exception", "telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13",
     "You are not allowed to lift the suspension if the line's contract end date is in the past, even if the user has paid all their overdue bills.",
     True, ["IF"], ["PROHIBITED"], ["IS_PAST"], "MUST", "ALL", True, True,
     ["same line contract_end_date < current_date", "paid bills do not override prohibition"]),
    ("refuel_two_gb_cap", "telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7",
     "The maximum amount of data that can be refueled is 2GB.",
     True, ["UNCONDITIONAL"], ["ASSERTED"], ["LE"], "MUST", "ALL", False, False,
     ["refuel amount <= 2 GB", "unit is GB", "boundary is inclusive"]),
    ("vpn_disconnect_conjunction", "telecom__mobile_data_issueairplane_mode_on-bad_network_preference-bad_vpn-data_saver_mode_::t7",
     "If `check_vpn_status()` shows \"VPN is ON and connected\" and performance level is \"Poor\", guide the user to use `disconnect_vpn()` to disconnect the VPN.",
     True, ["IF"], ["REQUIRED"], ["AND", "FIELD_EQUALS"], "SHOULD", "ALL", False, False,
     ["current VPN on and connected", "current performance poor", "guide disconnect for same device"]),
    ("mms_necessary_connectivity", "telecom__mms_issuebad_network_preference-bad_wifi_calling-break_apn_mms_setting-break_app_::t7",
     "For MMS to work, the user must have cellular service and mobile data (any speed).",
     True, ["ONLY_IF"], ["ASSERTED"], ["AND"], "MUST", "ANY", False, False,
     ["cellular service necessary", "mobile data necessary", "no minimum speed threshold"]),
]


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, required=True)
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args(argv)
    if args.output.exists():
        raise SystemExit("Output already exists")
    frame = pd.read_parquet(args.input, columns=["id", "prompt"])
    rows = {row.id: row.prompt for row in frame.itertuples(index=False)}
    output = []
    for (case_id, row_id, quote, supported, relations, effects, operators,
         modality, quantifier, negation, exception, requirements) in CASES:
        prompt = rows[row_id]
        start = prompt.find(quote)
        if start < 0 or prompt.find(quote, start + 1) >= 0:
            raise ValueError(f"Missing or ambiguous source: {case_id}")
        end = start + len(quote)
        events = parse_events(prompt, "prompt")
        if not any(event.role == "system" and event.source.start <= start < end <= event.source.end
                   for event in events):
            raise ValueError(f"Source outside SYSTEM: {case_id}")
        relation_set = set(relations)
        condition_feature = ("BOTH" if {"IF", "ONLY_IF"} <= relation_set or "IFF" in relation_set
                             else "NECESSARY" if "ONLY_IF" in relation_set
                             else "SUFFICIENT" if "IF" in relation_set else "NONE")
        output.append({
            "case_id": case_id, "row_id": row_id,
            "source": {"document": "prompt", "role": "SYSTEM", "start": start, "end": end,
                       "sha256": hashlib.sha256(quote.encode()).hexdigest()},
            "rule": quote,
            "gold": {"supported_by_fragment": supported, "relations": relations,
                     "effects": effects, "operators": operators,
                     "features": {"modality": modality, "quantifier": quantifier,
                                  "causality": "NONE", "strength": "NONE",
                                  "condition": condition_feature,
                                  "negation": negation, "exception": exception},
                     "critical_requirements": requirements},
        })
    payload = {
        "schema_version": 1,
        "data_role": "frozen real-rule semantic benchmark",
        "warning": "gold is local scoring metadata and must never enter model messages",
        "selection": "16 unique real SYSTEM rules across airline, banking, retail and telecom; labels and explanations were not read",
        "cases": output,
    }
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(json.dumps({"cases": len(output), "output": str(args.output)}))


if __name__ == "__main__":
    raise SystemExit(main())
