import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.policy_arms import (
    arm_messages,
    blind_policy_cases,
    build_blocked_policy_report,
    build_policy_report,
    freeze_proposals,
    load_policy_arm_contract,
    model_policy_proposal,
    paired_p1_p2,
    p0_proposal,
    score_proposals,
)
from guardian_truth.cycle2.policy_semantics import load_policy_dataset
from guardian_truth.llm_client import Completion


ROOT = Path(__file__).resolve().parents[1]


class Cycle2PolicyArmTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_policy_dataset(ROOT / "outputs" / "cycle2" / "policy_cases.json")
        cls.contract = load_policy_arm_contract(ROOT / "contracts" / "cycle2_policy_arms_v1.json")

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

    def test_arm_prompts_contain_only_blind_inputs_and_explicit_schema(self):
        blind = blind_policy_cases(self.dataset)[0]
        for arm in ("P1", "P2"):
            messages, schema = arm_messages(blind, arm, self.contract)
            rendered = json.dumps(messages)
            self.assertIn("OUTPUT_JSON_SCHEMA", messages[1]["content"])
            self.assertIn(blind.policy, messages[1]["content"])
            self.assertNotIn("worlds", rendered)
            self.assertNotIn("expected", rendered)
            self.assertFalse(schema["additionalProperties"])

    def test_p1_direct_rule_is_scored_without_fake_typed_structure(self):
        case = self.dataset.cases[0]
        blind = blind_policy_cases(self.dataset)[0]
        payload = {"case_id": case.id, **{
            key: [list(clause) for clause in case.program[key]]
            for key in ("violation_clauses", "permission_clauses")
        }}

        class Client:
            def complete(self, messages, *, schema=None, reasoning_effort=None):
                return Completion(json.dumps(payload), {}, "test")

        proposal = model_policy_proposal(Client(), blind, "P1", self.contract, clock=lambda: 0.0)
        self.assertEqual("VALID", proposal["schema_status"])
        scored = score_proposals([proposal], self.dataset)[0]
        self.assertTrue(scored["behavioral_semantic_correct"])
        self.assertIsNone(scored["structural_accuracy"])

    def test_p2_typed_ir_is_compiled_deterministically(self):
        case = self.dataset.cases[0]
        blind = blind_policy_cases(self.dataset)[0]
        payload = {"case_id": case.id, **case.structure}

        class Client:
            def complete(self, messages, *, schema=None, reasoning_effort=None):
                return Completion(json.dumps(payload), {}, "test")

        proposal = model_policy_proposal(Client(), blind, "P2", self.contract, clock=lambda: 0.0)
        self.assertEqual("SUPPORTED", proposal["representation_status"])
        self.assertTrue(score_proposals([proposal], self.dataset)[0]["behavioral_semantic_correct"])

    def test_paired_result_uses_only_cases_valid_in_both_arms(self):
        scores = [
            {"case_id": "a", "arm": "P1", "behavioral_semantic_correct": True},
            {"case_id": "a", "arm": "P2", "behavioral_semantic_correct": False},
            {"case_id": "b", "arm": "P1", "behavioral_semantic_correct": True},
            {"case_id": "b", "arm": "P2", "behavioral_semantic_correct": None},
        ]
        result = paired_p1_p2(scores, minimum_cases=1, bootstrap_resamples=100, bootstrap_seed=1)
        self.assertEqual(1, result["n_both_valid"])
        self.assertEqual(1, result["P1_only_correct"])
        self.assertEqual(0, result["P2_only_correct"])


if __name__ == "__main__":
    unittest.main()
