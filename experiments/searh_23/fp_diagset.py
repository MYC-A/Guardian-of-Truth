#!/usr/bin/env python3
"""Build the FP diagnostic set: per-FP cause class, source-fact evidence, general distinguishing
operation, refutability verdict. Curated from the deep-dive evidence (spans quoted verbatim).

This answers the user directive: a small diagnostic set of concrete FP causes, related source
facts and potentially distinguishing checks — to determine which GENERAL operations actually
refute erroneous suspicions (not special-case rules).
"""
import json
import os
from pathlib import Path

REPO = Path("/mnt/data/guardian/agent-workspace/Guardian-searh23")
OUT = REPO / "outputs/searh_23/fp_diagnostic"

# General operations (reusable, evidence-cited; NOT case-specific rules)
OPS = {
    "action_discriminator": "Does the response contain an action-executing tool call or an "
                            "action-performed claim? If not, 'confirm/verify BEFORE acting' "
                            "preconditions are not yet applicable -> suspicion refuted.",
    "confirmation_presence": "Does the response itself ask the user to confirm (question span)? "
                             "Refutes 'failed to obtain confirmation' when the ask is present.",
    "quote_entailment": "Is the demanded behavior (announce a tool, restate a user choice, "
                        "proactively disclose scope) actually entailed by the card's policy "
                        "quote? Obligations not present in the quote are invented -> refuted.",
    "trigger_absence": "Does the obligating condition occur in observed facts (cross-user "
                       "request, APN 'Incorrect', MMSC not set)? Absent trigger -> obligation "
                       "not due -> refuted.",
    "latest_observation_match": "Does the flagged claim match the latest clean observation for "
                                "the same entity (card status, membership level)? Match -> "
                                "grounded -> refuted; ambiguous pairing -> UNKNOWN (kept).",
    "request_count": "Mechanical count of user human-agent requests (text spans + user-side "
                     "transfer tool calls) vs the policy threshold -> refutes transfer-timing "
                     "flags when count >= threshold.",
    "internal_attempt_check": "Did the agent perform internal resolution attempts (KB searches) "
                              "before the transfer call? Present -> refutes 'did not attempt "
                              "internally'.",
    "required_data_request": "Does the response request exactly the data the policy requires "
                             "(cancellation reason, user/reservation IDs)? Present -> refutes "
                             "'missing verification' at the data-collection stage.",
}

