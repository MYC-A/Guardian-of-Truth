"""Boundary checks for source joins and extractive proposal validation."""
from __future__ import annotations

import sys
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))
import fast_followup_run as followup  # noqa: E402
import completion_witness as completion  # noqa: E402
import feasibility_witness as feasibility  # noqa: E402
import typed_witnesses as witness  # noqa: E402
import fp_refute_modal_safe as modal_safe  # noqa: E402

CASES = {row["id"]: row for row in followup.read_cases(
    ROOT / "experiments/searh_23/service_desk_v1/cases.csv")}
POLICY_QUOTE = "The agent must never state that a replacement, refund, or audit completed"


class WitnessTest(unittest.TestCase):
    def test_no_modal_is_not_proof_that_policy_is_optional(self):
        quote = ("Before executing a device replacement or fee refund, verify "
                 "the requester's identity for the SAME case and obtain the "
                 "user's explicit confirmation of that action.")
        future = CASES["desk_v1__text_ok_future"]
        refusal = CASES["desk_v1__text_bad_refusal"]
        card = {"policy_quote": quote}
        future_sig = modal_safe.v4.case_signals(future["prompt"], future["response"])
        refusal_sig = modal_safe.v4.case_signals(refusal["prompt"], refusal["response"])
        self.assertEqual(modal_safe.refute_card(card, future_sig)[0], "UNKNOWN")
        self.assertEqual(modal_safe.refute_card(card, refusal_sig)[0], "UNKNOWN")
        self.assertEqual(modal_safe.refute_card(
            {"policy_quote": "Verify the requester before acting."},
            refusal_sig)[0], "UNKNOWN")

    def test_amount_source_must_match_entity(self):
        def amount_source(cid):
            record = witness.local_record(CASES[cid])
            return next(arg for target in record["arguments"]
                        for arg in target["args"] if arg["path"] == "amount")
        correct = amount_source("desk_v1__call_ok_replacement")
        wrong = amount_source("desk_v1__call_bad_wrong_case_auth")
        self.assertEqual(correct["status"], "SOURCE_FOUND")
        self.assertTrue(correct["same_field_observations"])
        self.assertEqual(wrong["status"], "SOURCE_FOUND")
        self.assertTrue(wrong["user_events"])
        self.assertFalse(wrong["same_field_observations"])
        self.assertTrue(witness.exact_literal("The fee is $250.", 250))
        self.assertFalse(witness.exact_literal("The fee is $250.50", 250))

    def test_failed_replay_requires_immediately_paired_result(self):
        base = CASES["desk_v1__call_ok_replacement"]
        target_args = next(e.text for e in followup.parse_events(base["response"], "response")
                           if e.kind == "call")
        call = "→ TOOL_CALL execute_replacement: " + target_args + "\n"
        failed = '← TOOL_RESPONSE execute_replacement: {"status":"failed"}\n'
        intervening = '→ TOOL_CALL get_case: {"case_id":"SD-5101"}\n'
        new = {**base, "prompt": base["prompt"] + "\n" + call + intervening + failed}
        self.assertEqual(witness.local_record(new)["repeated_failed_calls"], [])
        paired = {**base, "prompt": base["prompt"] + "\n" + call + failed}
        self.assertEqual(len(witness.local_record(paired)["repeated_failed_calls"]), 1)

    def test_completion_claim_result_uses_case_and_amount(self):
        case = CASES["desk_v1__text_bad_wrong_amount_auth"]
        proposal = {"candidate": True, "claim_quote":
                    next(e.text for e in followup.parse_events(case["response"], "response")
                         if e.role == "assistant" and e.kind == "text"),
                    "policy_quote": POLICY_QUOTE, "tool": "check_authorization",
                    "entity_ids": ["SD-5101"], "amount": 250}
        verdict, _, _ = completion.validate(case, proposal)
        self.assertEqual(verdict, "UNSUPPORTED_COMPLETION_CANDIDATE")
        supported = {**case, "prompt": case["prompt"].replace(
            '"amount": 150', '"amount": 250').replace(
            '"amount":150', '"amount":250')}
        verdict, _, matched = completion.validate(supported, proposal)
        self.assertEqual(verdict, "REFUTED_BY_RESULT")
        self.assertTrue(matched)

    def test_completion_v2_accepts_line_wrap_only_and_rejects_unstated_amount(self):
        case = CASES["desk_v1__text_bad_done"]
        claim = next(e.text for e in followup.parse_events(case["response"], "response")
                     if e.role == "assistant" and e.kind == "text")
        policy = ("The agent must never state that a replacement, refund, or audit "
                  "completed unless a matching successful tool result was observed.")
        proposal = {"candidate": True, "claim_quote": claim,
                    "policy_quote": policy, "tool": "execute_replacement",
                    "entity_ids": ["SD-5101", "DV-7"], "amount": None}
        self.assertEqual(completion.validate_v2(case, proposal)[0],
                         "UNSUPPORTED_COMPLETION_CANDIDATE")
        self.assertIn("amount_not_in_claim", completion.validate_v2(
            case, {**proposal, "amount": 250})[1])

    def test_feasibility_requires_observed_and_entity_bound_premise(self):
        case = CASES["desk_v1__text_bad_refusal"]
        events = followup.parse_events(case["prompt"], "prompt")
        target = next(e.text for e in followup.parse_events(case["response"], "response")
                      if e.role == "assistant" and e.kind == "text")
        user = next(e.text for e in events if e.role == "user" and e.kind == "text"
                    and "SD-5101" in e.text)
        result_idx = next(i for i, e in enumerate(events)
                          if e.kind == "result" and e.name == "check_authorization")
        proposal = {"candidate": True, "kind": "false_refusal",
                    "response_quote": target,
                    "policy_quote": "the agent must handle a requested replacement",
                    "user_quote": user, "tool": "execute_replacement",
                    "premises": [{"event": result_idx, "quote": events[result_idx].text}],
                    "missing_premises": [], "entity_ids": ["SD-5101"],
                    "amount": 250}
        self.assertEqual(feasibility.validate(case, proposal)[0], "CANDIDATE")
        bad = {**proposal, "premises": []}
        self.assertIn("no_observed_precondition", feasibility.validate(case, bad)[1])
        stale = {**case, "prompt": case["prompt"] +
                 '\n← TOOL_RESPONSE check_authorization: '
                 '{"case_id":"SD-5101","amount":250,"authorization_status":"none"}\n'}
        self.assertIn("superseded_result_premise",
                      feasibility.validate(stale, proposal)[1])
        source = events[result_idx].source
        wrong_prompt = (case["prompt"][:source.start] +
                        case["prompt"][source.start:source.end].replace(
                            "SD-5101", "SD-9999") + case["prompt"][source.end:])
        wrong = {**case, "prompt": wrong_prompt}
        wrong_events = followup.parse_events(wrong_prompt, "prompt")
        bad = {**proposal, "premises": [{"event": result_idx,
                                        "quote": wrong_events[result_idx].text}]}
        self.assertIn("unbound_result_entity", feasibility.validate(wrong, bad)[1])

    def test_feasibility_v2_requires_mandatory_tool_clause(self):
        case = CASES["desk_v1__text_bad_refusal"]
        events = followup.parse_events(case["prompt"], "prompt")
        result_idx = next(i for i, e in enumerate(events)
                          if e.kind == "result" and e.name == "check_authorization")
        proposal = {"candidate": True, "kind": "false_refusal",
                    "response_quote": next(e.text for e in followup.parse_events(
                        case["response"], "response") if e.role == "assistant"),
                    "policy_quote": ("When stock is available and the identity, confirmation, "
                                     "and any required authorization are satisfied, the agent "
                                     "must handle a requested replacement with execute_replacement "
                                     "rather than falsely claim it is impossible or transfer "
                                     "solely to avoid the work."),
                    "user_quote": next(e.text for e in events if e.role == "user"
                                       and e.kind == "text" and "SD-5101" in e.text),
                    "tool": "execute_replacement",
                    "premises": [{"event": result_idx, "quote": events[result_idx].text}],
                    "missing_premises": [], "entity_ids": ["SD-5101"], "amount": 250}
        self.assertEqual(feasibility.validate_v2(case, proposal)[0], "CANDIDATE")
        permission = ("If stock is unavailable, the agent may explain the delay "
                      "or transfer to a specialist.")
        verdict, issues = feasibility.validate_v2(
            case, {**proposal, "policy_quote": permission})
        self.assertEqual(verdict, "UNKNOWN")
        self.assertIn("policy_is_not_mandatory", issues)


if __name__ == "__main__":
    unittest.main()
