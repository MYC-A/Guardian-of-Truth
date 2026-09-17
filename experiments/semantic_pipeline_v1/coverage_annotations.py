"""semantic_pipeline_v1 — Phase 4: human-auditable required-fragment coverage set.

For each audited development failure (label=1) the gold explanation names the
exact source facts a human proof needs.  Each required fragment is expressed as
a MATCHER (role + type/tool/contains/regex/document) resolved deterministically
against the Phase-2 fragment inventory.  Roles:

  RULE      - normative text the proof must apply (policy sentence)
  SCHEMA    - declared tool schema constraining the target call
  STATE     - observed state from a tool result / profile data
  EVIDENCE  - history evidence (user-provided facts, earlier calls/results)
  ACTION    - the target response call/text itself
  REQUEST   - user request constraint
  SYS_RULE  - rule located in SYSTEM instructions (outside <policy>)
  KB_RULE   - normative rule inside a KB/tool-result document

Negative (label=0) cases are annotated by deterministic derivation: target
calls, schemas of the called tools, and policy fragments naming them.
"""

from __future__ import annotations

# role, type, tool(optional), contains(optional, case-insensitive), regex(optional),
# document(optional), last_user(optional bool)
REQUIRED_FRAGMENTS: dict[str, list[dict]] = {
    # ---------------- airline ----------------
    "airline__21::t7": [
        {"role": "RULE", "type": "policy", "contains": "bag"},
        {"role": "RULE", "type": "policy", "contains": "silver"},
        {"role": "RULE", "type": "policy", "regex": r"(confirm|yes)[^.]*(update|chang|modif)|((update|chang|modif)[^.]*(confirm|explicit))", "note": "confirmation-before-update rule"},
        {"role": "STATE", "type": "result", "tool": "get_user_details", "contains": "silver"},
        {"role": "STATE", "type": "result", "contains": "economy"},
        {"role": "STATE", "type": "result", "contains": "gift_card"},
        {"role": "EVIDENCE", "type": "user", "regex": r"(Да|да|подтвержд)", "note": "user confirmation turn"},
        {"role": "ACTION", "type": "response_call", "tool": "update_reservation_baggages"},
    ],
    "airline__23::t10": [
        {"role": "SCHEMA", "type": "schema", "tool": "book_reservation"},
        {"role": "ACTION", "type": "response_call", "tool": "book_reservation"},
        {"role": "EVIDENCE", "type": "result", "contains": "payment_methods", "note": "payment objects from user profile"},
    ],
    "airline__44::t22": [
        {"role": "RULE", "type": "policy", "contains": "API does not check"},
        {"role": "RULE", "type": "policy", "regex": r"cancel[^.]{0,400}(24|business|insuranc)", "note": "cancellation conditions"},
        {"role": "RULE", "type": "policy", "contains": "current time"},
        {"role": "STATE", "type": "result", "contains": "basic_economy"},
        {"role": "STATE", "type": "result", "contains": "KC18K6"},
        {"role": "STATE", "type": "result", "contains": "S61CZX"},
        {"role": "ACTION", "type": "response_call", "tool": "cancel_reservation"},
    ],
    "airline__7::t6": [
        {"role": "RULE", "type": "policy", "contains": "current time"},
        {"role": "STATE", "type": "result", "contains": "A90KR2"},
        {"role": "STATE", "type": "result", "contains": "9MRJD4"},
        {"role": "REQUEST", "type": "last_user"},
        {"role": "ACTION", "type": "response_call", "tool": "calculate"},
    ],
    "airline__8::t7": [
        {"role": "STATE", "type": "result", "tool": "get_user_details", "contains": "dob"},
        {"role": "EVIDENCE", "type": "user", "contains": "sophia", "note": "user names profile owner"},
        {"role": "ACTION", "type": "response_text"},
    ],
    "airline__9::t6": [
        {"role": "RULE", "type": "policy", "regex": r"human agent", "note": "escalation-only-if rule"},
        {"role": "SCHEMA", "type": "description", "tool": "get_flight_status"},
        {"role": "STATE", "type": "result", "regex": r"HAT214|HAT045", "note": "flight numbers and dates in history"},
        {"role": "ACTION", "type": "response_call", "tool": "transfer_to_human_agents"},
    ],
    # ---------------- banking ----------------
    "banking_knowledge__task_003::t7": [
        {"role": "RULE", "type": "policy", "regex": r"transfer_to_human|human agent", "note": "clause 5"},
        {"role": "SCHEMA", "type": "description", "tool": "KB_search_bm25"},
        {"role": "KB_RULE", "type": "result", "contains": "\u0433\u043e\u0434\u043e\u0432", "note": "annual fee lines in KB docs (Russian)"},
        {"role": "EVIDENCE", "type": "call", "contains": "Diamond Elite Card", "note": "the grep pattern used"},
        {"role": "ACTION", "type": "response_call", "tool": "transfer_to_human_agents"},
    ],
    "banking_knowledge__task_005::t6": [
        {"role": "RULE", "type": "policy", "contains": "any 2 out of"},
        {"role": "STATE", "type": "result", "tool": "get_user_information_by_name", "contains": "206-555-0293"},
        {"role": "EVIDENCE", "type": "result", "contains": "No records found", "note": "failed email lookup"},
        {"role": "EVIDENCE", "type": "user", "regex": r"(206-555-0293|нет|не могу)", "note": "user provided only phone"},
        {"role": "ACTION", "type": "response_call", "tool": "log_verification"},
    ],
    "banking_knowledge__task_018::t6": [
        {"role": "RULE", "type": "policy", "regex": r"transfer_to_human|human agent"},
        {"role": "SYS_RULE", "type": "instructions", "contains": "exactly as they appear"},
        {"role": "EVIDENCE", "type": "call", "tool": "get_user_information_by_name", "note": "cyrillic-name search"},
        {"role": "REQUEST", "type": "last_user"},
        {"role": "ACTION", "type": "response_call", "tool": "transfer_to_human_agents"},
    ],
    "banking_knowledge__task_051::t15": [
        {"role": "KB_RULE", "type": "result", "regex": r"logistics_007", "note": "step-2 mandatory checks doc"},
        {"role": "KB_RULE", "type": "result", "regex": r"logistics_005", "note": "utilization threshold doc"},
        {"role": "STATE", "type": "result", "regex": r"credit limit|3,000|4,000", "note": "balance/limit state"},
        {"role": "ACTION", "type": "response_call", "tool": "unlock_discoverable_agent_tool"},
    ],
    "banking_knowledge__task_068::t11": [
        {"role": "ACTION", "type": "response_call", "tool": "call_discoverable_agent_tool", "contains": "light_blue_account_id_placeholder", "note": "placeholder account_id inside discoverable call"},
        {"role": "STATE", "type": "result", "tool": "get_user_information_by_name", "note": "profile without account ids"},
        {"role": "SCHEMA", "type": "result", "contains": "close_bank_account_7392", "note": "unlock result exposing signature"},
    ],
    "banking_knowledge__task_083::t10": [
        {"role": "RULE", "type": "policy", "regex": r"discoverable"},
        {"role": "KB_RULE", "type": "result", "contains": "get_bank_account_transactions_9173"},
        {"role": "ACTION", "type": "response_call", "tool": "get_bank_account_transactions_9173"},
    ],
    # ---------------- retail ----------------
    "retail__106::t3": [
        {"role": "EVIDENCE", "type": "user", "contains": "sofia.thomas3019", "note": "user gives name+email only"},
        {"role": "ACTION", "type": "response_call", "tool": "find_user_id_by_name_zip"},
        {"role": "SCHEMA", "type": "schema", "tool": "find_user_id_by_name_zip"},
    ],
    "retail__27::t10": [
        {"role": "RULE", "type": "policy", "contains": "return or exchange"},
        {"role": "RULE", "type": "policy", "regex": r"pending or delivered"},
        {"role": "STATE", "type": "result", "contains": "delivered"},
        {"role": "ACTION", "type": "response_call", "tool": "return_delivered_order_items"},
        {"role": "ACTION", "type": "response_call", "tool": "exchange_delivered_order_items"},
        {"role": "SCHEMA", "type": "description", "tool": "return_delivered_order_items"},
    ],
    "retail__29::t13": [
        {"role": "RULE", "type": "policy", "regex": r"exchange[^.]{0,300}(same product|any available)", "note": "exchange delivered order section"},
        {"role": "SCHEMA", "type": "description", "tool": "exchange_delivered_order_items"},
        {"role": "STATE", "type": "result", "contains": "5753502325"},
        {"role": "STATE", "type": "result", "contains": "5206946487"},
        {"role": "ACTION", "type": "response_text"},
    ],
    "retail__36::t10": [
        {"role": "RULE", "type": "policy", "regex": r"modif[^.]{0,400}(different|another|option)", "note": "modification = different option"},
        {"role": "ACTION", "type": "response_call", "tool": "modify_pending_order_items"},
        {"role": "STATE", "type": "result", "contains": "Patio Umbrella"},
    ],
    "retail__48::t4": [
        {"role": "EVIDENCE", "type": "result", "contains": "User not found", "note": "failed lookup in turn 2"},
        {"role": "EVIDENCE", "type": "call", "tool": "find_user_id_by_name_zip", "note": "identical earlier call"},
        {"role": "REQUEST", "type": "last_user"},
        {"role": "ACTION", "type": "response_call", "tool": "find_user_id_by_name_zip"},
    ],
    # ---------------- telecom ----------------
    "telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-data_usage_exce::t7": [
        {"role": "RULE", "type": "policy", "contains": "user can do on their device"},
        {"role": "RULE", "type": "policy", "contains": "check_network_status"},
        {"role": "SCHEMA", "type": "catalog_absence", "tool": "check_network_status", "note": "absence from [AVAILABLE TOOLS]"},
        {"role": "ACTION", "type": "response_call", "tool": "check_network_status"},
    ],
    "telecom__mms_issueairplane_mode_on-bad_network_preference-break_apn_mms_setting-break_app_::t10": [
        {"role": "RULE", "type": "policy", "contains": "user can do on their device"},
        {"role": "RULE", "type": "policy", "contains": "check_sim_status"},
        {"role": "EVIDENCE", "type": "result", "contains": "not found", "note": "tool-not-found error in history"},
        {"role": "ACTION", "type": "response_call"},
    ],
    "telecom__mms_issuebreak_apn_mms_setting-user_abroad_roaming_enabled_offPERSONA_Hard::t27": [
        {"role": "RULE", "type": "policy", "contains": "user can do on their device"},
        {"role": "RULE", "type": "policy", "regex": r"(reset_apn_settings|can_send_mms)"},
        {"role": "RULE", "type": "policy", "regex": r"human agent|escalat", "note": "escalation rule"},
        {"role": "ACTION", "type": "response_text"},
        {"role": "ACTION", "type": "response_call", "tool": "transfer_to_human_agents"},
    ],
    "telecom__mobile_data_issuebad_network_preference-bad_vpn-data_mode_off-data_saver_mode_onP::t6": [
        {"role": "RULE", "type": "policy", "contains": "user can do on their device"},
        {"role": "RULE", "type": "policy", "contains": "run_speed_test"},
        {"role": "EVIDENCE", "type": "result", "contains": "not found"},
        {"role": "ACTION", "type": "response_call", "tool": "run_speed_test"},
    ],
    "telecom__service_issueairplane_mode_on-break_apn_settings-lock_sim_card_pin-overdue_bill_s::t15": [
        {"role": "RULE", "type": "policy", "contains": "check_sim_status"},
        {"role": "RULE", "type": "policy", "contains": "user can do on their device"},
        {"role": "EVIDENCE", "type": "user", "regex": r"(перезагруз|автономн|reboot)", "note": "user performed device actions"},
        {"role": "ACTION", "type": "response_call", "tool": "check_sim_status"},
    ],
    "telecom__service_issuebreak_apn_settings-contract_end_suspension-lock_sim_card_pin-unseat_::t13": [
        {"role": "STATE", "type": "result", "tool": "get_details_by_id", "contains": "contract_end_date"},
        {"role": "RULE", "type": "policy", "contains": "contract end date is in the past"},
        {"role": "RULE", "type": "policy", "contains": "current time"},
        {"role": "ACTION", "type": "response_call", "tool": "resume_line"},
    ],
}

