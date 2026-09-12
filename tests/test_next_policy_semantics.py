import unittest
from dataclasses import replace

from guardian_truth.next.policy_semantics import (
    DistinguishingWorld,
    PairwiseDecision,
    PairwiseOutcome,
    PolicyInterpretation,
    SemanticOutcome,
    build_candidate_pool,
    evaluate_distinguishing_worlds,
    generate_semantic_mutants,
    oracle_at_k,
    select_pairwise,
)
from guardian_truth.next.records import (
    IdentityConstraint,
    PolicyMeaning,
    PolicyModality,
    PolicyProvenance,
    PolicyQuantification,
    PolicySubject,
    RegulatedKind,
    RegulatedMatter,
    SemanticQualifier,
    SemanticUncertainty,
    Span,
    TemporalConstraint,
)


POLICY = "Agents must call after approval unless exempt."


def _meaning(modality=PolicyModality.REQUIREMENT):
    condition_start = POLICY.index("after approval")
    exception_start = POLICY.index("unless exempt")
    return PolicyMeaning(
        id="meaning:0",
        modality=modality,
        subject=PolicySubject("agent", "support agent"),
        regulated=RegulatedMatter(RegulatedKind.ACTION, "call", "support tool"),
        conditions=(SemanticQualifier(
            "after approval", Span("prompt", condition_start, condition_start + len("after approval")),
        ),),
        exceptions=(SemanticQualifier(
            "unless exempt", Span("prompt", exception_start, exception_start + len("unless exempt")),
        ),),
        temporal=TemporalConstraint("after", "approval"),
        identity_constraints=(IdentityConstraint("case", "owner", "equals", "requesting_user"),),
        quantification=PolicyQuantification("all"),
        uncertainty=SemanticUncertainty.CERTAIN,
        unsupported_reason="",
        provenance=PolicyProvenance(
            Span("prompt", 0, len(POLICY)), POLICY, 0, "test_fixture",
        ),
    )


def _interpretation(identifier, rank, modality=PolicyModality.REQUIREMENT):
    return PolicyInterpretation(identifier, (_meaning(modality),), (), "test_fixture", rank)


class PolicySemanticCandidateTests(unittest.TestCase):
    def test_pool_and_exact_oracle_at_k(self):
        pool = build_candidate_pool(POLICY, (
            _interpretation("phi0", 0, PolicyModality.REQUIREMENT),
            _interpretation("phi1", 1, PolicyModality.PROHIBITION),
            _interpretation("phi2", 2, PolicyModality.PERMISSION),
        ))
        gold = _interpretation("gold", 0, PolicyModality.PROHIBITION)
        result = oracle_at_k(pool, (gold,), ks=(1, 2, 4))
        self.assertEqual([False, True, True], [point.hit for point in result.points])
        self.assertEqual(1, result.first_match_rank)
        self.assertEqual("OFFLINE_DEVELOPMENT_DIAGNOSTIC", result.execution_mode)

    def test_pool_rejects_duplicate_semantics(self):
        with self.assertRaisesRegex(ValueError, "duplicate semantic"):
            build_candidate_pool(POLICY, (
                _interpretation("phi0", 0),
                _interpretation("phi1", 1),
            ))

    def test_pool_rejects_broken_provenance(self):
        meaning = _meaning()
        broken = replace(meaning, provenance=replace(
            meaning.provenance, source=Span("prompt", 0, 6), quote="Agents must",
        ))
        candidate = PolicyInterpretation("phi0", (broken,), (), "test_fixture", 0)
        with self.assertRaisesRegex(ValueError, "does not reproduce"):
            build_candidate_pool(POLICY, (candidate,))

    def test_pairwise_aggregation_is_validated_and_deterministic(self):
        pool = build_candidate_pool(POLICY, (
            _interpretation("phi0", 0, PolicyModality.REQUIREMENT),
            _interpretation("phi1", 1, PolicyModality.PROHIBITION),
            _interpretation("phi2", 2, PolicyModality.PERMISSION),
        ))
        result = select_pairwise(pool, (
            PairwiseDecision("phi0", "phi1", PairwiseOutcome.RIGHT, "better condition", "fixture"),
            PairwiseDecision("phi0", "phi2", PairwiseOutcome.LEFT, "better scope", "fixture"),
            PairwiseDecision("phi1", "phi2", PairwiseOutcome.LEFT, "better modality", "fixture"),
        ))
        self.assertEqual("phi1", result.selected_id)
        self.assertTrue(result.complete)
        self.assertEqual(result.required_pairs, result.compared_pairs)

        with self.assertRaisesRegex(ValueError, "duplicate pairwise"):
            select_pairwise(pool, (
                PairwiseDecision("phi0", "phi1", PairwiseOutcome.LEFT, "reason", "fixture"),
                PairwiseDecision("phi1", "phi0", PairwiseOutcome.RIGHT, "reason", "fixture"),
            ))


class PolicySemanticMutationTests(unittest.TestCase):
    def test_mutants_are_single_candidate_changes_and_parent_is_unchanged(self):
        reference = _interpretation("reference", 0)
        mutants = generate_semantic_mutants(reference)
        self.assertEqual(
            {"flip_modality", "drop_conditions", "drop_exceptions", "drop_temporal",
             "drop_identity", "alter_quantifier"},
            {mutant.operator for mutant in mutants},
        )
        self.assertEqual(PolicyModality.REQUIREMENT, reference.meanings[0].modality)
        self.assertTrue(reference.meanings[0].conditions)
        self.assertTrue(all(mutant.parent_interpretation_id == reference.id for mutant in mutants))

    def test_distinguishing_world_report_keeps_surviving_mutants_visible(self):
        reference = _interpretation("reference", 0)
        generated = generate_semantic_mutants(reference)
        mutants = tuple(
            mutant for mutant in generated if mutant.operator in {"flip_modality", "drop_identity"}
        )
        worlds = (DistinguishingWorld("w0", frozenset({"approved"}), "approval is present"),)

        def evaluator(interpretation, _world):
            if interpretation.meanings[0].modality is PolicyModality.PERMISSION:
                return SemanticOutcome.DOES_NOT_APPLY
            return SemanticOutcome.APPLIES

        report = evaluate_distinguishing_worlds(reference, mutants, worlds, evaluator)
        self.assertEqual(1, len(report.killed_mutant_ids))
        self.assertEqual(1, len(report.surviving_mutant_ids))
        self.assertEqual(0.5, report.mutation_score)
        self.assertIn("NOT_P4_P6_EVIDENCE", report.execution_mode)


if __name__ == "__main__":
    unittest.main()
