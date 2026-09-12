import unittest

from guardian_truth.cycle2.x5 import core_review, protected_review


class Cycle2X5Tests(unittest.TestCase):
    def test_core_does_not_inherit_incumbent_finding(self):
        prompt = "⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- known — tool\n    id: string!"
        response = "⟦ASSISTANT_TOOL_CALL name=\"unknown\"⟧\n{\"id\":\"x\"}"
        core = core_review(prompt, response)
        protected = protected_review(prompt, response)
        self.assertEqual(0, core["label"])
        self.assertEqual("UNRESOLVED", core["internal_verdict"])
        self.assertEqual(1, protected["label"])
        self.assertEqual("X0", protected["telemetry"]["decision_source"])

    def test_unknown_is_visible_when_binary_falls_back_to_zero(self):
        result = core_review("⟦SYSTEM⟧\nOpen policy text.", "⟦ASSISTANT⟧\nA statement.")
        telemetry = result["telemetry"]
        self.assertEqual("UNRESOLVED", telemetry["solver_status"])
        self.assertTrue(telemetry["used_binary_fallback"])
        self.assertEqual(0, telemetry["binary_result"])
        required = {
            "policy_status", "policy_arm", "n_policy_segments", "n_policy_rules",
            "n_unknown_policy_segments", "n_claim_spans", "n_claims",
            "n_unknown_claim_spans", "n_tool_contracts", "n_unknown_tools",
            "n_evidence_events", "n_candidate_bindings", "solver_status",
            "binary_result", "decision_source",
        }
        self.assertLessEqual(required, set(telemetry))


if __name__ == "__main__":
    unittest.main()