# Negative cases: deterministic minimal annotation (target calls + their schemas
# + policy fragments naming the called tools).
NEGATIVE_AUTO_ANNOTATED = (
    "airline__10::t19",
    "banking_knowledge__task_033::t2",
    "retail__12::t4",
    "telecom__mms_issueairplane_mode_on-bad_network_preference-bad_wifi_calling-break_app_sms_p::t7",
)


def auto_requirements(timeline) -> list[dict]:
    """Deterministic negative-case requirements: the target response (calls
    and/or text), the schemas of the called tools, and any policy fragment
    naming a called tool."""
    called = {seg.tool for seg in timeline.segments
              if seg.source_type == "TOOL_CALL" and seg.document == "response" and seg.tool}
    has_response_text = any(seg.source_type == "ASSISTANT" and seg.document == "response"
                            for seg in timeline.segments)
    out = []
    if called:
        out.append({"role": "ACTION", "type": "response_call"})
    if has_response_text:
        out.append({"role": "ACTION", "type": "response_text"})
    if not out:
        out.append({"role": "ACTION", "type": "response_call"})
    for tool in sorted(called):
        out.append({"role": "SCHEMA", "type": "schema", "tool": tool})
        out.append({"role": "RULE", "type": "policy", "contains": tool, "note": "policy names the called tool"})
    return out


