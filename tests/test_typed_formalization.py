import json
import unittest

from guardian_truth.typed_catalog import extract_typed_catalog
from guardian_truth.typed_formalization import (
    canonical_program, distinguishing_witness, render_controlled_text,
    schema_for_catalog, verify_formalization,
)


def payload(**overrides):
    value = {
        "status": "FORMALIZED", "relation": "UNCONDITIONAL",
        "effect": "ASSERTED", "nodes": [], "condition_root": None,
        "conclusion_root": None, "coverage_span_ids": [],
        "unsupported_span_ids": [],
        "features": {"modality": "NONE", "quantifier": "NONE",
                     "causality": "NONE", "strength": "NONE",
                     "condition": "NONE"},
    }
    value.update(overrides)
    return value


class TypedFormalizationTests(unittest.TestCase):
    def setUp(self):
        self.catalog = extract_typed_catalog(
            "⟦SYSTEM⟧\nAt most 2 calls. On 2031-01-02 status ACTIVE.\n"
            "⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {\"amount\": 2, \"status\": \"ACTIVE\"}")
        self.span = next(x.id for x in self.catalog.items if x.kind == "TextSpan")
        self.action = next(x.id for x in self.catalog.items if x.kind == "Action")
        self.number = next(x.id for x in self.catalog.items if x.kind == "Number" and x.value == 2)

    def raw_limit(self, operator="LE"):
        nodes = [
            {"id": "n0", "op": "COUNT", "refs": [self.action], "children": [], "support_ids": [self.span]},
            {"id": "n1", "op": "REF", "refs": [self.number], "children": [], "support_ids": [self.span]},
            {"id": "n2", "op": operator, "refs": [], "children": ["n0", "n1"], "support_ids": [self.span]},
        ]
        return json.dumps(payload(nodes=nodes, conclusion_root="n2",
                                  coverage_span_ids=[self.span],
                                  features={"modality": "MUST", "quantifier": "ALL",
                                            "causality": "NONE", "strength": "CERTAIN",
                                            "condition": "NONE"}))

    def test_dynamic_schema_enumerates_catalog_and_node_references(self):
        schema = schema_for_catalog(self.catalog)
        node = schema["properties"]["nodes"]["items"]
        self.assertIn(self.action, node["properties"]["refs"]["items"]["enum"])
        self.assertEqual(node["properties"]["support_ids"]["items"]["enum"],
                         [x.id for x in self.catalog.items if x.kind == "TextSpan"])

    def test_verified_typed_count_limit_and_round_trip(self):
        result = verify_formalization(self.raw_limit(), self.catalog)
        self.assertEqual(result.status, "VERIFIED")
        self.assertEqual(dict(result.node_types)["n2"], "BOOL")
        text = render_controlled_text(result.program, self.catalog)
        self.assertIn("LE(COUNT(Action[", text)
        self.assertNotIn("lookup", text)

    def test_unknown_reference_and_missing_support_fail_closed(self):
        value = json.loads(self.raw_limit())
        value["nodes"][0]["refs"] = ["tc999999"]
        result = verify_formalization(json.dumps(value), self.catalog)
        self.assertEqual((result.status, result.error_category),
                         ("UNSUPPORTED", "unknown_reference"))
        value = json.loads(self.raw_limit())
        value["nodes"][0]["support_ids"] = []
        result = verify_formalization(json.dumps(value), self.catalog)
        self.assertEqual((result.status, result.error_category),
                         ("UNSUPPORTED", "unsupported_condition"))

    def test_type_arity_cycle_depth_and_unreachable_are_rejected(self):
        cases = []
        value = json.loads(self.raw_limit()); value["nodes"][0]["refs"] = [self.number]; cases.append(value)
        value = json.loads(self.raw_limit()); value["nodes"][2]["children"] = ["n2", "n1"]; cases.append(value)
        value = json.loads(self.raw_limit()); value["nodes"].append({"id":"n3","op":"IS_TRUE","refs":[self.span],"children":[],"support_ids":[self.span]}); cases.append(value)
        for value in cases:
            with self.subTest(value=value):
                self.assertEqual(verify_formalization(json.dumps(value), self.catalog).status,
                                 "TYPE_ERROR")

    def test_unsupported_and_incomplete_catalog_do_not_verify(self):
        raw = json.dumps(payload(status="UNSUPPORTED"))
        self.assertEqual(verify_formalization(raw, self.catalog).status, "UNSUPPORTED")
        incomplete = extract_typed_catalog("⟦SYSTEM⟧\n1 2 3", max_items=1)
        span = next(x.id for x in incomplete.items if x.kind == "TextSpan")
        value = payload(nodes=[{"id":"n0","op":"IS_TRUE","refs":[span],"children":[],"support_ids":[span]}], conclusion_root="n0")
        self.assertEqual(verify_formalization(json.dumps(value), incomplete).status,
                         "UNRESOLVED")

    def test_canonical_commutative_order_is_stable(self):
        result = verify_formalization(self.raw_limit("EQ"), self.catalog)
        value = json.loads(self.raw_limit("EQ")); value["nodes"][2]["children"].reverse()
        other = verify_formalization(json.dumps(value), self.catalog)
        self.assertEqual(canonical_program(result.program), canonical_program(other.program))

    def test_boundary_witness_distinguishes_lt_from_le(self):
        le = verify_formalization(self.raw_limit("LE"), self.catalog).program
        lt = verify_formalization(self.raw_limit("LT"), self.catalog).program
        result = distinguishing_witness(le, lt, self.catalog)
        self.assertTrue(result.ambiguous)
        self.assertNotEqual(result.witness["left"], result.witness["right"])


if __name__ == "__main__":
    unittest.main()
