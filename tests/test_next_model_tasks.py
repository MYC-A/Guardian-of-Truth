import json
import unittest

from guardian_truth.next.model_tasks import parse_claim_proposal, parse_policy_meaning
from guardian_truth.next.records import ClaimKind


class ModelTaskValidationTests(unittest.TestCase):
    def test_claim_citation_is_computed_from_blind_response(self):
        response = "Я уже изменил тариф."
        payload = {"claims": [{"kind": "action", "subject": "assistant", "predicate": "change",
                               "object": "fare", "modality": "completed",
                               "quote": "изменил тариф", "entities": []}], "uncovered_quotes": []}
        claims, uncovered = parse_claim_proposal(json.dumps(payload, ensure_ascii=False), response)
        self.assertEqual(ClaimKind.ACTION, claims[0].kind)
        self.assertEqual("изменил тариф", response[claims[0].source.start:claims[0].source.end])
        self.assertFalse(uncovered)

    def test_non_verbatim_claim_citation_is_rejected(self):
        payload = {"claims": [{"kind": "fact", "subject": "x", "predicate": "p", "object": "y",
                               "modality": "asserted", "quote": "missing", "entities": []}],
                   "uncovered_quotes": []}
        with self.assertRaises(ValueError):
            parse_claim_proposal(json.dumps(payload), "different")

    def test_duplicate_quote_is_rejected_as_ambiguous(self):
        payload = {"claims": [], "uncovered_quotes": ["same"]}
        with self.assertRaises(ValueError):
            parse_claim_proposal(json.dumps(payload), "same and same")

    def test_policy_meaning_requires_policy_local_quote(self):
        payload = {"rules": [{"kind": "prohibition", "subject": "agent", "predicate": "call",
                              "object": "tool", "quote": "must not call"}], "unknown_quotes": []}
        _, spans, _ = parse_policy_meaning(json.dumps(payload), "The agent must not call this tool.")
        self.assertEqual(1, len(spans))


if __name__ == "__main__":
    unittest.main()
