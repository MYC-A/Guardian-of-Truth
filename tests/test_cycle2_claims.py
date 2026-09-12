import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.claims import (
    blind_claim_cases,
    build_c0_claim_report,
    load_claim_dataset,
)


ROOT = Path(__file__).resolve().parents[1]


class Cycle2ClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_claim_dataset(ROOT / "outputs" / "cycle2" / "claim_cases.json")

    def test_frozen_benchmark_has_required_size_kinds_and_domains(self):
        spans = [item for case in self.dataset.cases for item in case.annotations]
        self.assertEqual(209, len(spans))
        self.assertEqual(11, len({item.kind for item in spans}))
        self.assertGreaterEqual(len({case.domain for case in self.dataset.cases}), 4)
        for case in self.dataset.cases:
            for item in case.annotations:
                self.assertEqual(item.text, case.response[item.start:item.end])

    def test_blind_view_contains_response_but_no_annotations(self):
        blind = blind_claim_cases(self.dataset)
        self.assertEqual({"case_id", "response"}, set(blind[0]))
        self.assertNotIn("unsupported", json.dumps(blind))
        self.assertNotIn("annotations", json.dumps(blind))

    def test_c0_reports_coverage_and_does_not_see_context(self):
        report = build_c0_claim_report(self.dataset)
        self.assertEqual("C0_COMPLETE_MODEL_ARMS_PENDING", report["status"])
        self.assertEqual(1.0, report["arms"]["C0"]["declarative_coverage"])
        self.assertGreater(report["arms"]["C0"]["unsupported_claims"], 0)
        self.assertTrue(all(not row["prompt_visible"] and not row["history_visible"]
                            and not row["evidence_visible"] and not row["label_visible"]
                            for row in report["proposals"]))


if __name__ == "__main__":
    unittest.main()
