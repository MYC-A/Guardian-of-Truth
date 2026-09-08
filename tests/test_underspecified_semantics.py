import unittest

from guardian_truth.underspecified_semantics import (
    ExclusionConstraint, RepresentationNode, StandardFactors, analyze_rule,
    build_outer_space, check_bidirectional_coverage, classify_standard,
    counterfactual_factor_sensitivity, evaluate_structured_standard,
    information_insufficiency_witness, residual_invariant, solve_invariant,
    solve_guarded,
)


class UnderspecifiedSemanticsTests(unittest.TestCase):
    def test_only_if_and_constructions_are_registered_not_silently_lost(self):
        analysis = analyze_rule("Cancel only if status is pending and identity is verified.",
                                schema_fields=["status"])
        kinds = [item.kind for item in analysis.obligations]
        self.assertIn("CONDITION_DIRECTION", kinds)
        self.assertIn("CONNECTIVE", kinds)
        direction = next(x for x in analysis.obligations if x.kind == "CONDITION_DIRECTION")
        self.assertEqual(direction.alternatives, ("ONLY_IF",))

    def test_semantic_role_prevents_forced_nearest_timestamp_binding(self):
        correct = analyze_rule("The flight must arrive after the arrival time.",
                               schema_fields=["arrival_time", "departure_time"])
        arrival = next(x for x in correct.concepts if x.kind == "EVENT_TIME")
        self.assertEqual((arrival.binding_options, arrival.binding_status),
                         (("arrival_time",), "BOUND_VERIFIED"))
        missing = analyze_rule("The flight must arrive after the arrival time.",
                               schema_fields=["departure_time"])
        arrival = next(x for x in missing.concepts if x.kind == "EVENT_TIME")
        self.assertEqual((arrival.binding_options, arrival.binding_status),
                         ((), "UNBOUND_CONCEPT"))
        self.assertIn("UNBOUND_CONCEPT", missing.issues)
        wrong_entity = analyze_rule("Flight A must arrive after 18:00.",
                                    schema_fields=["flight_B_arrival_time"])
        arrival = next(x for x in wrong_entity.concepts if x.kind == "EVENT")
        self.assertEqual((arrival.binding_options, arrival.binding_status),
                         ((), "UNBOUND_CONCEPT"))

    def test_compound_and_otherwise_create_structural_not_value_holes(self):
        analysis = analyze_rule("Otherwise it may proceed. It must not expose data.")
        self.assertTrue(any(hole.level == "WHOLE_RULE" for hole in analysis.holes))
        self.assertTrue(any(item.kind == "DISCOURSE_ATTACHMENT" and item.status == "UNSUPPORTED"
                            for item in analysis.obligations))

    def test_two_sat_queries_produce_supervaluational_verdicts(self):
        analysis = analyze_rule("The action may run unless status is closed.")
        space = build_outer_space(analysis)
        exception = next(hole for hole in space.holes
                         if space.holes and hole.level == "SUBTREE" and "EXCEPTION" in hole.alternatives)
        result = solve_invariant(space, lambda item: item.get(exception.id) == "EXCEPTION")
        self.assertEqual((result.q1, result.q0, result.status),
                         ("SAT", "SAT", "UNRESOLVED"))
        constraint = ExclusionConstraint("x1", exception.id, ("IF_NOT",),
                                         exception.source, "explicit exception scope",
                                         (), "EXACT")
        result = solve_invariant(build_outer_space(analysis, [constraint]),
                                 lambda item: item.get(exception.id) == "EXCEPTION")
        self.assertEqual(result.status, "PROVED_VIOLATION")

    def test_revision_can_expand_outer_and_invalidate_determinacy(self):
        analysis = analyze_rule("It must not run.")
        hole = next(h for h in analysis.holes if h.level == "SUBTREE")
        excluded = tuple(x for x in hole.alternatives if x != hole.alternatives[0])
        rule = ExclusionConstraint("scope", hole.id, excluded, hole.source,
                                   "temporary scope decision", ("same clause",), "HEURISTIC")
        narrowed = build_outer_space(analysis, [rule])
        # A heuristic may focus working search but can never remove an outer reading.
        self.assertEqual(narrowed.width(), narrowed.revise("scope").width())
        self.assertLessEqual(len(narrowed.working()), narrowed.width())

    def test_revision_transitively_invalidates_dependent_constraints(self):
        analysis = analyze_rule("It must not run.")
        hole = analysis.holes[0]
        first = ExclusionConstraint("premise", hole.id, (hole.alternatives[1],),
                                    hole.source, "first premise", (), "EXACT")
        residual = next(item for item in analysis.holes if item.level == "WHOLE_RULE")
        dependent = ExclusionConstraint("conclusion", residual.id,
                                        (residual.alternatives[1],), residual.source,
                                        "depends on first premise", (), "VERIFIED_DERIVATION",
                                        dependencies=("premise",))
        space = build_outer_space(analysis, [first, dependent])
        revised = space.revise("premise")
        self.assertGreater(revised.width(), space.width())
        self.assertFalse(next(item for item in revised.constraints
                              if item.id == "conclusion").active)

    def test_hard_revision_expands_outer(self):
        analysis = analyze_rule("It must not run.")
        hole = next(h for h in analysis.holes if h.level == "SUBTREE")
        excluded = tuple(x for x in hole.alternatives if x != hole.alternatives[0])
        rule = ExclusionConstraint("scope", hole.id, excluded, hole.source,
                                   "grammar fixes local scope", (), "EXACT")
        narrowed = build_outer_space(analysis, [rule])
        self.assertLess(narrowed.width(), narrowed.revise("scope").width())

    def test_bidirectional_coverage_detects_lost_and_invented_meaning(self):
        analysis = analyze_rule("Run only if A and B.")
        first = analysis.obligations[0].id
        report = check_bidirectional_coverage(
            analysis, [RepresentationNode("n0", "condition", (first,)),
                       RepresentationNode("invented", "extra", ())], [first])
        self.assertFalse(report.complete)
        self.assertTrue(report.lost_obligations)
        self.assertEqual(report.invented_nodes, ("invented",))

    def test_strict_solver_is_gated_by_bidirectional_coverage(self):
        analysis = analyze_rule("Run only if A and B.")
        space = build_outer_space(analysis)
        result = solve_guarded(analysis, (), (), space, lambda _: True)
        self.assertEqual((result.status, result.reason),
                         ("UNRESOLVED", "coverage_incomplete"))
        nodes = tuple(RepresentationNode(f"n{i}", obligation.kind, (obligation.id,))
                      for i, obligation in enumerate(analysis.obligations))
        ids = tuple(obligation.id for obligation in analysis.obligations)
        result = solve_guarded(analysis, nodes, ids, space, lambda _: True)
        self.assertEqual(result.status, "PROVED_VIOLATION")

    def test_coverage_cannot_be_faked_by_accounted_ids_or_swapped_space(self):
        analysis = analyze_rule("Run only if A and B.")
        ids = tuple(item.id for item in analysis.obligations)
        result = solve_guarded(analysis, (), ids, build_outer_space(analysis), lambda _: True)
        self.assertEqual((result.status, result.reason),
                         ("UNRESOLVED", "coverage_incomplete"))
        nodes = tuple(RepresentationNode(f"n{i}", item.kind, (item.id,))
                      for i, item in enumerate(analysis.obligations))
        from guardian_truth.underspecified_semantics import InterpretationSpace
        result = solve_guarded(analysis, nodes, ids, InterpretationSpace(()), lambda _: True)
        self.assertEqual((result.status, result.reason),
                         ("UNRESOLVED", "space_mismatch"))

    def test_cross_family_overlap_keeps_negation_inside_exception(self):
        analysis = analyze_rule("Notify unless consent is not available.")
        kinds = [item.kind for item in analysis.obligations]
        self.assertIn("EXCEPTION", kinds)
        self.assertIn("NEGATION", kinds)

    def test_unrecognized_rule_cannot_disappear_without_whole_rule_residual(self):
        analysis = analyze_rule("Frobnicate the ledger prudently.")
        residual = next(item for item in analysis.obligations
                        if item.kind == "SEMANTIC_RESIDUAL")
        hole = next(item for item in analysis.holes
                    if item.obligation_id == residual.id)
        self.assertEqual(hole.level, "WHOLE_RULE")

    def test_working_preferences_and_heuristics_cannot_change_strict_verdict(self):
        analysis = analyze_rule("It must not run.")
        space = build_outer_space(analysis, working_preferences={
            analysis.holes[0].id: analysis.holes[0].alternatives[0]})
        before = solve_invariant(space, lambda _: True)
        after = solve_invariant(build_outer_space(analysis), lambda _: True)
        self.assertEqual(before.status, after.status)

    def test_width_limit_and_empty_space_are_not_compliance(self):
        analysis = analyze_rule("It must not run.")
        self.assertEqual(solve_invariant(build_outer_space(analysis), lambda _: True,
                                         limit=1).status,
                         "COMPUTATION_UNRESOLVED")
        hole = analysis.holes[0]
        empty = ExclusionConstraint("empty", hole.id, hole.alternatives, hole.source,
                                    "contradictory exact experiment", (), "EXACT")
        self.assertEqual(solve_invariant(build_outer_space(analysis, [empty]),
                                         lambda _: False).status,
                         "EMPTY_SPACE")

    def test_non_boolean_evaluator_result_cannot_become_proof(self):
        analysis = analyze_rule("It must not run.")
        space = build_outer_space(analysis)
        result = solve_invariant(space, lambda item: True if item.choices[0][1]
                                  == analysis.holes[0].alternatives[0] else 0)
        self.assertEqual((result.status, result.reason),
                         ("COMPUTATION_UNRESOLVED", "invalid_evaluator_result"))

    def test_obligation_limit_cannot_produce_strict_verdict(self):
        analysis = analyze_rule(" ".join(["not"] * 80))
        self.assertIn("obligation_limit", analysis.issues)
        result = solve_guarded(analysis, (), (), build_outer_space(analysis),
                               lambda _: True)
        self.assertEqual((result.status, result.reason),
                         ("UNRESOLVED", "analysis_incomplete"))

    def test_equal_catalog_projection_can_hide_opposite_verdicts(self):
        worlds = [
            {"action": "resume", "line": "L1", "contract_expired": True, "violation": True},
            {"action": "resume", "line": "L1", "contract_expired": False, "violation": False},
        ]
        witness = information_insufficiency_witness(worlds, ["action", "line"], "violation")
        self.assertTrue(witness.found)
        self.assertEqual(witness.projection, {"action": "resume", "line": "L1"})

    def test_residual_is_skipped_only_when_verdict_is_invariant(self):
        self.assertEqual(residual_invariant(lambda residual: True or residual).status,
                         "PROVED_VIOLATION")
        self.assertEqual(residual_invariant(lambda residual: residual).status,
                         "UNRESOLVED")

    def test_structured_standard_has_asymmetric_unknown_and_counterfactual(self):
        factors = StandardFactors(True, True, True, True, False, False)
        self.assertEqual(classify_standard("respect the client's explicit preference"),
                         "STRUCTURED_STANDARD")
        self.assertEqual(evaluate_structured_standard(factors), "PROVED_VIOLATION")
        self.assertTrue(counterfactual_factor_sensitivity(factors, "feasible_alternative"))
        unknown = StandardFactors(True, True, True, None, False, False)
        self.assertEqual(evaluate_structured_standard(unknown), "UNRESOLVED")
        override_only = StandardFactors(None, None, None, None, None, True)
        self.assertEqual(evaluate_structured_standard(override_only),
                         "NO_EXPLICIT_VIOLATION_FOUND")
        self.assertEqual(classify_standard("act reasonably in unusual circumstances"),
                         "OPEN_TEXTURED")


if __name__ == "__main__":
    unittest.main()
