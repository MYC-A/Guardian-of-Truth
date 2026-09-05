import json
import unittest

from guardian_truth.parsing import parse_events
from guardian_truth.pipeline import Detector
from guardian_truth.provenance import build_graph


def result(value, name='lookup', role='assistant'):
    return f'⟦TOOL_RESULT name="{name}" requestor="{role}"⟧\n' + json.dumps(value) + '\n'


def call(value, name='update', role='assistant'):
    return f'⟦{role.upper()}_TOOL_CALL name="{name}"⟧\n' + json.dumps(value) + '\n'


def graph(prompt, response, **kwargs):
    return build_graph(parse_events(prompt, 'prompt'), parse_events(response, 'response'), **kwargs)


def trace(g, path):
    return next(t for t in g.arguments if t.path == path)


class ProvenanceTests(unittest.TestCase):
    def test_same_value_wrong_owner_is_not_support(self):
        prompt = result({'user_id': 'B', 'payment_id': 'P'})
        g = graph(prompt, call({'user_id': 'A', 'payment_id': 'P'}))
        t = trace(g, ['payment_id'])
        self.assertEqual(t.status, 'scope_conflict')
        self.assertFalse(t.supporting)
        self.assertTrue(t.alternatives)
        # No semantic rule says whether this call can use another user's payment.
        self.assertEqual(Detector().review(prompt, call({'user_id':'A', 'payment_id':'P'})).status, 'unknown')

    def test_changing_owner_changes_trace(self):
        prompt = result({'user_id':'B', 'payment_id':'P'})
        g = graph(prompt, call({'user_id':'B', 'payment_id':'P'}))
        self.assertEqual(trace(g, ['payment_id']).status, 'observed_match')

    def test_history_retains_versions(self):
        prompt = result({'order_id':'A', 'status':'pending'}) + result({'order_id':'A', 'status':'delivered'})
        g = graph(prompt, call({'order_id':'A', 'status':'pending'}))
        t = trace(g, ['status'])
        self.assertEqual(t.status, 'older_observation_match')
        facts = [f for f in g.facts if f.field == 'status']
        self.assertEqual([f.value for f in facts], ['pending','delivered'])
        self.assertEqual(facts[1].previous, [facts[0].id])
        self.assertIn(facts[1].id, t.alternatives)

    def test_change_request_is_not_a_violation(self):
        prompt = result({'order_id':'A', 'status':'pending'})
        response = call({'order_id':'A', 'status':'cancelled'})
        self.assertEqual(trace(graph(prompt, response), ['status']).status, 'different_observed_value')
        self.assertEqual(Detector().review(prompt, response).status, 'unknown')

    def test_different_entities_do_not_replace_each_other(self):
        prompt = result({'order_id':'A', 'status':'pending'}) + result({'order_id':'B', 'status':'done'})
        g = graph(prompt, call({'order_id':'A', 'status':'pending'}))
        self.assertEqual(trace(g, ['status']).status, 'observed_match')
        self.assertFalse(any(f.previous for f in g.facts))

    def test_array_reordering_preserves_identity(self):
        first = [{'order_id':'A','status':'pending'}, {'order_id':'B','status':'done'}]
        second = [{'order_id':'B','status':'done'}, {'order_id':'A','status':'cancelled'}]
        g = graph(result(first) + result(second), call({'order_id':'A','status':'pending'}))
        self.assertEqual(trace(g, ['status']).status, 'older_observation_match')
        status = [f for f in g.facts if f.value == 'cancelled'][0]
        self.assertEqual(status.path, [1, 'status'])
        self.assertEqual(status.previous, ['f1'])

    def test_anonymous_array_elements_not_merged(self):
        prompt = result({'user_id':'A', 'items':[{'price':1}, {'price':2}]})
        prompt += result({'user_id':'A', 'items':[{'price':2}, {'price':1}]})
        g = graph(prompt, call({'user_id':'A','price':1}))
        self.assertTrue(all(not f.versioned and not f.previous for f in g.facts if f.field == 'price'))
        self.assertNotEqual(trace(g, ['price']).status, 'older_observation_match')

    def test_duplicate_identity_in_one_result_is_ambiguous(self):
        prompt = result([{'order_id':'A','status':'pending'}, {'order_id':'A','status':'done'}])
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertFalse(any(f.previous for f in g.facts))
        self.assertEqual(trace(g, ['status']).status, 'ambiguous_history')

    def test_result_omission_is_not_deletion(self):
        prompt = result({'order_id':'A','status':'pending'}) + result({'order_id':'A','price':9})
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertEqual(trace(g, ['status']).status, 'observed_match')

    def test_different_tools_or_roles_not_one_timeline(self):
        prompt = result({'order_id':'A','status':'pending'}, name='lookup')
        prompt += result({'order_id':'A','status':'done'}, name='update')
        prompt += result({'order_id':'A','status':'done'}, name='lookup', role='user')
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertFalse(any(f.previous for f in g.facts))

    def test_unambiguous_pair_supplies_scope_and_source(self):
        prompt = call({'order_id':'A'}, name='lookup') + result({'status':'pending'})
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertEqual(trace(g, ['status']).status, 'observed_match')
        self.assertEqual(len(g.facts[0].sources), 2)
        self.assertEqual(g.facts[0].entities[0].value, 'A')

    def test_parallel_same_tool_results_not_guessed(self):
        prompt = call({'order_id':'A'}, name='lookup') + call({'order_id':'B'}, name='lookup')
        prompt += result({'status':'pending'}) + result({'status':'done'})
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertIn('ambiguous_call_result_pair', g.issues)
        self.assertTrue(all(not f.entities for f in g.facts))
        self.assertEqual(trace(g, ['status']).status, 'unscoped_match')

    def test_conflicting_pair_does_not_inject_scope(self):
        prompt = call({'order_id':'A','user_id':'U'}, name='lookup')
        prompt += result({'order_id':'B','status':'pending'})
        g = graph(prompt, call({'order_id':'A','status':'pending'}))
        self.assertIn('request_result_identity_conflict', g.issues)
        self.assertTrue(all(all(e.field != 'user_id' for e in f.entities) for f in g.facts))
        self.assertEqual(trace(g, ['status']).status, 'scope_conflict')

    def test_flight_dates_separate_timelines(self):
        prompt = result({'flight_number':'F1','date':'2025-01-01','status':'done'})
        prompt += result({'flight_number':'F1','date':'2025-01-02','status':'pending'})
        g = graph(prompt, call({'flight_number':'F1','date':'2025-01-01','status':'done'}))
        self.assertFalse(any(f.previous for f in g.facts))
        self.assertEqual(trace(g, ['status']).status, 'observed_match')

    def test_search_date_is_inherited_when_result_omits_it(self):
        prompt = call({'date':'2025-01-01'}, name='lookup')
        prompt += result([{'flight_number':'F1','price':10}])
        prompt += call({'date':'2025-01-02'}, name='lookup')
        prompt += result([{'flight_number':'F1','price':20}])
        response = call({'flight_number':'F1','date':'2025-01-01','price':10})
        g = graph(prompt, response)
        self.assertFalse(any(f.previous for f in g.facts))
        self.assertEqual(trace(g, ['price']).status, 'observed_match')
        self.assertEqual({e.value for e in g.facts[0].entities if e.field == 'date'}, {'2025-01-01'})

    def test_date_alone_does_not_identify_a_result_entity(self):
        prompt = result({'date':'2025-01-01','price':10}) + result({'date':'2025-01-01','price':20})
        g = graph(prompt, call({'date':'2025-01-01','price':10}))
        self.assertFalse(any(f.versioned for f in g.facts))

    def test_identical_value_under_other_field_is_not_support(self):
        g = graph(result({'order_id':'A','refund':10}), call({'order_id':'A','price':10}))
        self.assertEqual(trace(g, ['price']).status, 'not_observed')

    def test_scalar_types_are_not_coerced(self):
        g = graph(result({'order_id':'A','amount':1}), call({'order_id':'A','amount':True}))
        self.assertEqual(trace(g, ['amount']).status, 'different_observed_value')

    def test_free_text_and_candidate_results_are_not_facts(self):
        prompt = '⟦ASSISTANT⟧\n{"order_id":"A","status":"done"}'
        response = result({'order_id':'A','status':'done'}) + call({'order_id':'A','status':'done'})
        g = graph(prompt, response)
        self.assertFalse(g.facts)
        self.assertTrue(all(t.status == 'not_observed' for t in g.arguments))

    def test_all_argument_leaves_have_trace(self):
        response = call({'items':[{'item_id':'1','amount':3},{'item_id':'2','amount':4}], 'flag':None})
        g = graph('', response)
        self.assertEqual(len(g.arguments), 5)

    def test_user_calls_are_not_candidate_arguments(self):
        self.assertFalse(graph('', call({'order_id':'A'}, role='user')).arguments)

    def test_truncation_is_explicit_and_graph_references_valid(self):
        prompt = result({'order_id':'A','status':'done'}) * 4
        response = call({'order_id':'A','status':'done'})
        g = graph(prompt, response, max_links=2)
        t = trace(g, ['status'])
        self.assertTrue(t.truncated)
        self.assertEqual(len(t.supporting), 2)
        ids = {f.id for f in g.facts}
        for fact in g.facts:
            self.assertTrue(set(fact.previous) <= ids)
            for s in fact.sources:
                self.assertEqual(s.document, 'prompt')
                self.assertTrue(0 <= s.start < s.end <= len(prompt))
        for argument in g.arguments:
            self.assertTrue(set(argument.supporting + argument.alternatives) <= ids)
            self.assertTrue(0 <= argument.source.start < argument.source.end <= len(response))

    def test_provenance_can_be_disabled(self):
        review = Detector(enabled={'schema'}).review(result({'order_id':'A'}), call({'order_id':'A'}))
        self.assertFalse(review.graph.facts)
        self.assertNotIn('provenance', review.checks_run)


if __name__ == '__main__':
    unittest.main()
