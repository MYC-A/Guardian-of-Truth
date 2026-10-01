"""Gate against removing one suspicion while another survives."""
import sys
import unittest
import json
from unittest.mock import patch
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path[:0] = [str(HERE), str(HERE.parents[2] / "service"),
                str(HERE.parent / "three_architectures")]
from counterevidence import aggregate_review, validate_review
from structural_v02 import parse_case_v02
from phi_shadow_run import formal_messages
from counterevidence import collect_review


class ReviewTest(unittest.TestCase):
    def setUp(self):
        self.ctx = parse_case_v02("test", "⟦SYSTEM⟧\nChecks are permitted.\n\n[AVAILABLE TOOLS]\n- inspect — Read status.\n    id: string!\n⟦USER⟧\nInspect E-1.\n", '→ TOOL_CALL inspect: {"id":"E-1"}\nThe state is ready.')
        self.findings = [
            {"checked": {"statement": '→ TOOL_CALL inspect: {"id":"E-1"}'},
             "type": "OTHER", "module": "judge/test"},
            {"checked": {"statement": "The state is ready."},
             "type": "UNSUPPORTED", "module": "judge/test"}]

    def disposition(self, i, status):
        return {"finding_index": i, "status": status,
                "target_quote": self.findings[i]["checked"]["statement"],
                "source_quotes": [{"source": "policy", "text": "Checks are permitted."}],
                "explanation": "Source-based assessment."}

    def record(self, rows, whole=True):
        return {"valid": True, "model": "test",
                "review": {"dispositions": rows, "additional_error": None,
                           "whole_move_reviewed": whole}}

    def test_one_refuted_does_not_remove_remaining_error(self):
        rec = self.record([self.disposition(0, "REFUTED"), self.disposition(1, "CONFIRMED")])
        self.assertTrue(validate_review(rec["review"], self.ctx, self.findings)[0])
        decision, findings, _ = aggregate_review(rec, "ERROR", self.findings, self.ctx)
        self.assertEqual(decision, "ERROR")
        self.assertEqual(findings, self.findings[1:])

    def test_all_refuted_requires_full_move_review(self):
        rows = [self.disposition(i, "REFUTED") for i in range(2)]
        self.assertEqual(aggregate_review(self.record(rows, False), "ERROR",
            self.findings, self.ctx)[0], "ERROR")
        decision, findings, _ = aggregate_review(self.record(rows), "ERROR",
            self.findings, self.ctx)
        self.assertEqual((decision, findings), ("NO_ERROR", []))

    def test_unsure_and_invalid_preserve_first_decision(self):
        rows = [self.disposition(0, "REFUTED"), self.disposition(1, "UNSURE")]
        self.assertEqual(aggregate_review(self.record(rows), "ERROR",
            self.findings, self.ctx)[0], "ERROR")
        self.assertEqual(aggregate_review({"valid": False}, "ERROR",
            self.findings, self.ctx)[0], "ERROR")

    def test_false_quote_duplicate_index_and_missing_counterevidence_rejected(self):
        rows = [self.disposition(i, "REFUTED") for i in range(2)]
        rows[1]["finding_index"] = 0
        self.assertFalse(validate_review(self.record(rows)["review"], self.ctx, self.findings)[0])
        rows = [self.disposition(i, "REFUTED") for i in range(2)]
        rows[0]["source_quotes"] = []
        self.assertFalse(validate_review(self.record(rows)["review"], self.ctx, self.findings)[0])
        rows[0]["source_quotes"] = [{"source": "policy", "text": "Invented permission"}]
        self.assertFalse(validate_review(self.record(rows)["review"], self.ctx, self.findings)[0])

    def test_formal_prompt_contains_actual_schema_and_query_guard(self):
        messages = formal_messages("The current action is permitted.",
            [{"id": "prompt", "text": "Checks are permitted."}])
        self.assertIn('"atom_id"', messages[0]["content"])
        self.assertIn('"required"', messages[0]["content"])
        self.assertIn("Do not add the query as a fact", messages[0]["content"])

    def test_v2_rejects_false_secondary_quote_even_with_one_valid_source(self):
        vote = {"label": 1, "type": "CONTRADICTION",
                "response_quote": "The state is ready.",
                "policy_quote": "Checks are permitted.",
                "history_quote": "A nonexistent observation", "catalog_quote": "",
                "source_refs": [], "explanation": "A proposed contradiction."}
        value = {"dispositions": [], "additional_error": vote, "whole_move_reviewed": True}
        self.assertTrue(validate_review(value, self.ctx, [])[0])
        self.assertFalse(validate_review(value, self.ctx, [], strict_quotes=True)[0])

    def test_v2_exposes_the_actual_reference_namespace(self):
        sent = []

        def fake_chat(model, messages, **kwargs):
            sent.append(messages)
            return {"content": json.dumps({"dispositions": [], "additional_error": None,
                                            "whole_move_reviewed": True}), "usage": {}}

        with patch("llm.chat", fake_chat):
            record = collect_review({"model": "env_mistral", "protocol": "source-bound-v2"},
                                    self.ctx, [])
        payload = json.loads(sent[0][1]["content"])
        self.assertEqual([r["turn_id"] for r in payload["source_reference_inventory"]],
                         [t.turn_id for t in self.ctx.turns])
        self.assertIn("NOT event IDs", sent[0][0]["content"])
        self.assertEqual(record["module"], "independent-counterevidence/2")
        self.assertTrue(record["valid"])


if __name__ == "__main__":
    unittest.main()
