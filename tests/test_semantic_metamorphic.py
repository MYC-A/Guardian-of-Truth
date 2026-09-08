"""Independent mutation contracts and adversarial coverage-checker controls.

These test the test layer. A real semantic prototype must separately run through
run_metamorphic_suite; oracle fixtures here are not a parser quality measurement.
"""

from copy import deepcopy
import unittest

from guardian_truth.semantic_metamorphic import (
    assess_pair, check_coverage, evaluate_outer_coverage,
    find_information_witness, metamorphic_cases, run_metamorphic_suite,
)
from guardian_truth.semantic_feature_adapter import semantic_feature_view


def expected_views(case):
    return ({'features': {item.name: item.before[0] for item in case.features}},
            {'features': {item.name: item.after[0] for item in case.features}})


def source(text, quote):
    start = text.index(quote)
    return {'document': 'rule', 'start': start, 'end': start+len(quote), 'quote': quote}


class MetamorphicContractTests(unittest.TestCase):
    def test_real_prototype_adapter_is_measured_separately(self):
        report = run_metamorphic_suite(semantic_feature_view)
        self.assertEqual(report['cases'], 15)
        self.assertGreaterEqual(report['passed'], 12)

    def test_required_families_and_unique_ids(self):
        cases = metamorphic_cases()
        self.assertEqual(len(cases), 15)
        self.assertEqual(len({case.name for case in cases}), len(cases))
        required = {'arrival_departure', 'before_after', 'at_most_less_than', 'may_must',
                    'all_some', 'if_only_if', 'exception', 'pronoun_entity',
                    'stale_state', 'distractor_field', 'strict_inclusive', 'active_passive'}
        self.assertEqual({case.family for case in cases}, required)

    def test_expected_changes_pass_and_constant_views_fail_semantic_mutations(self):
        for case in metamorphic_cases():
            with self.subTest(case=case.name):
                before, after = expected_views(case)
                self.assertTrue(assess_pair(case, before, after)['passed'])
                if any(item.relation == 'different' for item in case.features):
                    self.assertFalse(assess_pair(case, before, before)['passed'])

    def test_same_final_label_does_not_mask_wrong_field(self):
        case = next(case for case in metamorphic_cases() if case.name == 'event_role_swap')
        before, after = expected_views(case)
        before['strict_verdict'] = after['strict_verdict'] = 'PROVED_VIOLATION'
        after['features']['field_binding'] = 'arrival_time'
        report = assess_pair(case, before, after)
        self.assertFalse(report['passed'])
        self.assertIn('field_binding:missing_expected_change', report['failures'])

    def test_numeric_boundary_has_a_deterministic_witness(self):
        # Equality, rather than a cherry-picked far-away input, exposes both flips.
        self.assertNotEqual(2 <= 2, 2 < 2)
        self.assertNotEqual(18 > 18, 18 >= 18)
        for name in ('cardinality_boundary', 'temporal_equality_boundary'):
            case = next(case for case in metamorphic_cases() if case.name == name)
            before, after = expected_views(case)
            after['features'] = before['features']
            self.assertFalse(assess_pair(case, before, after)['passed'])

    def test_only_if_direction_has_an_independent_truth_table_counterexample(self):
        condition, permission = True, False
        sufficient = (not condition) or permission
        necessary = (not permission) or condition
        self.assertFalse(sufficient)
        self.assertTrue(necessary)
        case = next(case for case in metamorphic_cases() if case.family == 'if_only_if')
        before, after = expected_views(case)
        after['features']['condition_direction'] = 'SUFFICIENT'
        self.assertFalse(assess_pair(case, before, after)['passed'])

    def test_invariance_cases_reject_distractor_and_stale_state_overwrite(self):
        changes = {'stale_state_insertion': ('current_state', 'CLOSED'),
                   'irrelevant_field_insertion': ('field_binding', 'departure_time'),
                   'missing_concept_with_distractor': ('field_binding', 'departure_time'),
                   'voice_invariance': ('patient', 'Agent')}
        for name, (feature, wrong) in changes.items():
            case = next(case for case in metamorphic_cases() if case.name == name)
            before, after = expected_views(case)
            after['features'][feature] = wrong
            self.assertFalse(assess_pair(case, before, after)['passed'])

    def test_unique_pronoun_cannot_always_abstain_ambiguous_one_cannot_force(self):
        for name, wrong in [('unambiguous_reference', 'UNRESOLVED'),
                            ('ambiguous_reference', 'Account A')]:
            case = next(case for case in metamorphic_cases() if case.name == name)
            before, after = expected_views(case)
            after['features']['entity_binding'] = wrong
            self.assertFalse(assess_pair(case, before, after)['passed'])

    def test_missing_features_and_boolean_numeric_confusion_fail(self):
        case = next(case for case in metamorphic_cases() if case.name == 'exception_addition')
        before, after = expected_views(case)
        after['features']['exception_present'] = 1
        self.assertFalse(assess_pair(case, before, after)['passed'])
        self.assertFalse(assess_pair(case, {}, {})['passed'])

    def test_runner_never_passes_expected_features_or_case_names_to_analyzer(self):
        received = []

        def always_missing(payload):
            received.append(payload)
            self.assertEqual(set(payload), {'text', 'schema', 'trace'})
            return {'features': {}}

        report = run_metamorphic_suite(always_missing)
        self.assertEqual(len(received), 30)
        self.assertEqual(report['failed'], 15)
        self.assertEqual(report['sensitivity'], 0)

    def test_analyzer_failures_stay_in_denominator(self):
        def broken(_):
            raise RuntimeError('not exposed')

        report = run_metamorphic_suite(broken)
        self.assertEqual(report['cases'], 15)
        self.assertEqual(report['failed'], 15)
        self.assertTrue(all(item['failures'] == ['analyzer_error'] for item in report['reports']))


