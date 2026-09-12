import unittest

from guardian_truth.next.statistics import (
    binary_metrics, calibration_metrics, hierarchical_bootstrap_delta, mcnemar_exact,
    selective_metrics,
)


class StatisticsTests(unittest.TestCase):
    def test_binary_metrics(self):
        result = binary_metrics([0, 0, 1, 1], [0, 1, 1, 0])
        self.assertEqual((1, 1, 1, 1), (result["tp"], result["tn"], result["fp"], result["fn"]))
        self.assertEqual(0.5, result["balanced_error"])

    def test_selective_metrics_do_not_hide_unknown_as_correct(self):
        result = selective_metrics(
            [1, 0, 1], [1, 0, 0],
            ["PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED"],
        )
        self.assertEqual(2 / 3, result["coverage"])
        self.assertEqual(0.0, result["selective_risk"])
        self.assertEqual(1, result["unresolved"])

    def test_mcnemar_uses_paired_correctness(self):
        result = mcnemar_exact([0, 1, 0, 1], [0, 0, 0, 0], [1, 1, 0, 1])
        self.assertEqual(2, result["candidate_only_correct"])
        self.assertEqual(1, result["incumbent_only_correct"])

    def test_hierarchical_bootstrap_is_reproducible(self):
        args = ([0, 1, 0, 1], [0, 0, 0, 1], [0, 1, 0, 1], ["a", "a", "b", "b"])
        self.assertEqual(hierarchical_bootstrap_delta(*args, samples=50, seed=7),
                         hierarchical_bootstrap_delta(*args, samples=50, seed=7))

    def test_calibration(self):
        result = calibration_metrics([0, 1], [0.0, 1.0])
        self.assertEqual(0.0, result["brier"])
        self.assertEqual(0.0, result["ece"])


if __name__ == "__main__":
    unittest.main()