# ---------------------------------------------------------------- resolution

def _matcher_role_type_fields(matcher: dict) -> dict:
    return {k: v for k, v in matcher.items() if k in {"tool", "contains", "regex", "document"}}


def resolve_matcher(timeline, matcher: dict) -> list:
    """Resolve a required-fragment matcher to concrete fragments."""
    kind = matcher.get("type")
    matched = []
    import re as _re
    for fragment in timeline.fragments:
        if kind == "policy":
            if fragment.source_type != "SYSTEM" or not fragment.kind.startswith("policy"):
                continue
        elif kind == "instructions":
            if fragment.source_type != "SYSTEM" or not fragment.kind.startswith("instructions"):
                continue
        elif kind == "schema":
            if fragment.source_type != "TOOL_SCHEMA":
                continue
        elif kind == "description":
            if fragment.source_type != "TOOL_DESCRIPTION":
                continue
        elif kind == "user":
            if fragment.source_type != "USER":
                continue
        elif kind == "assistant":
            if fragment.source_type != "ASSISTANT":
                continue
        elif kind == "call":
            if fragment.source_type != "TOOL_CALL":
                continue
        elif kind == "result":
            if fragment.source_type != "TOOL_RESULT":
                continue
        elif kind == "last_user":
            if fragment.source_type != "USER":
                continue
            user_segments = [s for s in timeline.segments if s.source_type == "USER"]
            if not user_segments or fragment.segment_id != user_segments[-1].segment_id:
                continue
        elif kind == "response_call":
            if fragment.source_type != "TOOL_CALL" or fragment.document != "response":
                continue
        elif kind == "response_text":
            if fragment.source_type != "ASSISTANT" or fragment.document != "response":
                continue
        elif kind == "catalog_absence":
            # absence requirement: matched by the catalog region fragment itself
            if fragment.source_type != "SYSTEM" or not fragment.kind.startswith("catalog"):
                continue
        else:
            raise ValueError(f"unknown matcher type {kind}")
        if kind != "catalog_absence" and matcher.get("tool") and fragment.tool != matcher["tool"]:
            continue
        contains = matcher.get("contains")
        if contains and contains.lower() not in fragment.text.lower():
            continue
        pattern = matcher.get("regex")
        if pattern and not _re.search(pattern, fragment.text, _re.IGNORECASE):
            continue
        matched.append(fragment)
    return matched
