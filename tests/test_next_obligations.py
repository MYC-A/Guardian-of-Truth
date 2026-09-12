import unittest

from guardian_truth.next.obligations import compile_meaning
from guardian_truth.next.records import (
    PolicyMeaning, PolicyModality, PolicyProvenance, PolicyQuantification,
    PolicySubject, RegulatedKind, RegulatedMatter, SemanticQualifier,
    SemanticUncertainty, Span, TemporalConstraint,
)
from guardian_truth.next.solver import ObligationKind


def meaning(predicate="cancel_order", uncertainty=SemanticUncertainty.CERTAIN):
    return PolicyMeaning(
        "m1", PolicyModality.REQUIREMENT, PolicySubject("agent", "assistant"),
        RegulatedMatter(RegulatedKind.ACTION, predicate, "order"),
        (SemanticQualifier("user confirms", Span("prompt", 0, 13)),), (),
        TemporalConstraint("before", "database update", ""), (),
        PolicyQuantification("all"), uncertainty, "" if uncertainty is SemanticUncertainty.CERTAIN else "ambiguous",
        PolicyProvenance(Span("prompt", 0, 20), "source policy text", 0, "test"),
    )


class ObligationCompilerTests(unittest.TestCase):
    def test_open_vocabulary_is_compiled_for_audit_but_not_strictly_trusted(self):
        result = compile_meaning(meaning())
        self.assertFalse(result.strict_eligible)
        self.assertIn("regulated_predicate_not_in_trusted_registry", result.unsupported_reasons)
        self.assertIn(ObligationKind.PRECEDENCE, {item.kind for item in result.obligations})

    def test_registered_certain_predicate_can_be_strictly_eligible(self):
        result = compile_meaning(meaning(), trusted_predicates=frozenset({"cancel_order"}))
        self.assertTrue(result.strict_eligible)

    def test_ambiguous_model_meaning_never_becomes_strict(self):
        result = compile_meaning(meaning(uncertainty=SemanticUncertainty.AMBIGUOUS),
                                 trusted_predicates=frozenset({"cancel_order"}))
        self.assertFalse(result.strict_eligible)


if __name__ == "__main__":
    unittest.main()