class BidirectionalCoverageTests(unittest.TestCase):
    def setUp(self):
        self.text = 'Notify the customer unless consent is absent.'
        self.obligations = [
            {'id': 'o1', 'kind': 'ACTION', 'status': 'FORMALIZED', 'source': source(self.text, 'Notify')},
            {'id': 'o2', 'kind': 'EXCEPTION', 'status': 'HOLE', 'source': source(self.text, 'unless consent is absent')},
        ]
        self.nodes = [{'id': 'n1', 'source': source(self.text, 'Notify'), 'obligation_ids': ['o1']}]

    def test_structural_hole_is_accounted_for_but_not_claimed_formalized(self):
        report = check_coverage(self.text, self.obligations, ['o1', 'o2'], self.nodes)
        self.assertTrue(report['passed'])
        self.assertEqual(report['coverage'], 1)
        self.assertEqual(report['unresolved_ids'], ['o2'])
        self.assertFalse(report['all_discovered_formalized'])
        self.assertFalse(report['semantic_equivalence_proved'])

    def test_covering_all_tokens_does_not_hide_lost_exception(self):
        nodes = [{'id': 'n1', 'source': source(self.text, self.text), 'obligation_ids': ['o1']}]
        report = check_coverage(self.text, self.obligations, ['o1'], nodes)
        self.assertFalse(report['passed'])
        self.assertIn('o2:lost_construction', report['issues'])

    def test_provenance_alone_cannot_hide_an_invented_condition(self):
        nodes = self.nodes + [{'id': 'invented', 'source': source(self.text, 'consent'),
                              'obligation_ids': ['not_in_source_registry']}]
        report = check_coverage(self.text, self.obligations, ['o1', 'o2'], nodes)
        self.assertIn('node_invented_obligation', report['issues'])

    def test_status_claim_without_actual_ast_node_is_rejected(self):
        obligations = deepcopy(self.obligations)
        obligations[1]['status'] = 'FORMALIZED'
        report = check_coverage(self.text, obligations, ['o1', 'o2'], self.nodes)
        self.assertIn('o2:formalized_without_node', report['issues'])

    def test_source_quote_bounds_and_empty_registry(self):
        for changed in ({'quote': 'not the source'}, {'start': -1}, {'end': 999}, {'start': True}):
            nodes = deepcopy(self.nodes)
            nodes[0]['source'].update(changed)
            report = check_coverage(self.text, self.obligations, ['o1', 'o2'], nodes)
            self.assertIn('node_without_valid_source', report['issues'])
        report = check_coverage(self.text, [], [], [])
        self.assertIsNone(report['coverage'])
        self.assertFalse(report['all_discovered_formalized'])


