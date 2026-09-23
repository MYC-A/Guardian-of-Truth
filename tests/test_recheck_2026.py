"""Regression checks for the confounds discovered in prior experiments."""
from __future__ import annotations

import unittest
from pathlib import Path
from tempfile import TemporaryDirectory
from types import SimpleNamespace

from experiments.recheck_2026.agent.run import controller, execute
from experiments.recheck_2026.c2_x5.run import extraction_from_c2
from experiments.recheck_2026.claim_verifier.run import support_status
from experiments.recheck_2026.fp_replay.run import audit_evidence
from experiments.recheck_2026.fp_review.run import candidate_decision
from experiments.recheck_2026.holistic.run import assemble
from experiments.recheck_2026.questions.run import pick
from experiments.recheck_2026.shared import prepare_run, write_jsonl


class RecheckContractTests(unittest.TestCase):
    def test_questions_sample_distinct_cases_and_exact_source(self):
        cases = {str(i): {"prompt": "Policy exact quote", "response": ""}
                 for i in range(3)}
        divergences = [{"id": "0", "key": f"0#{i}", "kind": "A",
                        "policy_fragment": "exact quote"} for i in range(20)]
        divergences += [{"id": "1", "key": "1#0", "kind": "B",
                         "policy_fragment": "exact quote"},
                        {"id": "2", "key": "2#0", "kind": "A",
                         "policy_fragment": "missing"}]
        result = pick(divergences, cases, 12)
        self.assertEqual({r["id"] for r in result}, {"0", "1"})
        self.assertEqual(len(result), 2)

    def test_groundedness_yes_is_not_confirmation(self):
        self.assertEqual(support_status("yes"), "NOT_SOURCE_SUPPORTED_PROBABILISTIC")
        self.assertEqual(support_status("no"), "SOURCE_SUPPORTED_PROBABILISTIC")
        self.assertEqual(support_status("yes", "custom_violation"),
                         "VIOLATION_SUPPORTED_PROBABILISTIC")

    def test_premise_tool_never_substitutes_card_one(self):
        fake = SimpleNamespace(p={"cards": [{"quote_grounded": True,
                                               "policy_quote": "required"}]},
                               pol="required")
        with self.assertRaises(ValueError):
            execute(fake, "premise_card", "P2")
        with self.assertRaises(ValueError):
            execute(fake, "premise_card", 2)
        fake.premise_check = lambda query: {"status": "PREMISES_VERIFIED",
            "result": {"card_index": int(query), "verdict": "safe",
                       "checker": {"passed": True}, "blocking": None}}
        result = execute(fake, "premise_card", 1)
        self.assertTrue(result["proof"])
        self.assertEqual(result["result"]["card_index"], 1)

    def test_safe_card_is_candidate_not_whole_response_clearance(self):
        observation = {"tool": "premise_card", "target": 1, "proof": True,
                       "result": {"verdict": "safe"}}
        decision = controller(1, {"violated_cards": [1]}, [observation])
        self.assertEqual(decision["label"], 1)
        self.assertEqual(decision["safe_card_candidates"], [1])

    def test_c2_action_without_predicate_cannot_claim_proof(self):
        response = "I completed something."
        proposal = {"arm": "C2", "schema_status": "VALID",
                    "coverage": [{"start": 0, "end": len(response), "status": "CLAIM"}],
                    "claims": [{"start": 0, "end": len(response),
                                "kind": "ACTION_COMPLETED"}]}
        extraction, meta = extraction_from_c2(response, proposal)
        self.assertEqual(meta["n_generic_actions_without_predicate"], 1)
        self.assertEqual(extraction.claims[0].kind.value, "fact")

    def test_holistic_head_tail_keeps_recent_history(self):
        case = {"prompt": "begin" + "x" * 300 + "RECENT", "response": "reply"}
        first = assemble(case, "head", 200)
        paired = assemble(case, "head_tail", 200)
        self.assertNotIn("RECENT", first["user"])
        self.assertIn("RECENT", paired["user"])

    def test_fp_replay_requires_actual_source_quote(self):
        case = {"prompt": "policy text", "response": "response text"}
        valid, _ = audit_evidence(case, [{"source": "prompt", "quote": "policy",
                                          "operation": "trigger_present"}])
        self.assertTrue(valid)
        invalid, _ = audit_evidence(case, [{"source": "prompt", "quote": "invented",
                                            "operation": "trigger_present"}])
        self.assertFalse(invalid)

    def test_fp_reviewer_requires_all_cards_and_an_exact_quote(self):
        case = {"prompt": "Policy says ask for confirmation.", "response": "Please confirm."}
        cited = {1: {}, 2: {}}
        one = {"assessments": [{"card_index": 1, "verdict": "refuted",
                               "source": "response", "quote": "Please confirm.",
                               "operation": "confirmation_question"}],
               "other_error_present": False}
        self.assertEqual(candidate_decision(1, cited, one, case)["label"], 1)
        both = {"assessments": one["assessments"] + [{"card_index": 2,
                "verdict": "refuted", "source": "prompt", "quote": "Policy says",
                "operation": "trigger_present"}], "other_error_present": False}
        self.assertEqual(candidate_decision(1, cited, both, case)["label"], 0)
        both["assessments"][1]["quote"] = "invented"
        self.assertEqual(candidate_decision(1, cited, both, case)["label"], 1)

    def test_resume_rejects_changed_config(self):
        with TemporaryDirectory() as directory:
            path = Path(directory) / "run"
            self.assertEqual(prepare_run(path, {"input_hash": "one"}), [])
            write_jsonl(path / "records.jsonl", [{"id": "case"}])
            self.assertEqual(prepare_run(path, {"input_hash": "one"}, True),
                             [{"id": "case"}])
            with self.assertRaises(ValueError):
                prepare_run(path, {"input_hash": "two"}, True)


if __name__ == "__main__":
    unittest.main()
