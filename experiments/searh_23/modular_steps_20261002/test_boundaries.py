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
        import json
        r = load_input()[0]
        g = graph_for(r)
        for mode in ('G2', 'G2-linear'):
            text = render(g, mode)
            for f in g['facts']:
                self.assertIn(f['id'], text)
                for quote in f['quotes']:
                    self.assertIn(json.dumps(quote['quote'], ensure_ascii=False), text)
        restored = {'facts': [], 'edges': []}
        for line in render(g, 'G2-linear').splitlines()[1:]:
            key, _, raw = line.partition(': ')
            if key in ('facts', 'edges'):
                restored[key].append(json.loads(raw))
            else:
                restored[key] = json.loads(raw)
        self.assertEqual(json.loads(render(g, 'G2')), restored)

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
        self.assertEqual(len({call.call_id for call in c.calls}), len(c.calls))
        self.assertEqual(len({result.call_id for result in c.results}), len(c.results))
        self.assertTrue(all(result.call_id in {call.call_id for call in c.calls} for result in c.results))
        self.assertTrue(all(call.index < converted['target_response']['index'] for call in c.calls))
        self.assertTrue(converted['catalog_complete'])
        self.assertFalse(any(call.tool == 'apply_change' for call in c.calls))

    def test_native_sequential_results_are_usable_after_pairing(self):
        from oracle_probe import oracle_case
        from guardian_truth.integration.contracts import facts_from_documented
        r = load_input(ids=['dev_latest::00'])[0]
        facts, assessments, issues = facts_from_documented(oracle_case(as_row(r)))
        self.assertGreater(len(facts), 1)
        self.assertEqual(len({f.fact.provenance.call_id for f in facts}), len({x.call_id for x in native_case(as_row(r)).results}))
        self.assertFalse(any('CALL_NOT_UNIQUELY_PRESENT' in str(x) for x in assessments))

    def test_sealed_gate_precedes_any_gold_read(self):
        import tempfile
        from pathlib import Path
        from unittest.mock import patch
        from score_dev import scoring_sources
        read = Path.read_bytes
        opened_gold = []
        def guarded_read(path):
            if path.name == 'sealed_gold.jsonl':
                opened_gold.append(str(path))
                raise AssertionError('gold must not be read before completion gates')
            return read(path)
        with tempfile.TemporaryDirectory() as directory, patch.object(Path, 'read_bytes', guarded_read):
            with self.assertRaisesRegex(ValueError, 'sealed_scoring_requires_frozen_shortlist'):
                scoring_sources(Path(directory), 'sealed')
        self.assertFalse(opened_gold)

    def test_ambiguous_transport_does_not_become_a_verified_fact(self):
        from oracle_probe import oracle_case
        from guardian_truth.integration.contracts import facts_from_documented
        row = load_input(ids=['dev_latest::00'])[0]
        prefix = row['prompt'].split('→ TOOL_CALL')[0]
        row = dict(row, prompt=prefix + '→ TOOL_CALL read_state: {"item_id":"E-70"}\n'
            '→ TOOL_CALL read_state: {"item_id":"E-70"}\n'
            '← TOOL_RESPONSE read_state: {"item_id":"E-70","active":true}\n'
            '← TOOL_RESPONSE read_state: {"item_id":"E-70","active":false}\n')
        converted = as_row(row)
        self.assertEqual(len(converted['source_pairing_issues']), 2)
        case = native_case(converted)
        self.assertFalse({r.call_id for r in case.results} & {c.call_id for c in case.calls})
        facts, _, _ = facts_from_documented(oracle_case(converted))
        self.assertFalse(facts)

    def test_scorer_rejects_duplicate_prediction_within_arm(self):
        from pathlib import Path
        from score_dev import score_arm
        r = load_input()[0]
        record = {'id': r['id'], 'source_sha256': source_sha(r), 'decision': 'UNKNOWN'}
        gold = {r['id']: {'label': 0, 'logical_group': 'synthetic_test'}}
        with self.assertRaisesRegex(ValueError, 'duplicate_case_within_one_arm'):
            score_arm([record, record], {r['id']: r}, gold, Path('synthetic/predictions.jsonl'), [r['id']])


if __name__ == '__main__':
    unittest.main()