class OuterCoverageTests(unittest.TestCase):
    def test_perfect_solver_over_wrong_single_ast_is_still_confident_wrong(self):
        admissible = [{'signature': 'arrival-after', 'verdict': 'NO_VIOLATION'}]
        outer = [{'signature': 'departure-after', 'verdict': 'VIOLATION'}]
        report = evaluate_outer_coverage(admissible, outer, 'PROVED_VIOLATION')
        self.assertEqual(report['formalization_coverage'], 0)
        self.assertTrue(report['confident_wrong'])
        self.assertTrue(report['strict_with_missing_interpretation'])

    def test_missing_interpretation_detected_even_if_accidental_label_matches(self):
        admissible = [{'signature': 'arrival-after', 'verdict': 'VIOLATION'}]
        outer = [{'signature': 'departure-after', 'verdict': 'VIOLATION'}]
        report = evaluate_outer_coverage(admissible, outer, 'PROVED_VIOLATION')
        self.assertTrue(report['confident_wrong'])
        self.assertFalse(report['opposite_admissible_verdict'])

    def test_working_subset_cannot_justify_strict_verdict_over_mixed_outer(self):
        outer = [{'signature': 'strict', 'verdict': 'VIOLATION'},
                 {'signature': 'inclusive', 'verdict': 'NO_VIOLATION'}]
        report = evaluate_outer_coverage(outer, outer, 'PROVED_VIOLATION', working=outer[:1])
        self.assertTrue(report['working_subset_outer'])
        self.assertTrue(report['strict_not_outer_invariant'])
        self.assertTrue(report['confident_wrong'])
        unresolved = evaluate_outer_coverage(outer, outer)
        self.assertFalse(unresolved['confident_wrong'])
        self.assertTrue(unresolved['unresolved'])

    def test_empty_space_is_not_a_vacuous_proof(self):
        admissible = [{'signature': 'rule', 'verdict': 'VIOLATION'}]
        report = evaluate_outer_coverage(admissible, [], 'PROVED_VIOLATION')
        self.assertTrue(report['empty_outer'])
        self.assertTrue(report['confident_wrong'])
        self.assertFalse(evaluate_outer_coverage([], [])['valid'])

    def test_admissible_invariant_and_unknown_reference_are_distinct(self):
        outer = [{'signature': {'field': 'arrival', 'op': 'GT'}, 'verdict': 'VIOLATION'}]
        report = evaluate_outer_coverage(outer, outer, 'PROVED_VIOLATION')
        self.assertFalse(report['confident_wrong'])
        self.assertEqual(report['formalization_coverage'], 1)
        working = [{'signature': 'made-up', 'verdict': 'VIOLATION'}]
        self.assertFalse(evaluate_outer_coverage(outer, outer, working=working)['working_subset_outer'])

    def test_same_available_catalog_cannot_decide_missing_arrival_time(self):
        worlds = [{'departure': 17, 'arrival': 19, 'violation': not (19 > 18)},
                  {'departure': 17, 'arrival': 16, 'violation': not (16 > 18)}]
        witness = find_information_witness(worlds, ('departure',))
        self.assertEqual(witness['projection'], {'departure': 17})
        self.assertEqual(witness['violation_values'], [False, True])
        self.assertIsNone(find_information_witness(worlds, ('departure', 'arrival')))
        with self.assertRaises(ValueError):
            find_information_witness(worlds, ('missing',))


if __name__ == '__main__':
    unittest.main()
