import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.claims import (
    blind_claim_cases,
    build_c0_claim_report,
    claim_messages,
    load_claim_arm_contract,
    load_claim_dataset,
    model_claim_proposal,
    response_spans,
)
from guardian_truth.llm_client import Completion


ROOT = Path(__file__).resolve().parents[1]


class Cycle2ClaimTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.dataset = load_claim_dataset(ROOT / "outputs" / "cycle2" / "claim_cases.json")
        cls.contract = load_claim_arm_contract(ROOT / "contracts" / "cycle2_claim_arms_v1.json")

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

    def test_boundary_decomposition_uses_response_only_and_reproduces_offsets(self):
        for case in self.dataset.cases:
            actual = [(item["start"], item["end"], item["text"])
                      for item in response_spans(case.response)]
            expected = [(item.start, item.end, item.text) for item in case.annotations]
            self.assertEqual(expected, actual)

    def test_c2_prompt_has_inventory_but_no_gold_fields(self):
        blind = blind_claim_cases(self.dataset)[0]
        messages, schema, inventory = claim_messages(blind, "C2", self.contract)
        text = json.dumps(messages)
        self.assertIn("span_inventory", text)
        self.assertNotIn("unsupported", text)
        self.assertNotIn("annotations", text)
        self.assertNotIn("expected", text)
        self.assertTrue(inventory)
        self.assertFalse(schema["additionalProperties"])

    def test_c2_requires_one_typed_record_per_response_span(self):
        blind = blind_claim_cases(self.dataset)[0]
        inventory = response_spans(blind["response"])
        payload = {"case_id": blind["case_id"], "spans": [
            {"span_id": item["span_id"], "kind": "FACT", "entities": [],
             "times": [], "source": "UNSPECIFIED"} for item in inventory
        ]}

        class Client:
            def __init__(self, value): self.value = value
            def complete(self, messages, *, schema=None, reasoning_effort=None):
                return Completion(json.dumps(self.value), {}, "test")

        valid = model_claim_proposal(Client(payload), blind, "C2", self.contract, clock=lambda: 0.0)
        self.assertEqual("VALID", valid["schema_status"])
        payload["spans"].pop()
        invalid = model_claim_proposal(Client(payload), blind, "C2", self.contract, clock=lambda: 0.0)
        self.assertEqual("INVALID", invalid["schema_status"])


if __name__ == "__main__":
    unittest.main()
