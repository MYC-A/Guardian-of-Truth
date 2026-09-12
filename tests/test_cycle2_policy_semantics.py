import copy
from pathlib import Path
import unittest

from guardian_truth.cycle2.policy_semantics import (
    STRUCTURAL_FIELDS,
    evaluate_program,
    load_policy_dataset,
    score_policy_candidate,
)


ROOT = Path(__file__).resolve().parents[1]
CASES = ROOT / "outputs" / "cycle2" / "policy_cases.json"


class Cycle2PolicySemanticsTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_policy_dataset(CASES)

    def test_frozen_dataset_has_required_scope_and_source_mix(self):
        self.assertEqual(96, len(self.dataset.cases))
        self.assertEqual(24, len({case.family for case in self.dataset.cases}))
        self.assertEqual(
            {"external_or_seed", "minimal_pair", "paraphrase", "long_distance"},
            {case.variant for case in self.dataset.cases},
        )
        self.assertIn("EXTERNAL_POLICY_FRAGMENT", {case.source_kind for case in self.dataset.cases})
        self.assertEqual(64, len(self.dataset.digest))

    def test_gold_program_reproduces_every_frozen_world(self):
        for case in self.dataset.cases:
            with self.subTest(case=case.id):
                self.assertGreaterEqual(len(case.worlds), 4)
                for world in case.worlds:
                    self.assertEqual(world.expected, evaluate_program(case.program, world.facts))

    def test_behavioral_equivalence_does_not_require_json_clause_order(self):
        case = next(case for case in self.dataset.cases if len(case.program["violation_clauses"]) > 1)
        reordered = {
            "violation_clauses": [list(reversed(clause)) for clause in reversed(case.program["violation_clauses"])],
            "permission_clauses": [list(clause) for clause in case.program["permission_clauses"]],
        }
        score = score_policy_candidate(case, case.structure, reordered)
        self.assertTrue(score["behavioral_semantic_correct"])
        self.assertFalse(score["exact_representation"])

    def test_structural_dimensions_are_scored_separately(self):
        case = self.dataset.cases[0]
        changed = copy.deepcopy(case.structure)
        changed["modality"] = "REQUIREMENT"
        program = {key: [list(clause) for clause in case.program[key]] for key in case.program}
        score = score_policy_candidate(case, changed, program)
        self.assertEqual(set(STRUCTURAL_FIELDS), set(score["structural_fields"]))
        self.assertFalse(score["structural_fields"]["modality"])
        self.assertTrue(score["behavioral_semantic_correct"])
        self.assertFalse(score["exact_representation"])


if __name__ == "__main__":
    unittest.main()
