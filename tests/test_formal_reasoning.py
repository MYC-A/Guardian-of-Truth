import copy
import json
import unittest

from guardian_truth.formal_reasoning import (
    APPLICABILITY_SCHEMA, FORMAL_SCHEMA, MAX_OUTPUT_CHARS, Atom,
    FormalProgram, FormalValidationError, evaluate_formalization,
    parse_formalization, solve, validate_applicability,
)


EVIDENCE = [
    {"id": "policy", "text": "A and B permit Q unless X."},
    {"id": "observations", "text": "A is true. B is true. X is false. Q was requested."},
]


def literal(number, polarity="POS"):
    return {"atom_id": "a" + str(number), "polarity": polarity}


def source(identifier="policy", quote="A and B permit Q unless X."):
    return {"source_id": identifier, "quote": quote}


def atom(number, **changes):
    result = {"id": "a" + str(number), "text": "Proposition " + str(number),
              "entity_refs": ["L1002"], "time_refs": ["current_turn"]}
    result.update(changes)
    return result


def fact(number, polarity="POS"):
    return {"literal": literal(number, polarity),
            "sources": [source("observations", "A is true.")]}


def program(direction="IF", facts=None, query=None):
    return {"status": "FORMALIZED", "atoms": [atom(0), atom(1), atom(2)],
            "facts": [fact(0), fact(1)] if facts is None else facts,
            "rules": [{"id": "r0", "direction": direction,
                       "conditions": [literal(0), literal(1)],
                       "conclusion": literal(2), "sources": [source()]}],
            "query": literal(2) if query is None else query}


def application():
    return {
        "rule": {"id": "rule1", "direction": "IF", "source": source()},
        "facts": [{"id": "f1", "source": source("observations", "A is true.")},
                  {"id": "f2", "source": source("observations", "B is true.")},
                  {"id": "f3", "source": source("observations", "X is false.")}],
        "entity_scope": "MATCH", "time_scope": "MATCH",
        "conditions": [{"id": "c1", "clause_quote": "A", "status": "TRUE", "fact_ids": ["f1"]},
                       {"id": "c2", "clause_quote": "B", "status": "TRUE", "fact_ids": ["f2"]}],
        "exceptions": [{"id": "e1", "clause_quote": "X", "status": "FALSE", "fact_ids": ["f3"]}],
        "applicability": "APPLIES",
    }


