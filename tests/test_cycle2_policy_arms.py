import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.policy_arms import (
    blind_policy_cases,
    build_blocked_policy_report,
    freeze_proposals,
    p0_proposal,
    score_proposals,
)
from guardian_truth.cycle2.policy_semantics import load_policy_dataset


ROOT = Path(__file__).resolve().parents[1]


class Cycle2PolicyArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_policy_dataset(ROOT / "outputs" / "cycle2" / "policy_cases.json")

    def test_blind_view_contains_no_gold_or_worlds(self):
        blind = blind_policy_cases(self.dataset)
        text = repr(blind[0])
        self.assertNotIn("world", text.lower())
        self.assertNotIn("expected", text.lower())
        self.assertFalse(hasattr(blind[0], "structure"))

    def test_p0_uses_current_exact_patterns_and_abstains_elsewhere(self):
        blind = blind_policy_cases(self.dataset)
        exact = next(case for case in blind if case.id == "one_tool_call::0")
        unsupported = next(case for case in blind if case.id == "one_tool_call::1")
        self.assertEqual("SUPPORTED", p0_proposal(exact)["representation_status"])
        self.assertEqual("UNSUPPORTED", p0_proposal(unsupported)["representation_status"])

    def test_proposals_are_frozen_before_gold_join(self):
        proposals, digest = freeze_proposals(p0_proposal(case) for case in blind_policy_cases(self.dataset))
        self.assertEqual(104, len(proposals))
        self.assertEqual(64, len(digest))
        scores = score_proposals(proposals, self.dataset)
        self.assertEqual(104, len(scores))
        supported = next(row for row in scores if row["case_id"] == "one_tool_call::0")
        self.assertTrue(supported["behavioral_semantic_correct"])

    def test_failed_gate_blocks_model_arms_without_scoring_them_zero(self):
        gate = {
            "status": "EVALUATION_BLOCKED_BY_PROVIDER",
            "policy_benchmark_permitted": False,
            "gate_contract_sha256": "a" * 64,
        }
        report = build_blocked_policy_report(self.dataset, gate)
        self.assertEqual("EVALUATION_BLOCKED_BY_PROVIDER", report["status"])
        self.assertEqual("NO_CONCLUSION", report["paired_p1_p2"]["status"])
        self.assertNotIn("P1", report["arms"])
        self.assertEqual(0, report["paired_p1_p2"]["n_P1_valid"])
        self.assertNotIn("expected_answer", json.dumps(report))


if __name__ == "__main__":
    unittest.main()
