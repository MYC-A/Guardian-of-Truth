import unittest

from guardian_truth.outer_benchmarking import (
    auxiliary_experiments, evaluate_real_rules, evaluate_row_slice,
)


class OuterBenchmarkingTests(unittest.TestCase):
    def test_rule_coverage_is_conservative(self):
        cases = [{
            "case_id": "x", "rule": "Proceed only if all records are valid.",
            "gold": {"relations": ["ONLY_IF"], "operators": [],
                     "features": {"quantifier": "ALL"}},
        }]
        report = evaluate_real_rules(cases)
        self.assertEqual(report["formalization_feature_coverage"], 1)
        self.assertEqual(report["gold_audit_gate_passed_cases"], 1)
        self.assertEqual(report["automatic_strict_verdicts_from_new_semantic_path"], 0)

    def test_semantic_routes_abstain_but_exact_controls_survive(self):
        cases = [
            {"row_id": "semantic", "baseline": {"prediction": 1, "status": "FP", "route": "semantic"},
             "invariant_expected_verdict": "UNRESOLVED"},
            {"row_id": "exact", "baseline": {"prediction": 1, "status": "TP_EXACT", "route": "exact:x"},
             "invariant_expected_verdict": "PROVED_VIOLATION"},
        ]
        report = evaluate_row_slice(cases)
        self.assertEqual(report["D_E_determinate"], 1)
        self.assertEqual(report["D_E_confident_wrong"], 0)
        self.assertEqual(report["contest_predictions_changed"], 0)

    def test_auxiliary_experiments_have_real_witnesses(self):
        report = auxiliary_experiments()
        self.assertEqual(report["metamorphic"]["passed"], 15)
        self.assertTrue(report["information_insufficiency"]["found"])
        self.assertEqual(report["semantic_residual"]["hard_core_invariant"],
                         "PROVED_VIOLATION")
        self.assertEqual(report["semantic_residual"]["residual_changes_outcome"],
                         "UNRESOLVED")
        self.assertEqual(report["structured_standard"]["explained_override_only"],
                         "NO_EXPLICIT_VIOLATION_FOUND")


if __name__ == "__main__":
    unittest.main()
