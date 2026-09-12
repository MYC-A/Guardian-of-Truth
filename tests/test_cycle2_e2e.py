import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.e2e import (
    compose_g1,
    load_e2e_contract,
    x1_messages,
    x1_proposal,
)
from guardian_truth.cycle2.external import blind_external_case, load_external_dataset
from guardian_truth.llm_client import Completion


ROOT = Path(__file__).resolve().parents[1]


class Cycle2E2ETests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.contract = load_e2e_contract(ROOT / "contracts" / "cycle2_e2e_arms_v1.json")
        cls.dataset = load_external_dataset(ROOT / "outputs" / "cycle2" / "external_manifest.json")

    def test_g1_formula_is_exactly_locked(self):
        cases = {
            "x0": (1, 0, None, 1),
            "x4zero": (0, 0, None, 0),
            "both": (0, 1, 1, 1),
            "modelzero": (0, 1, 0, 0),
            "unknown": (0, 1, None, None),
        }
        offline, model = [], []
        for case_id, (x0, x4, x1, _) in cases.items():
            offline.extend([
                {"case_id": case_id, "arm": "X0", "label": x0},
                {"case_id": case_id, "arm": "X4", "label": x4},
            ])
            model.append({"case_id": case_id, "arm": "X1", "label": x1,
                          "schema_status": "VALID" if x1 is not None else "NOT_EVALUATED",
                          "transport_status": "SUCCESS", "latency_ms": 0, "usage": {}})
        result = {row["case_id"]: row for row in compose_g1(offline, model)}
        self.assertEqual({key: expected for key, (*_, expected) in cases.items()},
                         {key: row["label"] for key, row in result.items()})

    def test_x1_sees_complete_allowed_input_but_no_gold(self):
        blind = blind_external_case(self.dataset.cases[0])
        messages, schema, rendered = x1_messages(blind, self.contract)
        text = json.dumps(messages)
        self.assertNotIn("ground_truth", text)
        self.assertNotIn("localization_basis", text)
        self.assertNotIn("source_decision", text)
        self.assertIn("target_assistant_turn", rendered)
        self.assertFalse(schema["additionalProperties"])

    def test_x1_quotes_are_converted_to_auditable_spans(self):
        blind = blind_external_case(self.dataset.cases[0])
        _, _, rendered = x1_messages(blind, self.contract)
        quote = blind["target_assistant_turn"]["action"]["name"]
        self.assertIn(quote, rendered)
        payload = {"case_id": blind["case_id"], "verdict": "ERROR",
                   "responsible_quotes": [quote], "reason": "Target action diverges."}

        class Client:
            def complete(self, messages, *, schema=None, reasoning_effort=None):
                return Completion(json.dumps(payload), {}, "test")

        row = x1_proposal(Client(), blind, self.contract, clock=lambda: 0.0)
        self.assertEqual("VALID", row["schema_status"])
        span = row["responsible_spans"][0]
        self.assertEqual(quote, rendered[span["start"]:span["end"]])


if __name__ == "__main__":
    unittest.main()
