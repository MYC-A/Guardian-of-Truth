import json
import unittest

from guardian_truth.typed_catalog import extract_typed_catalog
from guardian_truth.typed_translation import (
    build_free_messages, build_typed_messages, normalize_operator,
    parse_free_formalization,
)


class TypedTranslationTests(unittest.TestCase):
    def test_builders_keep_gold_out_and_catalog_ids_in(self):
        rule = "An order is allowed only if status is pending."
        catalog = extract_typed_catalog("⟦SYSTEM⟧\n" + rule)
        self.assertNotIn("gold", json.dumps(build_free_messages(rule)))
        typed = json.loads(build_typed_messages(rule, catalog)[1]["content"])
        self.assertEqual(typed["source_rule"], rule)
        self.assertEqual([x["id"] for x in typed["catalog"]],
                         [x.id for x in catalog.items])

    def test_free_parser_requires_exact_unique_proof_and_empty_unsupported(self):
        rule = "A only if B."
        value = {"status":"FORMALIZED", "relation":"ONLY_IF", "effect":"ASSERTED",
                 "formula":"A -> B", "predicates":["A","B"], "arguments":[],
                 "operators":["implies"], "support_quotes":[rule],
                 "features":{"modality":"NONE","quantifier":"NONE",
                             "causality":"NONE","strength":"NONE",
                             "condition":"NECESSARY"}}
        parsed = parse_free_formalization(json.dumps(value), rule)
        self.assertEqual(parsed.relation, "ONLY_IF")
        value["support_quotes"] = ["missing"]
        with self.assertRaisesRegex(ValueError, "invalid_free_quote"):
            parse_free_formalization(json.dumps(value), rule)
        value.update(status="UNSUPPORTED", formula="", predicates=[], arguments=[],
                     operators=[], support_quotes=[])
        parse_free_formalization(json.dumps(value), rule)

    def test_operator_normalization_is_scoring_only_and_bounded(self):
        self.assertEqual(normalize_operator("less than or equal"), "LE")
        self.assertIsNone(normalize_operator("run_python"))

    def test_free_parser_accepts_unconstrained_linc_like_extra_fields(self):
        rule = "No action if its end date is in the past."
        value = {"source_rule": rule, "type": "prohibition",
                 "formula": "Prohibit(action(x)) IF end_date(x) < today",
                 "predicates": ["end_date(entity)"], "support": [rule]}
        parsed = parse_free_formalization(json.dumps(value), rule)
        self.assertEqual((parsed.relation, parsed.effect), ("IF", "PROHIBITED"))


if __name__ == "__main__":
    unittest.main()