# per-FP diagnosis (evidence gathered in fp_deep24/fp_evidence24 runs, spans verbatim)
DIAG = [
    {"id": "airline__10::t21", "class": "C1a confirmation-demanded-without-action",
     "facts": "Response presents two paid options, refuses the discount, and asks the user to pick a "
              "card ('пожалуйста, выберите карту для оплаты... и я сразу оформлю изменения'). No booking-"
              "modifying tool call and no action-performed claim in the response.",
     "ops": ["action_discriminator", "confirmation_presence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "airline__24::t14", "class": "C2a invented-restatement-obligation",
     "facts": "book_reservation call exists in history with insurance:\"no\" (matches the user's stated "
              "choice); response summarizes the completed booking. No policy span requires restating "
              "the insurance choice in the summary.",
     "ops": ["quote_entailment", "latest_observation_match"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "airline__3::t4", "class": "C3 user-vs-system data conflict",
     "facts": "User claims Gold; system profile observation says Silver; response states Silver and "
              "explicitly says it relies on profile data. Policy defines membership levels but contains "
              "no rule that user claims override system data.",
     "ops": ["latest_observation_match"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "airline__47::t1", "class": "C1b early-turn-data-collection-flagged",
     "facts": "Turn 1: response asks for user id, reservation id AND the cancellation reason — the "
              "reason request satisfies the card's own quote ('must also obtain the reason for "
              "cancellation'). No action executed yet, so departure-check/confirmation are not yet due.",
     "ops": ["required_data_request", "action_discriminator"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "airline__5::t1", "class": "C1b eligibility-demanded-before-any-action",
     "facts": "Turn 1: response asks for user id and reservation to check flight details before "
              "considering compensation; no compensation action executed ('Only compensate if...' "
              "governs the compensate action, not the discussion).",
     "ops": ["action_discriminator", "required_data_request"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "banking_knowledge__task_033::t2", "class": "C2b invented-announcement-obligation",
     "facts": "Judge demands explicitly announcing the future log_verification call. The policy quote "
              "obliges calling the logging tool AFTER verification; verification has not happened yet, "
              "so the obligation is not due and no announcement duty exists. Response also offers help "
              "first and asks to confirm the transfer preference (compliant handoff pattern).",
     "ops": ["quote_entailment", "confirmation_presence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "banking_knowledge__task_057::t2", "class": "C2b invented-announcement-obligation",
     "facts": "Same pattern: response requests identity data (2 of DOB/email/phone/address); judge "
              "demands announcing verification_logging_tool usage before verification exists.",
     "ops": ["quote_entailment"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "banking_knowledge__task_063::t8", "class": "C4a transfer-'premature'",
     "facts": "5 KB_search_dense calls precede the transfer_to_human_agents call; user turn contains "
              "exactly 1 explicit human-agent request (below the 4-request threshold), but the agent "
              "did attempt internal resolution — the judge's 'without attempting to resolve internally' "
              "is factually false.",
     "ops": ["internal_attempt_check"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "banking_knowledge__task_080::t30", "class": "C5a success-claim-vs-ambiguous-observation",
     "facts": "Claim: Green Account card 'успешшно разморожена и снова активна'. Timeline: green freeze "
              "confirmed (Status: FROZEN); green unfreeze attempted -> unlock error -> unlock ok; "
              "interleaved unfreeze calls for green/blue/gff with responses pairing ambiguously (two "
              "'Unfrozen Successfully ... Status: ACTIVE' responses cite the BLUE card id; no clean "
              "green ACTIVE observation). Mechanical layer cannot refute cleanly: UNKNOWN, flag kept. "
              "This is the honest residual: claim-level grounding needs an unambiguous latest "
              "observation, which this transcript does not provide.",
     "ops": ["latest_observation_match"], "verdict": "NOT_REFUTABLE (UNKNOWN)",
     "expected_effect": "keep"},
    {"id": "banking_knowledge__task_081::t35", "class": "C4b transfer-timing-miscount",
     "facts": "Mechanical count: 4 user-side request_human_agent_transfer tool calls + repeated text "
              "requests ('я прошу снова. Это уже четвёртый раз...'). Judge claims transfer happened on "
              "the 'second request' — counting is factually wrong.",
     "ops": ["request_count"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "retail__12::t4", "class": "C1a confirmation-demanded-for-information",
     "facts": "Response lists the user's two orders (read-only info from profile lookup) and asks which "
              "items to return / which order to cancel. No database-updating action executed; the "
              "quoted precondition ('Before taking any action that updates the database...') governs "
              "actions, not information listing.",
     "ops": ["action_discriminator"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "retail__47::t12", "class": "C1a confirmation-demanded-for-listing",
     "facts": "Response lists order items with IDs and asks which to return + refund method; no action "
              "call, no action-performed claim.",
     "ops": ["action_discriminator", "confirmation_presence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "retail__78::t1", "class": "C2c invented-proactive-disclaimer",
     "facts": "Judge demands the agent proactively state it will deny other users' requests. All three "
              "user requests reference the user's own orders (W5056519, W8277957, W5995614); no "
              "cross-user request exists, so the 'deny any requests for any other user' obligation has "
              "no trigger.",
     "ops": ["trigger_absence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "retail__87::t6", "class": "C1c confirmation-and-status-already-present",
     "facts": "Response proposes the address change, lists each pending order with its status "
              "(W2166301/W2466703/W6832752 pending; W7739115 delivered, W1994898 processed — statuses "
              "stated and consistent with history) and ends with 'Вы подтверждаете эти изменения? "
              "(Пожалуйста, ответьте «да» или «нет»)'. Both judge claims are factually false.",
     "ops": ["confirmation_presence", "latest_observation_match"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "telecom__mms_issueairplane_mode_on-bad_network_preference-break_app_both_permissions-data_::t12",
     "class": "C6 mentioned-value-treated-as-incorrect",
     "facts": "check_apn_settings result: 'Current APN Name: internet; MMSC URL: http://mms.carrier.com/mms/wapenc' "
              "— MMSC URL IS set and no 'Incorrect' marker. Policy reset triggers only if check shows "
              "'Incorrect' or MMSC URL is not set. The judge inferred an 'MMSC URL issue' from the mere "
              "presence of the URL in the output.",
     "ops": ["trigger_absence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
    {"id": "telecom__mms_issueairplane_mode_on-bad_wifi_calling-break_app_both_permissions-data_mode_o::t15",
     "class": "C2d invented-confirmation-instruction",
     "facts": "Judge demands instructing the user to confirm after retrying. The response already asks "
              "for confirmation ('Я буду ждать вашего подтверждения') and the card's quote (permission "
              "tool references) contains no such instruction duty.",
     "ops": ["quote_entailment", "confirmation_presence"], "verdict": "REFUTABLE",
     "expected_effect": "refute"},
]

summary = {
    "n_fp": len(DIAG),
    "refutable": sum(1 for d in DIAG if d["verdict"].startswith("REFUTABLE")),
    "not_refutable": sum(1 for d in DIAG if not d["verdict"].startswith("REFUTABLE")),
    "class_counts": {},
    "op_coverage": {},
}
for d in DIAG:
    summary["class_counts"][d["class"]] = summary["class_counts"].get(d["class"], 0) + 1
    for op in d["ops"]:
        summary["op_coverage"][op] = summary["op_coverage"].get(op, 0) + 1

doc = {
    "purpose": "Diagnostic set of concrete pgjudge FP causes with source facts and GENERAL "
               "distinguishing operations; determines which operations refute erroneous "
               "suspicions before any agent re-run. Not special-case rules: every operation is "
               "defined over response structure, quote entailment, observation timelines, or "
               "mechanical counts, and must cite evidence spans.",
    "base_run": "pgjudge fresh (mistral-api ministral-14b, cards+graph) TP23/FP16/FN0 on public46",
    "general_operations": OPS,
    "cases": DIAG,
    "summary": summary,
    "next_step": "Implement the operations as a mechanical refutation layer over pgjudge "
                 "candidates; validate FPs_removed/16 AND TPs_wrongly_removed/23 (must be 0); "
                 "080 is the expected honest residual (UNKNOWN kept).",
}
(OUT / "diagnostic_set.json").write_text(json.dumps(doc, ensure_ascii=False, indent=1), encoding="utf-8")

lines = ["# FP diagnostic set (pgjudge fresh: 16 FP on public46)", "",
         f"Refutable by general operations: {summary['refutable']}/{len(DIAG)}; "
         f"honest residual (UNKNOWN, kept): {summary['not_refutable']}", "",
         "## Cause classes", ""]
for k, v in sorted(summary["class_counts"].items(), key=lambda kv: -kv[1]):
    lines.append(f"- {k}: {v}")
lines += ["", "## General operations and coverage (cases each op refutes)", ""]
for k, v in sorted(summary["op_coverage"].items(), key=lambda kv: -kv[1]):
    lines.append(f"- **{k}** ({v} cases): {OPS[k]}")
lines += ["", "## Per-case verdicts", "",
          "| case | class | ops | verdict |", "|---|---|---|---|"]
for d in DIAG:
    lines.append(f"| {d['id']} | {d['class']} | {', '.join(d['ops'])} | {d['verdict']} |")
lines += ["", "## Key finding", "",
          "15/16 FPs are refutable by 8 general evidence-cited operations; the single residual "
          "(banking_080) fails because the transcript's interleaved calls make the latest "
          "observation ambiguous — a mechanical layer honestly keeps it. The dominant FP cause "
          "(~9/16) is preconditions demanded where no action is executed or where the response "
          "already contains the demanded confirmation — i.e. the judge lacks an action/communication "
          "discriminator, not more reasoning budget."]
(OUT / "report.md").write_text("\n".join(lines), encoding="utf-8")
print(json.dumps(summary, ensure_ascii=False, indent=1))
print("saved diagnostic_set.json + report.md ->", OUT)
