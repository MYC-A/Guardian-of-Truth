"""TQ scoring must expose TPs lost by false-positive refutation."""

import json
import sys
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments" / "searh_23"))
import tq_questions as tq  # noqa: E402


class TQScoringTests(unittest.TestCase):
    def test_lost_true_positives_become_false_negatives(self):
        base = {"per_case": [
            *({"id": f"tp{i}", "gold": 1, "new_label": 1} for i in range(23)),
            *({"id": f"fp{i}", "gold": 0, "new_label": 1} for i in range(6)),
        ], "after": {"FN": 0}}
        reviewed = [
            *({"id": f"tp{i}", "gold": 1, "new_label": 0} for i in range(7)),
            *({"id": f"fp{i}", "gold": 0, "new_label": 0} for i in range(3)),
        ]
        score = tq.score_refutations(base, reviewed)
        self.assertEqual(score["after"], {"TP": 16, "FP": 3, "FN": 7, "F1": 0.7619})
        self.assertEqual(len(score["tp_lost"]), 7)

    def test_upstream_false_negatives_are_preserved(self):
        base = {"per_case": [{"id": "tp", "gold": 1, "new_label": 1}],
                "after": {"FN": 2}}
        score = tq.score_refutations(base, [{"id": "tp", "gold": 1, "new_label": 0}])
        self.assertEqual(score["after"], {"TP": 0, "FP": 0, "FN": 3, "F1": 0.0})

    def test_saved_final_replays_without_new_model_calls(self):
        paths = [
            ("outputs/searh_23/fp_diagnostic/refute_layer_v3_v31.json",
             "outputs/searh_23/tq_layer/tq_questions.json"),
            ("outputs/searh_23/hotel_p/refute_layer_v4_hotel.json",
             "outputs/searh_23/tq_layer/tq_questions_hotel.json"),
        ]
        for base_path, tq_path in paths:
            with self.subTest(tq_path=tq_path):
                base = json.loads((ROOT / base_path).read_text(encoding="utf-8"))
                saved = json.loads((ROOT / tq_path).read_text(encoding="utf-8"))
                score = tq.score_refutations(base, saved["per_case"])
                self.assertEqual(score["after"], saved["after"])
                self.assertEqual(score["tp_lost"], saved["tp_lost"])


if __name__ == "__main__":
    unittest.main()
