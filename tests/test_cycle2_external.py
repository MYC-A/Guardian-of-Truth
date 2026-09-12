import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.external import (
    blind_external_case,
    guardian_documents,
    load_external_dataset,
)
from guardian_truth.parsing import parse_events


ROOT = Path(__file__).resolve().parents[1]


class Cycle2ExternalTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_external_dataset(ROOT / "outputs" / "cycle2" / "external_manifest.json")

    def test_frozen_external_is_balanced_by_category_and_target_localized(self):
        self.assertEqual(100, len(self.dataset.cases))
        counts = {}
        for case in self.dataset.cases:
            counts[case.domain] = counts.get(case.domain, 0) + 1
            self.assertEqual(case.gold["target_step"], len(case.history))
        self.assertEqual({20}, set(counts.values()))

    def test_blind_view_excludes_gold_and_provenance(self):
        value = blind_external_case(self.dataset.cases[0])
        text = json.dumps(value)
        self.assertNotIn("gold", text)
        self.assertNotIn("rationale", text)
        self.assertNotIn("expected_decision", text)
        self.assertNotIn("provenance", text)

    def test_guardian_adapter_separates_history_and_target(self):
        case = self.dataset.cases[0]
        prompt, response = guardian_documents(case)
        self.assertIn("DECLARED GOAL", prompt)
        self.assertIn("[AVAILABLE TOOLS]", prompt)
        self.assertNotIn(case.gold["localization_basis"], prompt + response)
        target_events = parse_events(response, "response")
        self.assertTrue(any(event.role == "assistant" for event in target_events))


if __name__ == "__main__":
    unittest.main()
