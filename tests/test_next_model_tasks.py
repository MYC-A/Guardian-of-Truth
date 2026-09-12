import json
import unittest

from guardian_truth.next.model_tasks import parse_claim_proposal, parse_policy_meaning
from guardian_truth.next.records import (
    ClaimKind,
    PolicyModality,
    RegulatedKind,
    SemanticUncertainty,
)


def _policy_payload(**overrides):
    meaning = {
        "modality": "prohibition",
        "subject": {"kind": "agent", "identifier": "support agent"},
        "regulated": {"kind": "action", "predicate": "call", "object": "refund tool"},
        "conditions": [{"quote": "after approval", "occurrence": 0}],
        "exceptions": [],
        "temporal": {"relation": "after", "anchor": "manager approval", "duration": ""},
        "identity_constraints": [
            {"entity_type": "order", "key": "owner_id", "relation": "equals", "value": "requesting_user"},
        ],
        "quantification": {"kind": "all", "amount": 0},
        "uncertainty": "certain",
        "unsupported_reason": "",
        "quote": "must not call the refund tool after approval",
        "occurrence": 0,
    }
    meaning.update(overrides)
    return {"meanings": [meaning], "unknown_quotes": []}


class ModelTaskValidationTests(unittest.TestCase):
    def test_claim_citation_is_computed_from_blind_response(self):
        response = "Я уже изменил тариф."
        payload = {"claims": [{"kind": "action", "subject": "assistant", "predicate": "change",
                               "object": "fare", "modality": "completed",
                               "quote": "изменил тариф", "occurrence": 0, "entities": []}], "uncovered_quotes": []}
        claims, uncovered = parse_claim_proposal(json.dumps(payload, ensure_ascii=False), response)
        self.assertEqual(ClaimKind.ACTION, claims[0].kind)
        self.assertEqual("изменил тариф", response[claims[0].source.start:claims[0].source.end])
        self.assertFalse(uncovered)

    def test_non_verbatim_claim_citation_is_rejected(self):
        payload = {"claims": [{"kind": "fact", "subject": "x", "predicate": "p", "object": "y",
                               "modality": "asserted", "quote": "missing", "occurrence": 0,
                               "entities": []}],
                   "uncovered_quotes": []}
        with self.assertRaises(ValueError):
            parse_claim_proposal(json.dumps(payload), "different")

    def test_duplicate_quote_uses_explicit_occurrence(self):
        payload = {"claims": [], "uncovered_quotes": [{"quote": "same", "occurrence": 1}]}
        _, uncovered = parse_claim_proposal(json.dumps(payload), "same and same")
        self.assertEqual(9, uncovered[0].start)

    def test_policy_meaning_requires_policy_local_quote(self):
        policy = "The support agent must not call the refund tool after approval."
        meanings, spans, _ = parse_policy_meaning(json.dumps(_policy_payload()), policy)
        self.assertEqual(1, len(spans))
        self.assertEqual(PolicyModality.PROHIBITION, meanings[0].modality)
        self.assertEqual(RegulatedKind.ACTION, meanings[0].regulated.kind)
        self.assertEqual("after approval", meanings[0].conditions[0].text)
        self.assertEqual(SemanticUncertainty.CERTAIN, meanings[0].uncertainty)
        self.assertEqual("llm_semantic_proposal", meanings[0].provenance.extractor)

    def test_policy_meaning_rejects_case_changed_non_exact_quote(self):
        payload = _policy_payload(quote="Must not call the refund tool after approval")
        with self.assertRaisesRegex(ValueError, "exact substring"):
            parse_policy_meaning(
                json.dumps(payload), "The support agent must not call the refund tool after approval.",
            )

    def test_policy_meaning_rejects_incoherent_temporal_constraint(self):
        payload = _policy_payload(temporal={"relation": "before", "anchor": "", "duration": ""})
        with self.assertRaisesRegex(ValueError, "requires an anchor"):
            parse_policy_meaning(
                json.dumps(payload), "The support agent must not call the refund tool after approval.",
            )

    def test_policy_meaning_rejects_incoherent_quantifier(self):
        payload = _policy_payload(quantification={"kind": "all", "amount": 2})
        with self.assertRaisesRegex(ValueError, "numeric quantifiers"):
            parse_policy_meaning(
                json.dumps(payload), "The support agent must not call the refund tool after approval.",
            )

    def test_policy_meaning_requires_reason_for_unsupported_semantics(self):
        payload = _policy_payload(uncertainty="unsupported", unsupported_reason="")
        with self.assertRaisesRegex(ValueError, "requires a reason"):
            parse_policy_meaning(
                json.dumps(payload), "The support agent must not call the refund tool after approval.",
            )

    def test_policy_meaning_preserves_unknown_source_span(self):
        payload = _policy_payload()
        payload["unknown_quotes"] = [{"quote": "unless law requires it", "occurrence": 0}]
        policy = (
            "The support agent must not call the refund tool after approval, "
            "unless law requires it."
        )
        _, _, unknown = parse_policy_meaning(json.dumps(payload), policy)
        self.assertEqual("unless law requires it", policy[unknown[0].start:unknown[0].end])


if __name__ == "__main__":
    unittest.main()
