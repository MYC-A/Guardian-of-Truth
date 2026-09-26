#!/usr/bin/env python3
"""Stage B probe B1: action-state / actor / modality minimal pairs.

Question (directive §8): can we distinguish
  AGENT performs X vs AGENT claims X happened vs AGENT proposes X vs
  AGENT asks USER to do X vs TOOL merely logs/reads/schedules/attempts X
on minimal pairs that share wording, without domain lexicons?

Methods compared:
  code    : fragment_supplier flags + response-call effect typing (v2-equivalent)
  mistral : the v2 Q_ACTION_STATE question form (JSON mode, temp 0)
Gold labels are by construction (each item is synthetically minimal).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import Mistral, effect_type  # noqa: E402

# (id, response snippet, action, gold_state, gold_actor, note)
ITEMS = [
    ("ru_exec", "→ TOOL_CALL execute_replacement: {\"case_id\": \"SD-5101\", \"device_id\": \"DV-7\", \"amount\": 250}",
     "замену устройства", "EXECUTED", "AGENT", "mutation call present"),
    ("ru_exec_refund", "→ TOOL_CALL refund_fee: {\"case_id\": \"SD-5101\", \"amount\": 40}",
     "возврат сбора", "EXECUTED", "AGENT", "mutation call present"),
    ("ru_journal", "→ TOOL_CALL record_audit: {\"case_id\": \"SD-5101\", \"action\": \"replacement\"}",
     "замену устройства", "JOURNALLED_NOT_EXECUTED", "AGENT", "journal write is not the mutation"),
    ("ru_read", "→ TOOL_CALL check_authorization: {\"case_id\": \"SD-5101\", \"amount\": 250}",
     "замену устройства", "NOT_EXECUTED_READ", "AGENT", "read is not the action"),
    ("ru_claim_past", "Замена устройства DV-7 выполнена.", "замену устройства",
     "CLAIMED_COMPLETED", "AGENT", "past-tense completion claim, no call"),
    ("ru_offer_future", "Выполню замену устройства DV-7.", "замену устройства",
     "PROPOSED_ONLY", "AGENT", "RU 1sg future"),
    ("ru_offer_cond", "Замена будет выполнена после вашего подтверждения.", "замену устройства",
     "PROPOSED_ONLY", "AGENT", "conditional future"),
    ("ru_ask_user", "Пожалуйста, запустите диагностику user_self_test на вашем устройстве.",
     "диагностику user_self_test", "ASKED_USER", "USER", "imperative to user on user-side action"),
    ("ru_refuse", "Я не могу выполнить замену устройства DV-7.", "замену устройства",
     "REFUSED", "AGENT", "explicit refusal"),
    ("ru_transfer_claim", "Я передал ваш вопрос специалисту.", "передачу специалисту",
     "CLAIMED_COMPLETED", "AGENT", "claimed handoff"),
    ("ru_transfer_exec", "→ TOOL_CALL transfer_specialist: {\"case_id\": \"SD-5101\", \"reason\": \"stock\"}",
     "передачу специалисту", "EXECUTED", "AGENT", "handoff call"),
    ("ru_stock_claim", "Устройства DV-7 нет в наличии.", "наличие устройства DV-7",
     "CLAIMED_COMPLETED", "AGENT", "status claim"),
    ("en_exec", "→ TOOL_CALL replace_device: {\"case_id\": \"CS-42\", \"device_id\": \"DEV-9\", \"amount\": 250}",
     "the device replacement", "EXECUTED", "AGENT", "mutation call"),
    ("en_schedule", "→ TOOL_CALL schedule_replacement: {\"case_id\": \"CS-42\", \"when\": \"2026-10-03\"}",
     "the device replacement", "SCHEDULED_NOT_EXECUTED", "AGENT", "deferred, not done"),
    ("en_check_status", "→ TOOL_CALL check_replacement_status: {\"case_id\": \"CS-42\"}",
     "the device replacement", "NOT_EXECUTED_READ", "AGENT", "status read"),
    ("en_audit_log", "→ TOOL_CALL write_replacement_audit: {\"case_id\": \"CS-42\", \"result\": \"ok\"}",
     "the device replacement", "JOURNALLED_NOT_EXECUTED", "AGENT", "audit write is not the mutation"),
    ("en_claim_past", "The replacement of DEV-9 has been completed.", "the device replacement",
     "CLAIMED_COMPLETED", "AGENT", "present perfect claim"),
    ("en_offer_future", "I will complete the replacement of DEV-9.", "the device replacement",
     "PROPOSED_ONLY", "AGENT", "will-future"),
    ("en_offer_happy", "I'd be happy to process the refund for you.", "the refund",
     "PROPOSED_ONLY", "AGENT", "polite offer"),
    ("en_ask_user", "Could you run the diagnostic on your device yourself?",
     "the diagnostic", "ASKED_USER", "USER", "request to user"),
    ("en_refuse", "I'm afraid I cannot cancel this booking.", "the cancellation",
     "REFUSED", "AGENT", "refusal"),
    ("en_user_says_done", "USER: Я уже выполнил диагностику на своём устройстве.",
     "the diagnostic", "USER_PERFORMED", "USER", "user reports own action"),
    ("en_tool_error", "→ TOOL_CALL replace_device: {\"case_id\": \"CS-42\", \"device_id\": \"DEV-9\", \"amount\": 250}\n← TOOL_RESPONSE replace_device: {\"error\": \"insufficient authorization\"}",
     "the device replacement", "ATTEMPTED_FAILED", "AGENT", "attempted but failed"),
]

# Code baseline: reproduce what v2's code re-checks can decide (flags + call typing)
import re  # noqa: E402
FUTURE_LEX = re.compile(r"(оформлю|забронирую|отменю|выполню|сделаю|запишу|верну|обработаю|"
                        r"(?:will|shall|i'll|we'll)\b|going to|happy to|после вашего|after you)", re.I)
PAST_LEX = re.compile(r"(?:выполнена|выполнено|выполнил|выполнила|сделано|готово|оформлен|завершен|передал|нет в наличии|"
                      r"processed|completed|confirmed|has been|was)\b", re.I)
ASK_LEX = re.compile(r"(пожалуйста|запустите|укажите|подтвердите|please|could you|would you|"
                     r"run the|yourself|на вашем устройстве)", re.I)
REFUSE_LEX = re.compile(r"(не могу|невозможно|cannot|can't|unable to|impossible)", re.I)
USER_TURN = re.compile(r"^USER:", re.I)


def code_verdict(snippet: str, action: str) -> str:
    calls = re.findall(r"→ TOOL_CALL ([\w.-]+)", snippet)
    text_lines = [ln for ln in snippet.splitlines()
                  if ln.strip() and not ln.strip().startswith(("→", "←"))]
    text = " ".join(text_lines)
    is_user_turn = bool(USER_TURN.search(snippet))
    if is_user_turn:
        return "USER_PERFORMED" if PAST_LEX.search(text) else "UNCLEAR"
    if calls:
        etypes = [effect_type(c) for c in calls]
        err = "error" in snippet.lower() or "insufficient" in snippet.lower()
        if err:
            return "ATTEMPTED_FAILED"
        if "MUTATION" in etypes:
            return "EXECUTED"
        if "JOURNAL" in etypes:
            return "JOURNALLED_NOT_EXECUTED"
        if "DEFER" in etypes:
            return "SCHEDULED_NOT_EXECUTED"
        return "NOT_EXECUTED_READ"
    if REFUSE_LEX.search(text):
        return "REFUSED"
    if ASK_LEX.search(text) and not PAST_LEX.search(text):
        return "ASKED_USER"
    if PAST_LEX.search(text) and not FUTURE_LEX.search(text):
        return "CLAIMED_COMPLETED"
    if FUTURE_LEX.search(text):
        return "PROPOSED_ONLY"
    return "UNCLEAR"


SYSTEM = ("You are a precise trajectory annotator. Given an assistant response fragment and an "
          "action description, classify the action's state. Answer with JSON only.")
Q = """RESPONSE_FRAGMENT (verbatim):
{snippet}

