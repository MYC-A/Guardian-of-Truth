"""Meaningful invariants: trust defects, closed-world leakage, graph parity."""
import unittest
from modular_common import exact_quotes, load_input, source_sha
from evidence_views import graph_for, render, GraphAPI, information_hash
from v2_pipeline import as_row, native_case


class BoundaryTests(unittest.TestCase):
    def test_timezone_arithmetic_retains_exact_sources(self):
        from typed_calculations import timestamps
        row = load_input(ids=['dev_inclusive_timezone::02'])[0]
        result = timestamps(row)
        self.assertTrue(result['relations'])
        self.assertTrue(any(abs(r['delta_seconds']) == 1 for r in result['relations']))
        for relation in result['relations']:
            for field in ('left_source', 'right_source'):
                self.assertTrue(exact_quotes([relation[field]], {'prompt': row['prompt']}))
        self.assertEqual(result['decision'], 'ADVISORY_ONLY_NOT_AUTOMATIC_ERROR')

    def test_sampler_rejects_tuple_content_before_transport(self):
        from selfcheck_adapter import sample_bank
        class NoTransport:
            def chat(self, *args, **kwargs):
                self.fail('must not call provider')
        with self.assertRaises(ValueError):
            sample_bank(NoTransport(), 'unused', [{'role': 'user', 'content': ('text', None)}], caller='test')

    def test_rule_and_goal_are_not_observed_facts(self):
        from translator_pilot import trust_issues
        row = load_input()[0]
        quote = row['prompt'].split('⟦SYSTEM⟧\n')[1].split('\n')[0]
        proposed = {'facts': [{'sources': [{'source_id': 'prompt', 'quote': quote}]}]}
        self.assertTrue(any('not_preceding_observation' in issue for issue in trust_issues(proposed, row)))

    def test_every_quote_not_just_first(self):
        self.assertFalse(exact_quotes([{'source_id': 'prompt', 'quote': 'valid'},
                                      {'source_id': 'prompt', 'quote': 'invented'}], {'prompt': 'valid'}))
        self.assertFalse(exact_quotes([{'source_id': 'prompt', 'quote': ''}], {'prompt': 'valid'}))
        self.assertFalse(exact_quotes([{'source_id': 'target', 'quote': 'completed'}], {'prompt': 'not completed'}))

    def test_target_never_observation_and_content_identity(self):
        a = load_input()[0]
        b = dict(a, response='For item E-70, active is true.')
        self.assertNotEqual(source_sha(a), source_sha(b))
        graph = graph_for(a)
        self.assertTrue(all(q['source_id'] == 'prompt' for f in graph['facts'] for q in f['quotes']))
        self.assertTrue(all('OBSERVED_PAYLOAD_ONLY' in f['epistemic_status'] for f in graph['facts']))

    def test_graph_and_linear_same_facts_quotes(self):
        r = load_input()[0]
        g = graph_for(r)
        for mode in ('G2', 'G2-linear'):
            text = render(g, mode)
            for f in g['facts']:
                self.assertIn(f['id'], text)
                for quote in f['quotes']:
                    import json
                    self.assertIn(json.dumps(quote['quote'], ensure_ascii=False), text)
        self.assertEqual(information_hash(g), information_hash(g))

    def test_query_limit_no_tool_execution(self):
        api = GraphAPI(graph_for(load_input()[0]))
        self.assertEqual(api.query({'op': 'apply_change'})['status'], 'INVALID_QUERY')
        for _ in range(3):
            self.assertEqual(api.query({'op': 'requirements'})['status'], 'OK')
        self.assertEqual(api.query({'op': 'observations'})['status'], 'LIMIT_REACHED')

    def test_pairing_entities_and_target_exclusion(self):
        r = load_input(ids=['dev_latest::00'])[0]
        converted = as_row(r)
        c = native_case(converted)
        self.assertEqual(len(c.calls), len(c.results))
        self.assertTrue(all(result.call_id in {call.call_id for call in c.calls} for result in c.results))
        self.assertTrue(all(call.index < converted['target_response']['index'] for call in c.calls))
        self.assertTrue(converted['catalog_complete'])
        self.assertFalse(any(call.tool == 'apply_change' for call in c.calls))


if __name__ == '__main__':
    unittest.main()