class FormalReasoningTests(unittest.TestCase):
    def evaluate(self, value):
        return evaluate_formalization(json.dumps(value), EVIDENCE)

    def apply(self, value):
        return validate_applicability(json.dumps(value), EVIDENCE)

    def test_if_follows_with_all_premises_and_retains_proof(self):
        result = self.evaluate(program())
        self.assertEqual(result.relation, "FOLLOWS")
        self.assertEqual(len(result.proof), 3)
        self.assertEqual(result.proof[-1].rule_id, "r0")
        self.assertEqual(result.proof[-1].sources[0].source_id, "policy")
        self.assertEqual(result.scope, "relative_to_supplied_formalization")

    def test_missing_b_is_unknown_not_false(self):
        result = self.evaluate(program(facts=[fact(0)]))
        self.assertEqual(result.relation, "INSUFFICIENT")
        self.assertFalse(result.proof)
        self.assertFalse(result.conflicts)

    def test_only_if_does_not_invent_converse(self):
        self.assertEqual(self.evaluate(program("ONLY_IF")).relation, "INSUFFICIENT")
        for query in (literal(0), literal(1)):
            with self.subTest(query=query):
                self.assertEqual(self.evaluate(program("ONLY_IF", [fact(2)], query)).relation, "FOLLOWS")

    def test_if_does_not_invent_reverse(self):
        self.assertEqual(self.evaluate(program("IF", [fact(2)], literal(0))).relation, "INSUFFICIENT")

    def test_iff_supports_both_directions(self):
        self.assertEqual(self.evaluate(program("IFF")).relation, "FOLLOWS")
        for query in (literal(0), literal(1)):
            self.assertEqual(self.evaluate(program("IFF", [fact(2)], query)).relation, "FOLLOWS")

    def test_explicit_negative_head_contradicts_query(self):
        value = program()
        value["rules"][0]["conclusion"]["polarity"] = "NEG"
        result = self.evaluate(value)
        self.assertEqual(result.relation, "CONTRADICTS")
        self.assertEqual(result.proof[-1].literal.polarity, "NEG")

    def test_negative_query_and_negative_premise_are_explicit(self):
        value = program(facts=[fact(0, "NEG"), fact(1)])
        value["rules"][0]["conditions"][0]["polarity"] = "NEG"
        value["query"]["polarity"] = "NEG"
        self.assertEqual(self.evaluate(value).relation, "CONTRADICTS")

    def test_contradictory_facts_do_not_explode(self):
        result = self.evaluate(program(facts=[fact(0), fact(0, "NEG")]))
        self.assertEqual(result.relation, "INSUFFICIENT")
        self.assertEqual(result.reason, "conflicting_closure")
        self.assertEqual(result.conflicts, ("a0",))
        self.assertFalse(result.proof)

    def test_derived_conflict_blocks_otherwise_proven_query(self):
        value = program(facts=[fact(0), fact(1), fact(2, "NEG")])
        result = self.evaluate(value)
        self.assertEqual(result.relation, "INSUFFICIENT")
        self.assertEqual(result.conflicts, ("a2",))

    def test_no_contraposition_is_claimed_by_forward_fragment(self):
        value = program("ONLY_IF", [fact(0, "NEG")], literal(2, "NEG"))
        self.assertEqual(self.evaluate(value).relation, "INSUFFICIENT")

    def test_two_step_proof_and_cycle_terminate(self):
        value = program()
        value["atoms"].append(atom(3))
        value["rules"].extend([
            {"id": "r1", "direction": "IF", "conditions": [literal(2)],
             "conclusion": literal(3), "sources": [source()]},
            {"id": "r2", "direction": "IF", "conditions": [literal(3)],
             "conclusion": literal(0), "sources": [source()]},
        ])
        value["query"] = literal(3)
        result = self.evaluate(value)
        self.assertEqual(result.relation, "FOLLOWS")
        self.assertEqual([step.rule_id for step in result.proof], [None, None, "r0", "r1"])
        value["facts"] = []
        self.assertEqual(self.evaluate(value).relation, "INSUFFICIENT")

    def test_entity_and_time_annotations_do_not_unify_distinct_atoms(self):
        value = program(facts=[fact(0)])
        value["rules"] = []
        value["atoms"][0].update(text="The line is active", entity_refs=["L1"], time_refs=["t1"])
        value["atoms"][1].update(text="The line is active", entity_refs=["L2"], time_refs=["t1"])
        value["atoms"][2].update(text="The line is active", entity_refs=["L1"], time_refs=["t2"])
        for query in (literal(1), literal(2)):
            value["query"] = query
            self.assertEqual(self.evaluate(value).relation, "INSUFFICIENT")

    def test_unsupported_translation_never_produces_verdict(self):
        value = {"status": "UNSUPPORTED", "atoms": [], "facts": [], "rules": [], "query": None}
        self.assertEqual(self.evaluate(value).reason, "unsupported_translation")
        value["atoms"] = [atom(0)]
        with self.assertRaises(FormalValidationError):
            self.evaluate(value)

    def test_strict_shape_types_references_and_bounds(self):
        invalid = []
        for key, new in (("status", True), ("status", "formalized"), ("atoms", None),
                         ("facts", {}), ("query", None), ("rules", "r0")):
            value = program()
            value[key] = new
            invalid.append(value)
        value = program(); value["extra"] = "ignored"; invalid.append(value)
        value = program(); del value["facts"]; invalid.append(value)
        value = program(); value["atoms"] = [atom(i) for i in range(17)]; invalid.append(value)
        value = program(); value["atoms"].append(atom(0)); invalid.append(value)
        value = program(); value["facts"].append(fact(0)); invalid.append(value)
        value = program(); value["facts"][0]["literal"] = literal(99); invalid.append(value)
        value = program(); value["query"]["polarity"] = False; invalid.append(value)
        value = program(); value["atoms"][0]["entity_refs"] = [1]; invalid.append(value)
        value = program(); value["atoms"][0]["time_refs"] = ["t1", "t1"]; invalid.append(value)
        value = program(); value["rules"][0]["conditions"] = []; invalid.append(value)
        value = program(); value["rules"][0]["conditions"] *= 2; invalid.append(value)
        value = program(); value["rules"][0]["direction"] = "eval"; invalid.append(value)
        value = program(); value["rules"] *= 9; invalid.append(value)
        value = program(); value["rules"] *= 2; invalid.append(value)
        value = program(); value["facts"][0]["sources"] = []; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(FormalValidationError):
                self.evaluate(value)

    def test_duplicate_keys_nonfinite_fenced_deep_and_oversize_json_rejected(self):
        valid = json.dumps(program())
        invalid = [valid.replace('"status": "FORMALIZED"', '"status":"FORMALIZED","status":"FORMALIZED"'),
                   valid.replace('"polarity": "POS"', '"polarity":NaN', 1),
                   valid.replace('"polarity": "POS"', '"polarity":Infinity', 1),
                   valid.replace('"atom_id": "a0"', '"atom_id":"a0","atom_id":"a0"', 1),
                   "```json\n" + valid + "\n```", valid + valid, "[]", None,
                   "[" * 2000 + "]" * 2000, "x" * (MAX_OUTPUT_CHARS + 1)]
        for raw in invalid:
            with self.assertRaises(FormalValidationError):
                evaluate_formalization(raw, EVIDENCE)

    def test_source_ids_and_exact_unique_quotes_checked(self):
        for citation in (source("missing"), source(quote="invented"),
                         source("observations", "is")):
            value = program()
            value["rules"][0]["sources"] = [citation]
            with self.assertRaises(FormalValidationError):
                self.evaluate(value)
        with self.assertRaises(FormalValidationError):
            evaluate_formalization(json.dumps(program()), EVIDENCE * 2)

    def test_manually_constructed_program_cannot_bypass_atom_limit(self):
        oversized = FormalProgram("FORMALIZED", tuple(Atom("a" + str(i), "x", (), ()) for i in range(17)),
                                  (), (), None)
        with self.assertRaises(FormalValidationError):
            solve(oversized)

    def test_code_like_atom_text_remains_inert(self):
        value = program()
        value["atoms"][0]["text"] = "__import__('os').system('do-not-run')"
        parsed = parse_formalization(json.dumps(value), EVIDENCE)
        self.assertEqual(parsed.atoms[0].text, value["atoms"][0]["text"])
        self.assertEqual(solve(parsed).relation, "FOLLOWS")

    def test_application_true_conditions_and_inactive_exception(self):
        result = self.apply(application())
        self.assertEqual(result.applicability, "APPLIES")
        self.assertEqual(result.fact_ids, ("f1", "f2", "f3"))
        self.assertEqual(result.scope, "consistency_of_supplied_application_record")

    def test_application_entity_or_time_mismatch_is_not_applicable(self):
        for field in ("entity_scope", "time_scope"):
            value = application()
            value[field] = "MISMATCH"
            value["applicability"] = "NOT_APPLIES"
            self.assertEqual(self.apply(value).reason, "scope_mismatch")

    def test_application_missing_condition_or_unknown_scope_remains_unknown(self):
        value = application()
        value["conditions"][1].update(status="UNKNOWN", fact_ids=[])
        value["applicability"] = "UNKNOWN"
        self.assertEqual(self.apply(value).applicability, "UNKNOWN")
        for field in ("entity_scope", "time_scope"):
            value = application()
            value[field] = "UNKNOWN"
            value["applicability"] = "UNKNOWN"
            self.assertEqual(self.apply(value).applicability, "UNKNOWN")

    def test_application_false_condition_or_true_exception_blocks_rule(self):
        for field, status in (("conditions", "FALSE"), ("exceptions", "TRUE")):
            value = application()
            value[field][0]["status"] = status
            value["applicability"] = "NOT_APPLIES"
            self.assertEqual(self.apply(value).applicability, "NOT_APPLIES")

    def test_application_unknown_exception_does_not_mean_no_exception(self):
        value = application()
        value["exceptions"][0].update(status="UNKNOWN", fact_ids=[])
        value["applicability"] = "UNKNOWN"
        self.assertEqual(self.apply(value).applicability, "UNKNOWN")

    def test_application_only_if_cannot_certify_conclusion(self):
        value = application()
        value["rule"]["direction"] = "ONLY_IF"
        with self.assertRaises(FormalValidationError):
            self.apply(value)
        value["applicability"] = "UNKNOWN"
        self.assertEqual(self.apply(value).applicability, "UNKNOWN")
        value["rule"]["direction"] = "IFF"
        value["applicability"] = "APPLIES"
        self.assertEqual(self.apply(value).applicability, "APPLIES")

    def test_application_invalid_records_and_inconsistent_outcomes_rejected(self):
        invalid = []
        value = application(); value["applicability"] = "NOT_APPLIES"; invalid.append(value)
        value = application(); value["extra"] = True; invalid.append(value)
        value = application(); value["conditions"][0]["fact_ids"] = ["missing"]; invalid.append(value)
        value = application(); value["conditions"][0]["fact_ids"] = []; invalid.append(value)
        value = application(); value["conditions"][0]["clause_quote"] = "not in rule"; invalid.append(value)
        value = application(); value["exceptions"][0]["id"] = "c1"; invalid.append(value)
        value = application(); value["facts"].append(copy.deepcopy(value["facts"][0])); invalid.append(value)
        value = application(); value["time_scope"] = True; invalid.append(value)
        value = application(); value["conditions"][0]["status"] = 1; invalid.append(value)
        value = application(); value["conditions"] = []; invalid.append(value)
        for value in invalid:
            with self.subTest(value=value), self.assertRaises(FormalValidationError):
                self.apply(value)

    def test_exported_schemas_reject_extra_fields_everywhere(self):
        def inspect(schema):
            if schema.get("type") == "object":
                self.assertIs(schema["additionalProperties"], False)
                self.assertEqual(set(schema["required"]), set(schema["properties"]))
                for child in schema["properties"].values():
                    inspect(child)
            if schema.get("type") == "array":
                self.assertIn("maxItems", schema)
                inspect(schema["items"])
            for child in schema.get("anyOf", []):
                inspect(child)
        inspect(FORMAL_SCHEMA)
        inspect(APPLICABILITY_SCHEMA)


if __name__ == "__main__":
    unittest.main()