ACTION_IN_QUESTION: {action}

QUESTION: For the ACTION_IN_QUESTION, choose the state that holds in the RESPONSE_FRAGMENT:
- EXECUTED: the assistant performs the action itself via a tool call in this fragment
- CLAIMED_COMPLETED: the assistant asserts the action already happened, with NO tool call here
- PROPOSED_ONLY: the assistant offers or promises the action for the future / conditionally
- ASKED_USER: the assistant asks or instructs the USER to perform the action
- REFUSED: the assistant says it cannot or will not perform the action
- OTHER_TOOL_SEMANTICS: a tool call is present but it only reads, logs/audits, schedules, or
  checks status — it does NOT perform the action itself (state which in reason)
- USER_PERFORMED: a user message reports the user did it
- UNCLEAR: none of the above
ANSWER JSON: {{"state":"...","actor":"AGENT|USER|TOOL","deciding_evidence":"<short quote>","reason":"..."}}"""


def main() -> int:
    out = {"items": [], "gold_states": {}}
    client = Mistral()
    for iid, snippet, action, gold, actor, note in ITEMS:
        cv = code_verdict(snippet, action)
        row = {"id": iid, "gold_state": gold, "gold_actor": actor, "code_state": cv,
               "code_correct": cv == gold, "note": note}
        try:
            ans = client.ask(SYSTEM, Q.format(snippet=snippet, action=action))
            ms = str(ans["value"].get("state", "")).upper()
            ma = str(ans["value"].get("actor", "")).upper()
            # tolerant match: model's EXECUTED vs gold variants
            row["mistral_state"] = ms
            row["mistral_actor"] = ma
            row["mistral_reason"] = str(ans["value"].get("reason", ""))[:160]
            row["mistral_correct"] = ms == gold
        except Exception as e:  # noqa: BLE001
            row["mistral_state"] = f"ERROR:{e}"
            row["mistral_correct"] = False
        out["items"].append(row)
        print(f"{iid:22s} gold={gold:22s} code={row['code_correct']} mistral={row['mistral_correct']}")
    for method in ("code", "mistral"):
        n = sum(1 for r in out["items"] if r.get(f"{method}_correct"))
        out[f"{method}_accuracy"] = round(n / len(ITEMS), 4)
    # the critical minimal pairs: executed vs journal vs read vs schedule
    crit = [r for r in out["items"] if r["id"] in ("ru_exec", "ru_journal", "ru_read",
                                                   "en_exec", "en_schedule", "en_check_status",
                                                   "en_audit_log", "en_tool_error")]
    out["critical_pairs"] = {m: round(sum(1 for r in crit if r.get(f"{m}_correct")) / len(crit), 4)
                             for m in ("code", "mistral")}
    dump = Path(__file__).resolve().parent / "results_b1.json"
    dump.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "items"}, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
