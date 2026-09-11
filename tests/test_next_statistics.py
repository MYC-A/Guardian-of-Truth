import unittest

from guardian_truth.next.statistics import (
    binary_metrics, calibration_metrics, hierarchical_bootstrap_delta, mcnemar_exact,
)


class StatisticsTests(unittest.TestCase):
    def test_binary_metrics(self):
        result = binary_metrics([0, 0, 1, 1], [0, 1, 1, 0])
        self.assertEqual((1, 1, 1, 1), (result["tp"], result["tn"], result["fp"], result["fn"]))

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
