"""Frozen Step 2 dataset builder (sections 25-27).

Authoring discipline:

* Every case is constructed together with its gold — facts are never
  hand-written apart from the trajectory that proves them.
* Minimal pairs share the same tool catalog and differ in exactly one
  evidence source (result shape, entity, field, time).
* The ORACLE track contract mirrors the documented semantics of the tool;
  the REAL track sees only name/description/input-schema (what a deployed
  Guardian actually gets).
* Splits: dev (open), calib (threshold/config decisions), test (sealed).
  The rename and counterfactual suites are derived programmatically from
  base cases with one evidence source flipped.

Run:  python experiments/searh_23/build_step2_dataset.py --out experiments/searh_23/step2_evidence_v1
Committed BEFORE any inference.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import random
from pathlib import Path

# ----------------------------------------------------------------- helpers ---

def _sha(obj) -> str:
    return hashlib.sha256(json.dumps(obj, ensure_ascii=False, sort_keys=True).encode()).hexdigest()[:16]


def tool(name: str, description: str, fields: dict | None = None) -> dict:
    return {"name": name, "description": description,
            "fields": fields or {}}


def f(type_: str = "string", required: bool = True, description: str = "",
      enum: list | None = None) -> dict:
    spec = {"type": type_, "required": required}
    if description:
        spec["description"] = description
    if enum:
        spec["enum"] = enum
    return spec


def call(index: int, call_id: str, tool_name: str, payload: dict) -> dict:
    return {"index": index, "kind": "call", "call_id": call_id,
            "tool": tool_name, "actor": "assistant", "payload": payload}


def result(index: int, call_id: str, tool_name: str, payload, raw: str | None = None) -> dict:
    return {"index": index, "kind": "result", "call_id": call_id,
            "tool": tool_name, "actor": "tool", "payload": payload,
            **({"raw": raw} if raw is not None else {})}


def gold(predicate, entity_type, entity_id, value, truth="TRUE", strength="OBSERVED",
         call_id=None, json_path=None, valid_from=None) -> dict:
    return {"predicate": predicate, "entity_type": entity_type,
            "entity_id": entity_id, "value": value, "truth": truth,
            "strength": strength,
            "provenance": {"call_id": call_id, "json_path": json_path},
            **({"valid_from": valid_from} if valid_from is not None else {})}


def neg(predicate, entity_type, entity_id, value=None) -> dict:
    """An unsupported candidate fact: must NOT be established."""
    return {"predicate": predicate, "entity_type": entity_type,
            "entity_id": entity_id, "value": value, "truth": "UNKNOWN"}


def tq(kind, entity_type, entity_id, predicate, expected, as_of=None, value=None) -> dict:
    return {"query": kind, "entity_type": entity_type, "entity_id": entity_id,
            "predicate": predicate, "expected": expected,
            **({"as_of": as_of} if as_of is not None else {}),
            **({"value": value} if value is not None else {})}


def case(case_id: str, category: str, domain: str, tools: list,
         trajectory: list, gold_facts: list, unsupported: list | None = None,
         contradicted: list | None = None, temporal: list | None = None,
         contracts: dict | None = None, notes: str = "",
         read_tools: list | None = None) -> dict:
    return {
        "case_id": case_id, "category": category, "domain": domain,
        "tools": tools, "trajectory": trajectory, "gold_facts": gold_facts,
        "unsupported_candidate_facts": unsupported or [],
        "contradicted_facts": contradicted or [],
        "temporal_queries": temporal or [],
        "oracle_contracts": contracts or {},
        "notes": notes,
        "_read_tools": read_tools or [],
    }


# ============================================================ domain toolkits ==

RETAIL_TOOLS = [
    tool("cancel_order", "Cancel the whole order.", {"order_id": f(description="The order ID, such as '#12345'.")}),
    tool("get_order_details", "Get the details of an order.", {"order_id": f(description="The order ID.")}),
    tool("exchange_delivered_order_items", "Request an exchange of delivered items for an order.",
         {"order_id": f(), "item_ids": f("array"), "new_item_ids": f("array")}),
    tool("return_delivered_order_items", "Request a return of delivered items.",
         {"order_id": f(), "item_ids": f("array")}),
    tool("audit_order_action", "Write an audit record that an action was intended for an order.",
         {"order_id": f(), "action": f(enum=["cancel", "exchange", "return"])}),
    tool("notify_customer", "Send a notification message to the customer.",
         {"user_id": f(), "message": f()}),
]

AIRLINE_TOOLS = [
    tool("cancel_reservation", "Cancel the whole reservation.", {"reservation_id": f(description="The reservation ID, such as 'ZFA04Y'.")}),
    tool("get_reservation_details", "Get the details of a reservation.", {"reservation_id": f()}),
    tool("book_reservation", "Book a new reservation.", {"user_id": f(), "origin": f(), "destination": f(), "flight_type": f(enum=["round_trip", "one_way"])}),
    tool("request_refund", "Create a refund request for a reservation.", {"reservation_id": f(), "amount": f("number")}),
    tool("log_assistance", "Log that assistance was given about a reservation.", {"reservation_id": f(), "topic": f()}),
]

TELECOM_TOOLS = [
    tool("resume_line", "Activate a suspended line.", {"customer_id": f(), "line_id": f()}),
    tool("get_line_details", "Get the current details of a line.", {"line_id": f()}),
    tool("suspend_line", "Suspend an active line.", {"customer_id": f(), "line_id": f()}),
    tool("schedule_line_change", "Schedule a future change to a line.", {"customer_id": f(), "line_id": f(), "change": f()}),
    tool("record_device_replacement", "Create a replacement record for a device.", {"device_id": f()}),
    tool("write_device_audit", "Write an audit entry about a device.", {"device_id": f(), "note": f()}),
]

BANKING_TOOLS = [
    tool("close_account", "Close the bank account.", {"account_id": f()}),
    tool("get_account_details", "Get the account details.", {"account_id": f()}),
    tool("block_card", "Block a lost or stolen card.", {"card_id": f()}),
    tool("issue_card", "Create a request to issue a new card.", {"account_id": f(), "card_type": f(enum=["debit", "credit"])}),
    tool("record_complaint", "Record a customer complaint.", {"account_id": f(), "text": f()}),
]

SHIPPING_TOOLS = [
    tool("dispatch_parcel", "Dispatch the parcel to the carrier.", {"parcel_id": f()}),
    tool("get_parcel_status", "Get the current status of a parcel.", {"parcel_id": f()}),
    tool("create_return_label", "Create a return shipping label.", {"parcel_id": f(), "reason": f()}),
    tool("scan_note", "Scan and store a delivery note for a parcel.", {"parcel_id": f(), "note": f()}),
]

INSURANCE_TOOLS = [
    tool("cancel_policy", "Cancel the insurance policy.", {"policy_id": f()}),
    tool("get_policy_details", "Get the policy details.", {"policy_id": f()}),
    tool("file_claim", "File a new insurance claim.", {"policy_id": f(), "amount": f("number")}),
    tool("approve_claim", "Approve an insurance claim.", {"claim_id": f(), "amount": f("number")}),
    tool("send_policy_notice", "Send a policy notice document to the customer.", {"policy_id": f(), "template": f()}),
]


# ============================================================== case families ==

def fam_read_status(domain, tools, cat_prefix, entity_tool, entity_arg, entity_id,
                    detail_payload, status_value, extra_gold=None):
    """Read tool returns explicit status -> OBSERVED fact."""
    traj = [
        call(0, "c1", entity_tool, {entity_arg: entity_id}),
        result(1, "c1", entity_tool, detail_payload),
    ]
    return case(f"{cat_prefix}", "read_explicit_status", domain, tools, traj,
                gold_facts=[
                    gold(f"{_etype(entity_arg)}.status", _etype(entity_arg), entity_id,
                         f'"{status_value}"', strength="OBSERVED",
                         call_id="c1", json_path="$.status"),
                ] + (extra_gold or []),
                read_tools=[entity_tool])


def _etype(entity_arg: str) -> str:
    return entity_arg[:-3] if entity_arg.endswith("_id") else entity_arg


def fam_mutation_poststate(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id,
                           result_payload, pred, value_json, strength="EXECUTED"):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, result_payload),
    ]
    return case(cat_prefix, "mutation_poststate", domain, tools, traj,
                gold_facts=[gold(pred, _etype(entity_arg), entity_id, value_json,
                                 strength=strength, call_id="c1",
                                 json_path="$.new_status" if "new_status" in (result_payload or {}) else "$.status")],
                unsupported=[neg(f"{_etype(entity_arg)}.replaced", _etype(entity_arg), entity_id)])


def fam_generic_success(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id, business_pred):
    """{"success": true} alone: business predicate stays UNKNOWN."""
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, {"success": True}),
    ]
    return case(cat_prefix, "generic_success_only", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(business_pred, _etype(entity_arg), entity_id)],
                notes="generic success must not establish business state")


def fam_async_accepted(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id,
                       async_payload, pred, value_json):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, async_payload),
    ]
    return case(cat_prefix, "async_accepted", domain, tools, traj,
                gold_facts=[gold(pred, _etype(entity_arg), entity_id, value_json,
                                 strength="REQUESTED", call_id="c1", json_path="$.status")],
                unsupported=[neg(f"{_etype(entity_arg)}.completed", _etype(entity_arg), entity_id)])


def fam_request_creation(domain, tools, cat_prefix, req_tool, entity_arg, entity_id,
                         payload, pred, value_json):
    traj = [
        call(0, "c1", req_tool, {entity_arg: entity_id, "amount": 250}),
        result(1, "c1", req_tool, payload),
    ]
    return case(cat_prefix, "request_creation", domain, tools, traj,
                gold_facts=[gold(pred, _etype(entity_arg), entity_id, value_json,
                                 strength="REQUESTED", call_id="c1", json_path="$.status")],
                unsupported=[neg(f"{_etype(entity_arg)}.processed", _etype(entity_arg), entity_id),
                             neg(f"{_etype(entity_arg)}.refunded", _etype(entity_arg), entity_id)])


def fam_audit_logging(domain, tools, cat_prefix, audit_tool, business_tool,
                      entity_arg, entity_id, business_pred, audit_payload=None):
    """Audit success: the business predicate stays UNKNOWN. The audit record
    id is a result-born entity with its own binding question (follow-up)."""
    traj = [
        call(0, "c1", audit_tool, {entity_arg: entity_id, "action": "cancel"}),
        result(1, "c1", audit_tool, audit_payload or {"success": True, "audit_id": "a-1042"}),
    ]
    return case(cat_prefix, "audit_logging", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(business_pred, _etype(entity_arg), entity_id)],
                notes="audit success != business action success; audit_id is a "
                      "result-born entity, out of scope for entity-echo binding")


def fam_notification(domain, tools, cat_prefix, notify_tool, entity_arg, entity_id,
                     business_pred):
    traj = [
        call(0, "c1", notify_tool, {entity_arg: entity_id, "message": "Your request was processed."}),
        result(1, "c1", notify_tool, {"success": True, "message_id": "m-88"}),
    ]
    return case(cat_prefix, "notification_sent", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(business_pred, _etype(entity_arg), entity_id)],
                notes="notification sent != business action; message_id is a "
                      "result-born entity")


def fam_mutation_failure(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id,
                         business_pred):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, {"error": "precondition failed", "code": 412}),
    ]
    return case(cat_prefix, "mutation_failure", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(business_pred, _etype(entity_arg), entity_id)])


def fam_partial_result(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, {"success": True, "status": "partially_updated",
                                    "failed_items": ["item_2"]}),
    ]
    return case(cat_prefix, "partial_result", domain, tools, traj,
                gold_facts=[gold(f"{_etype(entity_arg)}.status", _etype(entity_arg), entity_id,
                                 '"partially_updated"', strength="EXECUTED",
                                 call_id="c1", json_path="$.status")],
                unsupported=[neg(f"{_etype(entity_arg)}.fully_updated", _etype(entity_arg), entity_id)])


def fam_later_confirmation(domain, tools, cat_prefix, mut_tool, read_tool,
                           entity_arg, entity_id, mut_payload, read_payload,
                           pred, value_json):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, mut_payload),
        call(2, "c2", read_tool, {entity_arg: entity_id}),
        result(3, "c2", read_tool, read_payload),
    ]
    return case(cat_prefix, "later_confirmation", domain, tools, traj,
                gold_facts=[
                    gold(pred, _etype(entity_arg), entity_id, value_json,
                         strength="EXECUTED", call_id="c1", json_path="$.status",
                         valid_from=1),
                    gold(pred, _etype(entity_arg), entity_id, value_json,
                         strength="OBSERVED", call_id="c2", json_path="$.status",
                         valid_from=3),
                ],
                temporal=[tq("LATEST", _etype(entity_arg), entity_id,
                             pred.replace(f"{_etype(entity_arg)}.", f"{_etype(entity_arg)}.") if "." in pred else pred,
                             value_json)],
                read_tools=[read_tool],
                notes="with J layer: EXECUTED upgraded to CONFIRMED at index 3")


def fam_later_contradiction(domain, tools, cat_prefix, mut_tool, read_tool,
                            entity_arg, entity_id, mut_payload, read_payload,
                            pred, self_value, read_value):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, mut_payload),
        call(2, "c2", read_tool, {entity_arg: entity_id}),
        result(3, "c2", read_tool, read_payload),
    ]
    return case(cat_prefix, "later_contradiction", domain, tools, traj,
                gold_facts=[
                    gold(pred, _etype(entity_arg), entity_id, self_value,
                         strength="EXECUTED", call_id="c1", json_path="$.status",
                         valid_from=1),
                    gold(pred, _etype(entity_arg), entity_id, read_value,
                         strength="OBSERVED", call_id="c2", json_path="$.status",
                         valid_from=3),
                ],
                temporal=[tq("LATEST", _etype(entity_arg), entity_id, pred, read_value)],
                contradicted=[],
                read_tools=[read_tool],
                notes="read wins; self-report invalidated at 3")


def fam_wrong_entity(domain, tools, cat_prefix, mut_tool, entity_arg,
                     called_id, result_id):
    """Call for entity A, result echoes entity B: entity binding fails for
    BOTH — honest UNKNOWN everywhere (pairing integrity, §20)."""
    traj = [
        call(0, "c1", mut_tool, {entity_arg: called_id}),
        result(1, "c1", mut_tool, {entity_arg: result_id, "status": "cancelled"}),
    ]
    et = _etype(entity_arg)
    return case(cat_prefix, "wrong_entity", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(f"{et}.status", et, called_id),
                             neg(f"{et}.status", et, result_id)],
                notes="entity mismatch between call and result: all facts UNKNOWN")


def fam_wrong_field(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id):
    """status-like value lives in `last_operation`, not `status`."""
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, {"entity_ref": entity_id, "last_operation": "cancel",
                                    "operation_log": [{"seq": 1}]}),
    ]
    return case(cat_prefix, "wrong_field", domain, tools, traj,
                gold_facts=[gold(f"{_etype(entity_arg)}.last_operation", _etype(entity_arg),
                                 entity_id, '"cancel"', strength="EXECUTED",
                                 call_id="c1", json_path="$.last_operation")],
                unsupported=[neg(f"{_etype(entity_arg)}.status", _etype(entity_arg), entity_id)])


def fam_stale_state(domain, tools, cat_prefix, read_tool, mut_tool, entity_arg,
                    entity_id, v1, v2):
    traj = [
        call(0, "c1", read_tool, {entity_arg: entity_id}),
        result(1, "c1", read_tool, {entity_arg: entity_id, "status": v1, "tier": "standard"}),
        call(2, "c2", mut_tool, {entity_arg: entity_id}),
        result(3, "c2", mut_tool, {"status": v2, entity_arg: entity_id}),
        call(4, "c3", read_tool, {entity_arg: entity_id}),
        result(5, "c3", read_tool, {entity_arg: entity_id, "status": v2, "tier": "standard"}),
    ]
    pred = f"{_etype(entity_arg)}.status"
    return case(cat_prefix, "stale_state", domain, tools, traj,
                gold_facts=[
                    gold(pred, _etype(entity_arg), entity_id, f'"{v1}"',
                         strength="OBSERVED", call_id="c1", json_path="$.status"),
                    gold(pred, _etype(entity_arg), entity_id, f'"{v2}"',
                         strength="EXECUTED", call_id="c2", json_path="$.status"),
                    gold(pred, _etype(entity_arg), entity_id, f'"{v2}"',
                         strength="OBSERVED", call_id="c3", json_path="$.status"),
                ],
                temporal=[
                    tq("LATEST", _etype(entity_arg), entity_id, pred, f'"{v2}"'),
                    tq("PRIOR_TRUE", _etype(entity_arg), entity_id, pred, "TRUE",
                       as_of=2, value=f'"{v1}"'),
                    tq("AT_TIME", _etype(entity_arg), entity_id, pred, f'"{v1}"', as_of=1),
                    tq("AT_TIME", _etype(entity_arg), entity_id, pred, f'"{v2}"', as_of=3),
                ],
                read_tools=[read_tool],
                notes="ever_true != currently_true")


def fam_repeated_mutation(domain, tools, cat_prefix, mut_tool, entity_arg,
                          entity_id, payload, pred, value_json):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, payload),
        call(2, "c2", mut_tool, {entity_arg: entity_id}),
        result(3, "c2", mut_tool, payload),
    ]
    return case(cat_prefix, "repeated_mutation", domain, tools, traj,
                gold_facts=[gold(pred, _etype(entity_arg), entity_id, value_json,
                                 strength="EXECUTED", call_id="c1", json_path="$.status")],
                temporal=[tq("LATEST", _etype(entity_arg), entity_id, pred, value_json)])


def fam_conflicting_observations(domain, tools, cat_prefix, read_tool, entity_arg,
                                 entity_id, v1, v2):
    traj = [
        call(0, "c1", read_tool, {entity_arg: entity_id}),
        result(1, "c1", read_tool, {entity_arg: entity_id, "status": v1}),
        call(2, "c2", read_tool, {entity_arg: entity_id}),
        result(3, "c2", read_tool, {entity_arg: entity_id, "status": v2}),
    ]
    pred = f"{_etype(entity_arg)}.status"
    return case(cat_prefix, "conflicting_observations", domain, tools, traj,
                gold_facts=[
                    gold(pred, _etype(entity_arg), entity_id, f'"{v1}"',
                         strength="OBSERVED", call_id="c1", json_path="$.status"),
                    gold(pred, _etype(entity_arg), entity_id, f'"{v2}"',
                         strength="OBSERVED", call_id="c2", json_path="$.status"),
                ],
                temporal=[tq("LATEST", _etype(entity_arg), entity_id, pred, f'"{v2}"')],
                read_tools=[read_tool],
                notes="conflict visible; latest observation wins, history retained")


def fam_malformed_result(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id,
                         business_pred):
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, None, raw="processing… (no JSON returned)"),
    ]
    return case(cat_prefix, "malformed_result", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(business_pred, _etype(entity_arg), entity_id)])


def fam_misleading_names(domain, tools, cat_prefix, entity_arg, entity_id):
    """replace_device that only CREATES A REQUEST; audit_device that MUTATES."""
    tools2 = [
        tool("replace_device", "Create a replacement request for a device (does not itself replace anything).",
             {"device_id": f()}),
        tool("audit_device", "Write an audit record for a device and mark it inspected.",
             {"device_id": f()}),
    ]
    traj = [
        call(0, "c1", "replace_device", {entity_arg: entity_id}),
        result(1, "c1", "replace_device", {"request_id": "rep-202", "status": "created",
                                            entity_arg: entity_id}),
        call(2, "c2", "audit_device", {entity_arg: entity_id}),
        result(3, "c2", "audit_device", {"success": True, "inspected": True,
                                          "status": "inspected", entity_arg: entity_id}),
    ]
    et = _etype(entity_arg)
    return case(cat_prefix, "misleading_tool_name", domain, tools2, traj,
                gold_facts=[
                    gold(f"{et}.replacement_request.status", et, entity_id,
                         '"created"', strength="REQUESTED", call_id="c1",
                         json_path="$.status"),
                    gold(f"{et}.status", et, entity_id, '"inspected"',
                         strength="EXECUTED", call_id="c2", json_path="$.status"),
                ],
                unsupported=[neg(f"{et}.replaced", et, entity_id)],
                notes="names lie: replace=request-only, audit=mutation")


def fam_renamed_ids(domain, tools, cat_prefix, entity_arg, entity_id):
    """Opaque tool identifiers; pairing must survive without semantic names."""
    tools2 = [
        tool("tool_x14", "Cancel the whole order.", {"order_id": f()}),
        tool("tool_q7", "Get the details of an order.", {"order_id": f()}),
    ]
    traj = [
        call(0, "c1", "tool_q7", {entity_arg: entity_id}),
        result(1, "c1", "tool_q7", {entity_arg: entity_id, "status": "pending"}),
        call(2, "c2", "tool_x14", {entity_arg: entity_id}),
        result(3, "c2", "tool_x14", {entity_arg: entity_id, "status": "cancelled"}),
    ]
    pred = f"{_etype(entity_arg)}.status"
    return case(cat_prefix, "renamed_tool_ids", domain, tools2, traj,
                gold_facts=[
                    gold(pred, _etype(entity_arg), entity_id, '"pending"',
                         strength="OBSERVED", call_id="c1", json_path="$.status"),
                    gold(pred, _etype(entity_arg), entity_id, '"cancelled"',
                         strength="EXECUTED", call_id="c2", json_path="$.status"),
                ],
                read_tools=["tool_q7"],
                notes="opaque names must not change verdicts")


def fam_result_no_echo(domain, tools, cat_prefix, mut_tool, entity_arg, entity_id):
    """Mutation result with business state but NO entity echo: entity binding
    must fail -> facts stay UNKNOWN (no guessing which entity)."""
    traj = [
        call(0, "c1", mut_tool, {entity_arg: entity_id}),
        result(1, "c1", mut_tool, {"status": "cancelled"}),
    ]
    return case(cat_prefix, "result_no_echo", domain, tools, traj,
                gold_facts=[],
                unsupported=[neg(f"{_etype(entity_arg)}.status", _etype(entity_arg), entity_id)],
                notes="no entity echo: honest UNKNOWN, entity unbound")


def fam_same_result_diff_contract(domain, tools, cat_prefix, entity_arg, entity_id):
    """Same result payload under a read contract vs mutation contract (§26)."""
    tools2 = [
        tool("get_case_state", "Get the current state of a support case.", {"case_id": f()}),
        tool("set_case_state", "Set the state of a support case.", {"case_id": f(), "state": f()}),
    ]
    payload = {"case_id": entity_id, "status": "escalated"}
    traj = [
        call(0, "c1", "get_case_state", {entity_arg: entity_id}),
        result(1, "c1", "get_case_state", payload),
        call(2, "c2", "set_case_state", {entity_arg: entity_id, "state": "escalated"}),
        result(3, "c2", "set_case_state", payload),
    ]
    contracts = {
        "set_case_state": {
            "effect_class": "UPDATE", "entity_field": "case_id", "entity_type": "case",
            "result_bindings": {"case_id": "$.case_id"},
            "documented_contract": True,
            "postconditions": [
                {"predicate": "case.status", "json_path": "$.status",
                 "value_json": '"escalated"', "strength": "EXECUTED"},
            ],
        },
        "get_case_state": {
            "effect_class": "READ", "entity_field": "case_id", "entity_type": "case",
            "result_bindings": {"case_id": "$.case_id"},
            "observe_fields": [
                {"predicate": "case.status", "json_path": "$.status",
                 "value_json": '"escalated"'},
            ],
        },
    }
    return case(cat_prefix, "same_result_diff_contract", domain, tools2, traj,
                gold_facts=[
                    gold("case.status", "case", entity_id, '"escalated"',
                         strength="OBSERVED", call_id="c1", json_path="$.status"),
                    gold("case.status", "case", entity_id, '"escalated"',
                         strength="EXECUTED", call_id="c2", json_path="$.status"),
                ],
                contracts=contracts,
                read_tools=["get_case_state"],
                notes="same payload, different contract -> different strength")


def fam_same_desc_diff_output(domain, tools, cat_prefix, entity_arg, entity_id):
    """Same description, different output schema (§26): one tool's result
    carries status, the other only ack. Two DIFFERENT records so the
    unsupported fact is a distinct triple."""
    tools2 = [
        tool("archive_record_A", "Archive the record.", {"record_id": f()}),
        tool("archive_record_B", "Archive the record.", {"record_id": f()}),
    ]
    other_id = entity_id + "-2"
    traj = [
        call(0, "c1", "archive_record_A", {entity_arg: entity_id}),
        result(1, "c1", "archive_record_A", {"success": True}),
        call(2, "c2", "archive_record_B", {entity_arg: other_id}),
        result(3, "c2", "archive_record_B", {"record_id": other_id, "status": "archived"}),
    ]
    et = _etype(entity_arg)
    return case(cat_prefix, "same_desc_diff_output", domain, tools2, traj,
                gold_facts=[
                    gold(f"{et}.status", et, other_id, '"archived"',
                         strength="EXECUTED", call_id="c2", json_path="$.status"),
                ],
                unsupported=[neg(f"{et}.status", et, entity_id)],
                notes="identical descriptions; only the result distinguishes them")


# ================================================================== assemble ==

ASYNC_VALUES_LC = {"queued", "queue", "processing", "pending", "scheduled",
                   "accepted", "submitted", "in_progress", "started",
                   "initiated", "created", "requested", "received"}


def _classify(payload):
    if not isinstance(payload, dict) or not payload:
        return "EMPTY"
    if any(k in payload for k in ("error", "error_message", "error_code")):
        return "FAILURE"
    has_async = any(isinstance(payload.get(k), str) and payload[k].lower() in ASYNC_VALUES_LC
                    for k in ("status", "new_status", "state", "new_state"))
    has_request = any(k in payload for k in ("request_id", "job_id", "task_id", "ticket_id"))
    if has_async or (has_request and "status" not in payload):
        return "ASYNC_ACCEPTED"
    if any(k in payload for k in ("status", "new_status", "state", "new_state")):
        return "BUSINESS_STATE"
    if any(k in payload for k in ("success", "ok", "acknowledged")):
        return "SUCCESS_ACK"
    return "OBSERVATION"


def add_structural_gold(c: dict) -> dict:
    """Reference structural extraction with TRUE strengths, merged into gold.

    This records what a *perfect* structure-only extractor with correct
    read/mutation knowledge could prove: top-level scalar report fields with
    entity echo binding. Deterministic arms are scored against these; the
    semantic gold facts above measure the extra contract/LLM gap.
    """
    read_tools = set(c.pop("_read_tools", []))
    calls = {ev["call_id"]: ev for ev in c["trajectory"] if ev["kind"] == "call"}
    existing = {(g["predicate"], str(g["entity_id"]), str(g["value"]))
                for g in c["gold_facts"]}
    for ev in c["trajectory"]:
        if ev["kind"] != "result" or not isinstance(ev.get("payload"), dict):
            continue
        call_ev = calls.get(ev["call_id"])
        if call_ev is None or call_ev["tool"] not in read_tools and call_ev["tool"] not in {t["name"] for t in c["tools"]}:
            continue
        payload = ev["payload"]
        # entity echo binding (same rule as the arms)
        entity_field, entity_id = None, None
        for arg_name, arg_value in (call_ev.get("payload") or {}).items():
            if isinstance(arg_value, str) and arg_name.endswith("_id") \
                    and any(v == arg_value for v in _iter_strings(payload)):
                if entity_field is None or len(arg_name) > len(entity_field):
                    entity_field, entity_id = arg_name, arg_value
        if entity_field is None:
            continue
        et = _etype(entity_field)
        rtype = _classify(payload)
        if rtype in ("EMPTY", "FAILURE", "SUCCESS_ACK"):
            continue
        for key, value in payload.items():
            if not isinstance(value, (str, int, float, bool)) or value is None:
                continue
            if str(value) == entity_id:
                continue  # echo restatement
            rendered = json.dumps(value, ensure_ascii=False)
            if rtype == "ASYNC_ACCEPTED":
                strength = "REQUESTED"
            elif call_ev["tool"] in read_tools:
                strength = "OBSERVED"
            else:
                strength = "EXECUTED"
            entry = (f"{et}.{key}", entity_id, rendered)
            if entry in existing:
                continue
            c["gold_facts"].append(gold(f"{et}.{key}", et, entity_id, rendered,
                                        strength=strength,
                                        call_id=ev["call_id"], json_path=f"$.{key}"))
            existing.add(entry)
    return c


def _iter_strings(payload, depth=0):
    if depth > 3:
        return
    if isinstance(payload, dict):
        for value in payload.values():
            if isinstance(value, str):
                yield value
            else:
                yield from _iter_strings(value, depth + 1)
    elif isinstance(payload, list):
        for value in payload[:8]:
            if isinstance(value, str):
                yield value
            else:
                yield from _iter_strings(value, depth + 1)

def build_all() -> list[dict]:
    cases: list[dict] = []
    R, A, T, B, S, I = (RETAIL_TOOLS, AIRLINE_TOOLS, TELECOM_TOOLS,
                        BANKING_TOOLS, SHIPPING_TOOLS, INSURANCE_TOOLS)

    # --- reads with explicit status (2 domains)
    cases.append(fam_read_status("retail", R, "retail_read_001", "get_order_details",
                                 "order_id", "#9001",
                                 {"order_id": "#9001", "status": "pending",
                                  "items": [{"id": "item_1", "qty": 2}]}, "pending"))
    cases.append(fam_read_status("airline", A, "airline_read_001", "get_reservation_details",
                                 "reservation_id", "ZFA04Y",
                                 {"reservation_id": "ZFA04Y", "status": "cancelled",
                                  "flights": [{"id": "FL121"}]}, "cancelled"))

    # --- mutations with explicit post-state (2 domains)
    cases.append(fam_mutation_poststate("retail", R, "retail_post_001", "cancel_order",
                                        "order_id", "#9001",
                                        {"order_id": "#9001", "new_status": "cancelled"},
                                        "order.status", '"cancelled"'))
    cases.append(fam_mutation_poststate("airline", A, "airline_post_001", "cancel_reservation",
                                        "reservation_id", "ZFA04Y",
                                        {"reservation_id": "ZFA04Y", "status": "cancelled"},
                                        "reservation.status", '"cancelled"'))
    cases.append(fam_mutation_poststate("telecom", T, "telecom_post_001", "resume_line",
                                        "line_id", "LN-77",
                                        {"line_id": "LN-77", "status": "active"},
                                        "line.status", '"active"'))

    # --- generic success only (3 domains) — hard negative core
    cases.append(fam_generic_success("retail", R, "retail_gso_001", "cancel_order",
                                     "order_id", "#9001", "order.cancelled"))
    cases.append(fam_generic_success("banking", B, "banking_gso_001", "close_account",
                                     "account_id", "ACC-33", "account.closed"))
    cases.append(fam_generic_success("insurance", I, "insurance_gso_001", "cancel_policy",
                                     "policy_id", "POL-9", "policy.cancelled"))
    cases.append(fam_generic_success("shipping", S, "shipping_gso_001", "dispatch_parcel",
                                     "parcel_id", "PK-512", "parcel.dispatched"))

    # --- async accepted
    cases.append(fam_async_accepted("retail", R, "retail_async_001", "return_delivered_order_items",
                                    "order_id", "#9002",
                                    {"order_id": "#9002", "status": "queued",
                                     "return_id": "r-31"},
                                    "order.return.status", '"queued"'))
    cases.append(fam_async_accepted("shipping", S, "shipping_async_001", "dispatch_parcel",
                                    "parcel_id", "PK-513",
                                    {"parcel_id": "PK-513", "status": "scheduled",
                                     "carrier_ticket": "CT-9"},
                                    "parcel.dispatch.status", '"scheduled"'))

    # --- request creation != operation completed
    cases.append(fam_request_creation("retail", R, "retail_req_001",
                                      "exchange_delivered_order_items", "order_id", "#9003",
                                      {"request_id": "ex-17", "order_id": "#9003",
                                       "status": "created"},
                                      "order.exchange.status", '"created"'))
    cases.append(fam_request_creation("airline", A, "airline_req_001", "request_refund",
                                      "reservation_id", "ZFA04Y",
                                      {"request_id": "rf-88", "reservation_id": "ZFA04Y",
                                       "status": "created"},
                                      "reservation.refund.status", '"created"'))
    cases.append(fam_request_creation("banking", B, "banking_req_001", "issue_card",
                                      "account_id", "ACC-33",
                                      {"request_id": "ci-05", "account_id": "ACC-33",
                                       "status": "created"},
                                      "account.card_request.status", '"created"'))

    # --- audit logging (3 domains)
    cases.append(fam_audit_logging("retail", R, "retail_audit_001", "audit_order_action",
                                   "cancel_order", "order_id", "#9001", "order.cancelled"))
    cases.append(fam_audit_logging("telecom", T, "telecom_audit_001", "write_device_audit",
                                   "record_device_replacement", "device_id", "DEV-17",
                                   "device.replaced"))
    cases.append(fam_audit_logging("shipping", S, "shipping_audit_001", "scan_note",
                                   "dispatch_parcel", "parcel_id", "PK-512",
                                   "parcel.dispatched"))

    # --- notification
    cases.append(fam_notification("retail", R, "retail_notify_001", "notify_customer",
                                  "user_id", "usr_77", "order.cancelled"))
    cases.append(fam_notification("insurance", I, "insurance_notify_001", "send_policy_notice",
                                  "policy_id", "POL-9", "policy.cancelled"))

    # --- mutation failure
    cases.append(fam_mutation_failure("retail", R, "retail_fail_001", "cancel_order",
                                      "order_id", "#9004", "order.cancelled"))
    cases.append(fam_mutation_failure("telecom", T, "telecom_fail_001", "suspend_line",
                                       "line_id", "LN-77", "line.suspended"))

    # --- partial result
    cases.append(fam_partial_result("retail", R, "retail_partial_001",
                                    "exchange_delivered_order_items", "order_id", "#9005"))

    # --- later confirmation / contradiction
    cases.append(fam_later_confirmation(
        "retail", R, "retail_conf_001", "cancel_order", "get_order_details",
        "order_id", "#9006", {"order_id": "#9006", "status": "cancelled"},
        {"order_id": "#9006", "status": "cancelled", "items": []},
        "order.status", '"cancelled"'))
    cases.append(fam_later_confirmation(
        "telecom", T, "telecom_conf_001", "resume_line", "get_line_details",
        "line_id", "LN-78", {"line_id": "LN-78", "status": "active"},
        {"line_id": "LN-78", "status": "active", "plan": "unlimited"},
        "line.status", '"active"'))
    cases.append(fam_later_contradiction(
        "retail", R, "retail_contra_001", "cancel_order", "get_order_details",
        "order_id", "#9007", {"order_id": "#9007", "status": "cancelled"},
        {"order_id": "#9007", "status": "pending", "items": []},
        "order.status", '"cancelled"', '"pending"'))
    cases.append(fam_later_contradiction(
        "airline", A, "airline_contra_001", "cancel_reservation", "get_reservation_details",
        "reservation_id", "ZFA04Y", {"reservation_id": "ZFA04Y", "status": "cancelled"},
        {"reservation_id": "ZFA04Y", "status": "confirmed", "flights": []},
        "reservation.status", '"cancelled"', '"confirmed"'))

    # --- wrong entity / wrong field / no echo
    cases.append(fam_wrong_entity("retail", R, "retail_went_001", "cancel_order",
                                  "order_id", "#9001", "#9002"))
    cases.append(fam_wrong_field("banking", B, "banking_wfld_001", "close_account",
                                 "account_id", "ACC-33"))
    cases.append(fam_result_no_echo("retail", R, "retail_noecho_001", "cancel_order",
                                    "order_id", "#9008"))

    # --- stale state / repeated / conflicting
    cases.append(fam_stale_state("airline", A, "airline_stale_001", "get_reservation_details",
                                 "cancel_reservation", "reservation_id", "ZFA04Y",
                                 "pending", "cancelled"))
    cases.append(fam_stale_state("banking", B, "banking_stale_001", "get_account_details",
                                 "close_account", "account_id", "ACC-33",
                                 "open", "closed"))
    cases.append(fam_repeated_mutation("retail", R, "retail_repeat_001", "cancel_order",
                                       "order_id", "#9009",
                                       {"order_id": "#9009", "status": "cancelled"},
                                       "order.status", '"cancelled"'))
    cases.append(fam_conflicting_observations("shipping", S, "shipping_confobs_001",
                                              "get_parcel_status", "parcel_id", "PK-514",
                                              "in_transit", "delivered"))
    cases.append(fam_conflicting_observations("insurance", I, "insurance_confobs_001",
                                              "get_policy_details", "policy_id", "POL-9",
                                              "active", "cancelled"))

    # --- malformed
    cases.append(fam_malformed_result("telecom", T, "telecom_mal_001", "resume_line",
                                      "line_id", "LN-79", "line.status"))
    cases.append(fam_malformed_result("shipping", S, "shipping_mal_001", "dispatch_parcel",
                                      "parcel_id", "PK-515", "parcel.dispatched"))

    # --- misleading names / renamed ids / contract contrasts
    cases.append(fam_misleading_names("telecom", T, "telecom_mislead_001", "device_id", "DEV-17"))
    cases.append(fam_renamed_ids("retail", R, "retail_renid_001", "order_id", "#9010"))
    cases.append(fam_same_result_diff_contract("generic", [], "generic_srdc_001",
                                               "case_id", "CS-408"))
    cases.append(fam_same_desc_diff_output("generic", [], "generic_sddo_001",
                                           "record_id", "REC-1"))

    # --- breadth variants: same categories across more domains/entities
    cases.append(fam_read_status("telecom", T, "telecom_read_001", "get_line_details",
                                 "line_id", "LN-80",
                                 {"line_id": "LN-80", "status": "suspended",
                                  "plan": "basic"}, "suspended"))
    cases.append(fam_read_status("banking", B, "banking_read_001", "get_account_details",
                                 "account_id", "ACC-40",
                                 {"account_id": "ACC-40", "status": "open",
                                  "balance": 120}, "open"))
    cases.append(fam_mutation_poststate("insurance", I, "insurance_post_001", "cancel_policy",
                                        "policy_id", "POL-21",
                                        {"policy_id": "POL-21", "status": "cancelled"},
                                        "policy.status", '"cancelled"'))
    cases.append(fam_mutation_poststate("banking", B, "banking_post_001", "block_card",
                                        "card_id", "CD-77",
                                        {"card_id": "CD-77", "status": "blocked"},
                                        "card.status", '"blocked"'))
    cases.append(fam_generic_success("airline", A, "airline_gso_001", "cancel_reservation",
                                     "reservation_id", "ZFA04Y", "reservation.cancelled"))
    cases.append(fam_generic_success("telecom", T, "telecom_gso_001", "suspend_line",
                                     "line_id", "LN-81", "line.suspended"))
    cases.append(fam_async_accepted("telecom", T, "telecom_async_001", "schedule_line_change",
                                    "line_id", "LN-82",
                                    {"line_id": "LN-82", "status": "scheduled",
                                     "change_ticket": "tc-4"},
                                    "line.change.status", '"scheduled"'))
    cases.append(fam_async_accepted("banking", B, "banking_async_001", "issue_card",
                                    "account_id", "ACC-41",
                                    {"account_id": "ACC-41", "status": "processing",
                                     "request_ref": "pr-9"},
                                    "account.card.status", '"processing"'))
    cases.append(fam_request_creation("insurance", I, "insurance_req_001", "file_claim",
                                      "policy_id", "POL-22",
                                      {"claim_id": "cl-31", "policy_id": "POL-22",
                                       "status": "created"},
                                      "policy.claim.status", '"created"'))
    cases.append(fam_audit_logging("airline", A, "airline_audit_001", "log_assistance",
                                   "cancel_reservation", "reservation_id", "ZFA04Y",
                                   "reservation.cancelled",
                                   audit_payload={"success": True, "log_id": "lg-77"}))
    cases.append(fam_audit_logging("banking", B, "banking_audit_001", "record_complaint",
                                   "close_account", "account_id", "ACC-42",
                                   "account.closed",
                                   audit_payload={"success": True, "record_id": "rc-19"}))
    cases.append(fam_mutation_failure("airline", A, "airline_fail_001", "cancel_reservation",
                                      "reservation_id", "ZFA04Y", "reservation.cancelled"))
    cases.append(fam_mutation_failure("insurance", I, "insurance_fail_001", "cancel_policy",
                                      "policy_id", "POL-23", "policy.cancelled"))
    cases.append(fam_partial_result("banking", B, "banking_partial_001", "close_account",
                                    "account_id", "ACC-43"))
    cases.append(fam_later_confirmation(
        "airline", A, "airline_conf_001", "cancel_reservation", "get_reservation_details",
        "reservation_id", "ZFW11X", {"reservation_id": "ZFW11X", "status": "cancelled"},
        {"reservation_id": "ZFW11X", "status": "cancelled", "flights": []},
        "reservation.status", '"cancelled"'))
    cases.append(fam_later_confirmation(
        "banking", B, "banking_conf_001", "close_account", "get_account_details",
        "account_id", "ACC-44", {"account_id": "ACC-44", "status": "closed"},
        {"account_id": "ACC-44", "status": "closed", "balance": 0},
        "account.status", '"closed"'))
    cases.append(fam_later_contradiction(
        "telecom", T, "telecom_contra_001", "resume_line", "get_line_details",
        "line_id", "LN-83", {"line_id": "LN-83", "status": "active"},
        {"line_id": "LN-83", "status": "suspended", "plan": "basic"},
        "line.status", '"active"', '"suspended"'))
    cases.append(fam_later_contradiction(
        "banking", B, "banking_contra_001", "close_account", "get_account_details",
        "account_id", "ACC-45", {"account_id": "ACC-45", "status": "closed"},
        {"account_id": "ACC-45", "status": "open", "balance": 10},
        "account.status", '"closed"', '"open"'))
    cases.append(fam_wrong_entity("airline", A, "airline_went_001", "cancel_reservation",
                                  "reservation_id", "ZFA04Y", "ZFA04Z"))
    cases.append(fam_wrong_entity("telecom", T, "telecom_went_001", "suspend_line",
                                  "line_id", "LN-84", "LN-85"))
    cases.append(fam_wrong_field("retail", R, "retail_wfld_001", "cancel_order",
                                 "order_id", "#9011"))
    cases.append(fam_result_no_echo("airline", A, "airline_noecho_001", "cancel_reservation",
                                    "reservation_id", "ZFA04Y"))
    cases.append(fam_stale_state("telecom", T, "telecom_stale_001", "get_line_details",
                                 "suspend_line", "line_id", "LN-86",
                                 "active", "suspended"))
    cases.append(fam_stale_state("shipping", S, "shipping_stale_001", "get_parcel_status",
                                 "dispatch_parcel", "parcel_id", "PK-516",
                                 "in_warehouse", "in_transit"))
    cases.append(fam_repeated_mutation("airline", A, "airline_repeat_001", "cancel_reservation",
                                       "reservation_id", "ZFA04Y",
                                       {"reservation_id": "ZFA04Y", "status": "cancelled"},
                                       "reservation.status", '"cancelled"'))
    cases.append(fam_repeated_mutation("banking", B, "banking_repeat_001", "block_card",
                                       "card_id", "CD-78",
                                       {"card_id": "CD-78", "status": "blocked"},
                                       "card.status", '"blocked"'))
    cases.append(fam_conflicting_observations("airline", A, "airline_confobs_001",
                                              "get_reservation_details", "reservation_id",
                                              "ZFA04Y", "pending", "cancelled"))
    cases.append(fam_conflicting_observations("telecom", T, "telecom_confobs_001",
                                              "get_line_details", "line_id", "LN-87",
                                              "active", "suspended"))
    cases.append(fam_malformed_result("retail", R, "retail_mal_001", "cancel_order",
                                      "order_id", "#9012", "order.cancelled"))
    cases.append(fam_malformed_result("banking", B, "banking_mal_001", "close_account",
                                      "account_id", "ACC-46", "account.closed"))
    cases.append(fam_renamed_ids("telecom", T, "telecom_renid_001", "line_id", "LN-88"))
    cases.append(fam_same_result_diff_contract("generic", [], "generic_srdc_002",
                                               "case_id", "CS-409"))
    cases.append(fam_same_desc_diff_output("generic", [], "generic_sddo_002",
                                           "record_id", "REC-2"))
    return [add_structural_gold(c) for c in cases]


# ---------------------------------------------------- oracle contracts (I arm) -

def attach_oracle_contracts(cases: list[dict]) -> list[dict]:
    """ORACLE track: add documented contracts mirroring tool semantics.

    Only tools whose catalog description documents their effect get a
    contract; vague descriptions stay contract-poor (§23).
    """
    contracts = {
        "retail": {
            "cancel_order": {"effect_class": "UPDATE", "entity_field": "order_id",
                             "entity_type": "order",
                             "result_bindings": {"order_id": "$.order_id"},
                             "documented_contract": True,
                             "postconditions": [
                                 {"predicate": "order.status", "json_path": "$.new_status",
                                  "value_json": '"cancelled"', "strength": "EXECUTED"},
                                 {"predicate": "order.status", "json_path": "$.status",
                                  "value_json": '"cancelled"', "strength": "EXECUTED"}]},
            "get_order_details": {"effect_class": "READ", "entity_field": "order_id",
                                  "entity_type": "order",
                                  "result_bindings": {"order_id": "$.order_id"},
                                  "observe_fields": [
                                      {"predicate": "order.status", "json_path": "$.status",
                                       "value_json": None}]},
            "exchange_delivered_order_items": {
                "effect_class": "REQUEST", "entity_field": "order_id", "entity_type": "order",
                "result_bindings": {"order_id": "$.order_id"},
                "postconditions": [
                    {"predicate": "order.exchange.status", "json_path": "$.status",
                     "value_json": '"created"', "strength": "REQUESTED"},
                    {"predicate": "order.return.status", "json_path": "$.status",
                     "value_json": '"queued"', "strength": "REQUESTED"}]},
        },
        "airline": {
            "cancel_reservation": {"effect_class": "UPDATE", "entity_field": "reservation_id",
                                   "entity_type": "reservation",
                                   "result_bindings": {"reservation_id": "$.reservation_id"},
                                   "documented_contract": True,
                                   "postconditions": [
                                       {"predicate": "reservation.status", "json_path": "$.status",
                                        "value_json": '"cancelled"', "strength": "EXECUTED"}]},
            "get_reservation_details": {"effect_class": "READ", "entity_field": "reservation_id",
                                        "entity_type": "reservation",
                                        "result_bindings": {"reservation_id": "$.reservation_id"},
                                        "observe_fields": [
                                            {"predicate": "reservation.status", "json_path": "$.status",
                                             "value_json": None}]},
            "request_refund": {"effect_class": "REQUEST", "entity_field": "reservation_id",
                               "entity_type": "reservation",
                               "result_bindings": {"reservation_id": "$.reservation_id"},
                               "postconditions": [
                                   {"predicate": "reservation.refund.status", "json_path": "$.status",
                                    "value_json": '"created"', "strength": "REQUESTED"}]},
        },
        "telecom": {
            "resume_line": {"effect_class": "UPDATE", "entity_field": "line_id",
                            "entity_type": "line",
                            "result_bindings": {"line_id": "$.line_id"},
                            "documented_contract": True,
                            "postconditions": [
                                {"predicate": "line.status", "json_path": "$.status",
                                 "value_json": '"active"', "strength": "EXECUTED"}]},
            "get_line_details": {"effect_class": "READ", "entity_field": "line_id",
                                 "entity_type": "line",
                                 "result_bindings": {"line_id": "$.line_id"},
                                 "observe_fields": [
                                     {"predicate": "line.status", "json_path": "$.status",
                                      "value_json": None}]},
        },
        "banking": {
            "close_account": {"effect_class": "UPDATE", "entity_field": "account_id",
                              "entity_type": "account",
                              "result_bindings": {"account_id": "$.account_id"},
                              "documented_contract": True,
                              "postconditions": [
                                  {"predicate": "account.status", "json_path": "$.status",
                                   "value_json": '"closed"', "strength": "EXECUTED"}]},
            "get_account_details": {"effect_class": "READ", "entity_field": "account_id",
                                    "entity_type": "account",
                                    "result_bindings": {"account_id": "$.account_id"},
                                    "observe_fields": [
                                        {"predicate": "account.status", "json_path": "$.status",
                                         "value_json": None}]},
        },
        "shipping": {
            "get_parcel_status": {"effect_class": "READ", "entity_field": "parcel_id",
                                   "entity_type": "parcel",
                                   "result_bindings": {"parcel_id": "$.parcel_id"},
                                   "observe_fields": [
                                       {"predicate": "parcel.status", "json_path": "$.status",
                                        "value_json": None}]},
            "dispatch_parcel": {"effect_class": "ATTEMPT", "entity_field": "parcel_id",
                                 "entity_type": "parcel",
                                 "result_bindings": {"parcel_id": "$.parcel_id"},
                                 "postconditions": [
                                     {"predicate": "parcel.dispatch.status", "json_path": "$.status",
                                      "value_json": '"scheduled"', "strength": "REQUESTED"}]},
        },
        "insurance": {
            "get_policy_details": {"effect_class": "READ", "entity_field": "policy_id",
                                    "entity_type": "policy",
                                    "result_bindings": {"policy_id": "$.policy_id"},
                                    "observe_fields": [
                                        {"predicate": "policy.status", "json_path": "$.status",
                                         "value_json": None}]},
            "cancel_policy": {"effect_class": "UPDATE", "entity_field": "policy_id",
                               "entity_type": "policy",
                               "result_bindings": {"policy_id": "$.policy_id"},
                               "documented_contract": True,
                               "postconditions": [
                                   {"predicate": "policy.status", "json_path": "$.status",
                                    "value_json": '"cancelled"', "strength": "EXECUTED"}]},
            "file_claim": {"effect_class": "REQUEST", "entity_field": "policy_id",
                            "entity_type": "policy",
                            "result_bindings": {"policy_id": "$.policy_id"},
                            "postconditions": [
                                {"predicate": "policy.claim.status", "json_path": "$.status",
                                 "value_json": '"created"', "strength": "REQUESTED"}]},
        },
    }
    out = []
    for c in cases:
        c = json.loads(json.dumps(c))  # deep copy
        domain = c["domain"]
        if domain in contracts:
            c["oracle_contracts"] = json.loads(json.dumps(contracts.get(domain, {})))
        out.append(c)
    return out


# ------------------------------------------------------- derived suites (CF) --

def make_counterfactuals(cases: list[dict]) -> list[dict]:
    """Flip exactly one evidence source per case; gold flips with it (§35)."""
    out = []
    for c in cases:
        if c["category"] not in ("mutation_poststate", "read_explicit_status",
                                 "later_confirmation", "async_accepted",
                                 "request_creation"):
            continue
        cf = json.loads(json.dumps(c))
        cf["case_id"] = c["case_id"] + "::CF"
        flipped = False
        for ev in cf["trajectory"]:
            if ev["kind"] != "result" or not isinstance(ev.get("payload"), dict):
                continue
            payload = ev["payload"]
            if "status" in payload and isinstance(payload["status"], str) \
                    and payload["status"] in ("cancelled", "active", "created", "queued",
                                              "pending", "archived", "scheduled"):
                old = payload["status"]
                new = {"cancelled": "pending", "active": "suspended", "created": "rejected",
                       "queued": "aborted", "pending": "cancelled", "archived": "active",
                       "scheduled": "cancelled"}.get(old, "pending")
                payload["status"] = new
                flipped = True
        if not flipped:
            continue
        # flip gold values to the new status where predicate covers status
        for g in cf["gold_facts"]:
            if g["predicate"].endswith(".status") or g["predicate"].endswith("status"):
                try:
                    value = json.loads(g["value"])
                except (ValueError, TypeError):
                    continue
                if isinstance(value, str) and value in ("cancelled", "active", "created",
                                                        "queued", "pending", "archived",
                                                        "scheduled"):
                    new = {"cancelled": "pending", "active": "suspended", "created": "rejected",
                           "queued": "aborted", "pending": "cancelled", "archived": "active",
                           "scheduled": "cancelled"}.get(value, "pending")
                    g["value"] = json.dumps(new)
        for q in cf["temporal_queries"]:
            if isinstance(q.get("expected"), str) and q["expected"].startswith('"'):
                try:
                    value = json.loads(q["expected"])
                except (ValueError, TypeError):
                    continue
                if isinstance(value, str) and value in ("cancelled", "active", "created",
                                                        "queued", "pending", "archived",
                                                        "scheduled"):
                    new = {"cancelled": "pending", "active": "suspended", "created": "rejected",
                           "queued": "aborted", "pending": "cancelled", "archived": "active",
                           "scheduled": "cancelled"}.get(value, "pending")
                    q["expected"] = json.dumps(new)
        cf["category"] = c["category"] + "_cf"
        cf["notes"] = (cf.get("notes", "") + " [counterfactual: one status value flipped]")
        out.append(cf)
    return out


def make_entity_counterfactuals(cases: list[dict]) -> list[dict]:
    """Flip the entity id in the CALL only: facts about the original entity
    must disappear (entity grounding, §35)."""
    out = []
    for c in cases:
        if c["category"] != "mutation_poststate":
            continue
        cf = json.loads(json.dumps(c))
        cf["case_id"] = c["case_id"] + "::CFE"
        original = None
        for ev in cf["trajectory"]:
            if ev["kind"] == "call":
                for key, value in list(ev["payload"].items()):
                    if key.endswith("_id") and isinstance(value, str):
                        original = (key, value)
                        ev["payload"][key] = value + "-B"
        if original is None:
            continue
        key, old_value = original
        cf["gold_facts"] = []   # entity unbound for the original id: honest UNKNOWN
        cf["unsupported_candidate_facts"] = [
            {"predicate": g["predicate"], "entity_type": g["entity_type"],
             "entity_id": g["entity_id"], "value": g["value"], "truth": "UNKNOWN"}
            for g in c["gold_facts"]]
        cf["category"] = "mutation_poststate_cfe"
        cf["notes"] = "counterfactual: call entity changed; facts about original must vanish"
        out.append(cf)
    return out


def make_rename_suite(cases: list[dict]) -> list[dict]:
    """Opaque renames + misleading name swaps (§34). Verdicts must survive."""
    rng = random.Random(20260928)
    out = []
    for c in cases:
        if c["category"] in ("same_result_diff_contract", "same_desc_diff_output",
                             "misleading_tool_name", "renamed_tool_ids"):
            continue
        rc = json.loads(json.dumps(c))
        rc["case_id"] = c["case_id"] + "::RN"
        mapping = {}
        for i, t in enumerate(rc["tools"]):
            mapping[t["name"]] = f"tool_{rng.randrange(100, 999)}_{i:02d}"
        for t in rc["tools"]:
            t["name"] = mapping[t["name"]]
            t["description"] = t["description"]  # descriptions unchanged (rename only)
        for ev in rc["trajectory"]:
            if ev["tool"] in mapping:
                ev["tool"] = mapping[ev["tool"]]
        rc["oracle_contracts"] = {}
        rc["category"] = c["category"] + "_rn"
        rc["notes"] = "rename control: opaque tool identifiers, semantics unchanged"
        out.append(rc)
    return out


# ------------------------------------------------------------------- splits ---

def split_cases(cases: list[dict]) -> dict[str, list[dict]]:
    """Deterministic split by category balance: ~55% dev, ~20% calib, ~25% test."""
    rng = random.Random(20260928)
    by_cat: dict[str, list[dict]] = {}
    for c in cases:
        by_cat.setdefault(c["category"], []).append(c)
    dev, calib, test = [], [], []
    for cat in sorted(by_cat):
        group = by_cat[cat]
        rng.shuffle(group)
        n = len(group)
        n_dev = max(1, round(n * 0.55))
        n_calib = max(0 if n == 1 else 1, round(n * 0.2))
        dev.extend(group[:n_dev])
        calib.extend(group[n_dev:n_dev + n_calib])
        test.extend(group[n_dev + n_calib:])
    return {"dev": dev, "calib": calib, "test": test}


def write_split(path: Path, name: str, cases: list[dict]) -> dict:
    path.mkdir(parents=True, exist_ok=True)
    rows = []
    for c in cases:
        row = json.loads(json.dumps(c))
        row["split"] = name
        rows.append(row)
    with open(path / f"{name}.jsonl", "w", encoding="utf-8") as fh:
        for row in rows:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    gold = {row["case_id"]: {
        "gold_facts": row["gold_facts"],
        "unsupported_candidate_facts": row["unsupported_candidate_facts"],
        "contradicted_facts": row["contradicted_facts"],
        "temporal_queries": row["temporal_queries"],
    } for row in rows}
    with open(path / f"{name}.gold.json", "w", encoding="utf-8") as fh:
        json.dump(gold, fh, ensure_ascii=False, indent=1)
    return {"split": name, "cases": len(rows),
            "sha256": _sha(rows),
            "categories": sorted({r["category"] for r in rows})}


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", default="experiments/searh_23/step2_evidence_v1")
    args = ap.parse_args()
    out = Path(args.out)

    base = build_all()
    oracle = attach_oracle_contracts(base)
    splits = split_cases(oracle)
    manifests = {}
    for name, rows in splits.items():
        manifests[name] = write_split(out, name, rows)

    cf = make_counterfactuals(oracle) + make_entity_counterfactuals(oracle)
    with open(out / "cf_suite.jsonl", "w", encoding="utf-8") as fh:
        for row in cf:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifests["cf_suite"] = {"cases": len(cf), "sha256": _sha(cf)}

    ren = make_rename_suite(oracle)
    with open(out / "rename_suite.jsonl", "w", encoding="utf-8") as fh:
        for row in ren:
            fh.write(json.dumps(row, ensure_ascii=False) + "\n")
    manifests["rename_suite"] = {"cases": len(ren), "sha256": _sha(ren)}

    manifest = {
        "dataset": "step2_evidence_v1",
        "built": "2026-09-28",
        "rule": "committed BEFORE any inference; gold sealed by construction",
        "splits": manifests,
        "total_base": len(oracle),
        "categories": sorted({c["category"] for c in oracle}),
        "domains": sorted({c["domain"] for c in oracle}),
        "oracle_track": "contracts present for documented tools only",
    }
    with open(out / "manifest.json", "w", encoding="utf-8") as fh:
        json.dump(manifest, fh, ensure_ascii=False, indent=1)
    print(json.dumps(manifest, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
