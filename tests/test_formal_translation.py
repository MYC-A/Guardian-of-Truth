import json
import unittest

from guardian_truth.formal_reasoning import APPLICABILITY_SCHEMA, FORMAL_SCHEMA
from guardian_truth.formal_translation import (
    APPLICATION_INSTRUCTION, FORMAL_INSTRUCTION, build_application_messages,
    build_formal_messages, schema_for,
)


class FormalTranslationTests(unittest.TestCase):
    def setUp(self):
        self.evidence = [{"id": "s1", "text": "A refund is allowed only if A and B."}]

    def test_formal_payload_is_untrusted_json_data(self):
        messages = build_formal_messages("Is refund allowed?", self.evidence)
        self.assertEqual(messages[0]["role"], "system")
        self.assertIn("ONLY_IF", messages[0]["content"])
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["evidence"], self.evidence)
        self.assertNotIn("Is refund allowed?", messages[0]["content"])

    def test_application_keeps_rule_separate_from_evidence(self):
        messages = build_application_messages("Apply?", "A and B imply Q", self.evidence)
        payload = json.loads(messages[1]["content"])
        self.assertEqual(payload["supplied_rule"], "A and B imply Q")
        self.assertIn("entity scope", APPLICATION_INSTRUCTION)

    def test_input_bounds_and_shape(self):
        bad = [[], [{"id": "x", "text": ""}], [{"id": "x", "body": "a"}],
               [{"id": "x", "text": "a"}, {"id": "x", "text": "b"}]]
        for evidence in bad:
            with self.subTest(evidence=evidence), self.assertRaises(ValueError):
                build_formal_messages("target", evidence)
        with self.assertRaises(ValueError):
            build_formal_messages("", self.evidence)

    def test_schema_dispatch(self):
        self.assertIs(schema_for("D"), FORMAL_SCHEMA)
        self.assertIs(schema_for("C"), APPLICABILITY_SCHEMA)
        with self.assertRaises(ValueError):
            schema_for("E")

    def test_prompts_explicitly_forbid_execution_and_row_verdict(self):
        self.assertIn("Python", FORMAL_INSTRUCTION)
        self.assertIn("not a final row label", APPLICATION_INSTRUCTION)


if __name__ == "__main__":
    unittest.main()
