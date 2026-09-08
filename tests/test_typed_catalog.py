"""Exact provenance and conservative typing for model-blind catalog extraction."""

import json
import unittest
from unittest.mock import patch

from guardian_truth.typed_catalog import extract_typed_catalog, select_rule_catalog


class TypedCatalogTests(unittest.TestCase):
    def assert_sources(self, catalog, prompt, response=''):
        for item in catalog.items:
            text = prompt if item.source.document == 'prompt' else response
            self.assertGreaterEqual(item.source.start, 0)
            self.assertGreater(item.source.end, item.source.start)
            self.assertLessEqual(item.source.end, len(text))
            if item.kind == 'TextSpan':
                self.assertEqual(item.value, text[item.source.start:item.source.end])
            elif item.metadata.get('structured'):
                self.assertEqual(json.loads(text[item.source.start:item.source.end]), item.value)

    def test_structured_values_have_exact_paths_and_token_spans(self):
        prompt = '⟦TOOL_RESULT name="lookup" requestor="assistant"⟧\n' + json.dumps({
            'records': [{'record_id': 'R-1', 'date': '2031-03-24', 'amount': 24.5,
                         'currency': 'EUR', 'status': 'ACTIVE', 'enabled': True},
                        {'record_id': 'R-2', 'amount': 9, 'description': 'quote " and slash \\'}]},
            ensure_ascii=False)
        result = extract_typed_catalog(prompt)
        self.assertTrue(result.complete, result.issues)
        self.assert_sources(result, prompt)
        ids = [item for item in result.items if item.kind == 'EntityID']
        self.assertEqual([item.value for item in ids], ['R-1', 'R-2'])
        self.assertEqual(ids[1].path, ('records', 1, 'record_id'))
        self.assertEqual(ids[1].authority, 'tool_observation')
        self.assertEqual([item.value for item in result.items if item.kind == 'Number'], [24.5, 9])
        self.assertEqual([item.value for item in result.items if item.kind == 'Date'], ['2031-03-24'])
        self.assertEqual([item.value for item in result.items if item.kind == 'Currency'], ['EUR'])
        self.assertIn(True, [item.value for item in result.items if item.kind == 'State'])

    def test_candidate_actions_distinct_from_observations_and_historical_calls(self):
        prompt = '⟦ASSISTANT⟧\n→ TOOL_CALL lookup: {"id":"R1"}\n← TOOL_RESPONSE lookup: {"status":"ACTIVE"}'
        response = '⟦ASSISTANT⟧\n→ TOOL_CALL close: {"id":"R1"}\n← TOOL_RESPONSE close: {"status":"CLOSED"}'
        result = extract_typed_catalog(prompt, response)
        self.assert_sources(result, prompt, response)
        actions = [item for item in result.items if item.kind == 'Action']
        self.assertEqual([item.authority for item in actions], ['historical_assistant_action', 'candidate_action'])
        self.assertEqual([item.metadata['candidate'] for item in actions], [False, True])
        closed = next(item for item in result.items if item.kind == 'State' and item.value == 'CLOSED')
        self.assertEqual(closed.authority, 'candidate_claim')
        argument = next(item for item in result.items if item.kind == 'EntityID' and item.source.document == 'response')
        self.assertEqual(argument.metadata['action_id'], actions[1].id)

    def test_schema_declarations_require_actual_system_event(self):
        schema = '[AVAILABLE TOOLS]\n- update — Update an object\n  object_id: string!\n  data: object\n    state: string [enum: ACTIVE|CLOSED]\n'
        prompt = '⟦SYSTEM⟧\n' + schema + '\n⟦USER⟧\n' + schema
        response = '⟦SYSTEM⟧\n' + schema
        result = extract_typed_catalog(prompt, response)
        declared = [item for item in result.items if item.metadata.get('declaration')]
        self.assertEqual(len(declared), 4)
        self.assertTrue(all(item.authority == 'system_tool_schema' and item.source.document == 'prompt' for item in declared))
        state = next(item for item in declared if item.value == 'state')
        self.assertEqual(state.path, ('data', 'state'))
        self.assertEqual(state.metadata['enum'], ['ACTIVE', 'CLOSED'])
        self.assert_sources(result, prompt, response)

    def test_ids_and_booleans_never_become_numbers(self):
        values = {'user_id': 1234, 'flight_number': 765, 'order_number': '0098',
                  'zip': '00123', 'item_ids': ['12', '13'], 'enabled': True, 'amount': 12}
        prompt = '⟦USER⟧\n' + json.dumps(values)
        result = extract_typed_catalog(prompt)
        numbers = [item for item in result.items if item.kind == 'Number']
        self.assertEqual([item.value for item in numbers], [12])
        self.assertEqual(numbers[0].path, ('amount',))
        self.assertEqual(len([item for item in result.items if item.kind == 'EntityID']), 6)
        self.assert_sources(result, prompt)

    def test_text_dates_numbers_and_units_are_candidates_only(self):
        prompt = '⟦SYSTEM⟧\nOnly one tool call. On 2031-03-24 pay $25 or 30 EUR; limit 20%. Status ACTIVE.'
        result = extract_typed_catalog(prompt)
        self.assert_sources(result, prompt)
        numbers = [item for item in result.items if item.kind == 'Number']
        self.assertEqual(sorted(item.value for item in numbers), [1, 20, 25, 30])
        self.assertTrue(all(not item.metadata['arithmetic_operand_verified'] for item in numbers))
        self.assertTrue(next(item for item in numbers if item.value == 20).metadata['percent'])
        self.assertEqual(next(item for item in numbers if item.value == 30).metadata['unit'], 'EUR')
        dollar = next(item for item in result.items if item.kind == 'Currency' and item.value == '$')
        self.assertTrue(dollar.metadata['symbol_ambiguous'])
        self.assertEqual(len([item for item in result.items if item.kind == 'Date']), 1)

    def test_policy_mentions_features_and_clause_spans_are_lexical_only(self):
        prompt = ('⟦SYSTEM⟧\nIf any status is "Poor", you must call `disconnect_vpn()`; '
                  'otherwise some requests may continue.')
        result = extract_typed_catalog(prompt)
        self.assertEqual([x.value for x in result.items if x.kind == 'PolicyActionMention'],
                         ['disconnect_vpn'])
        self.assertIn('Poor', [x.value for x in result.items if x.kind == 'EnumValue'])
        self.assertIn('must', [x.value for x in result.items if x.kind == 'Modality'])
        self.assertIn('some', [x.value for x in result.items if x.kind == 'Quantifier'])
        spans = [x for x in result.items if x.kind == 'TextSpan']
        self.assertGreaterEqual(len(spans), 2)
        self.assert_sources(result, prompt)

    def test_rule_catalog_keeps_local_spans_and_lexically_linked_schema(self):
        policy = "An order can only be cancelled if its status is 'pending'."
        prompt = ('⟦SYSTEM⟧\n' + policy + '\n[AVAILABLE TOOLS]\n'
                  '- cancel_order — cancel\n  order_id: string!\n  status: string\n'
                  '- unrelated — other\n  noise: string\n')
        whole = extract_typed_catalog(prompt)
        start = prompt.index(policy); end = start + len(policy)
        selected = select_rule_catalog(whole, prompt, start, end)
        self.assertTrue(selected.complete, selected.issues)
        self.assertTrue(all((x.kind == 'TextSpan' and x.source.start < end
                             and x.source.end > start)
                            or start <= x.source.start < x.source.end <= end
                            or x.metadata.get('declaration') for x in selected.items))
        values = {x.value for x in selected.items if x.metadata.get('declaration')}
        self.assertIn('cancel_order', values)
        self.assertIn('status', values)
        self.assertNotIn('unrelated', values)

    def test_opaque_text_tokens_and_invalid_dates_do_not_leak_numbers(self):
        prompt = '⟦USER⟧\nA123 1.2.3 user123@example.com https://x.test/23 1234567890 1,234 2031-02-31'
        result = extract_typed_catalog(prompt)
        self.assertFalse(any(item.kind in {'Number', 'Date'} for item in result.items))
        result = extract_typed_catalog('⟦USER⟧\n00123')
        self.assertEqual([item.value for item in result.items if item.kind == 'Number'], [123])
        self.assertTrue(all(not item.metadata.get('arithmetic_operand_verified', False) for item in result.items))
        result = extract_typed_catalog('⟦USER⟧\nLimit 2. A total of 4.5.')
        self.assertEqual([item.value for item in result.items if item.kind == 'Number'], [2, 4.5])

    def test_invalid_structured_data_does_not_generate_partial_facts(self):
        for body in ('{"amount":1,"amount":2}', '{"amount": NaN}', '{"amount":', '{"amount":Infinity}'):
            prompt = '⟦TOOL_RESULT name="get" requestor="assistant"⟧\n' + body
            with self.subTest(body=body):
                result = extract_typed_catalog(prompt)
                self.assertIn('unparsed_structured_event', result.issues)
                self.assertFalse(any(item.kind in {'Field', 'Number', 'State'} for item in result.items))
                self.assert_sources(result, prompt)

    def test_deterministic_ids_and_fully_serializable_result(self):
        prompt = '⟦USER⟧\n{"id":"R1","amount":12,"status":"ACTIVE"}'
        first = extract_typed_catalog(prompt)
        second = extract_typed_catalog(prompt)
        self.assertEqual(first, second)
        self.assertEqual([item.id for item in first.items], [f'tc{i:06d}' for i in range(len(first.items))])
        self.assertEqual(first.get(first.items[0].id), first.items[0])
        self.assertIsNone(first.get('missing'))
        json.dumps(first.to_dict())

    def test_limits_are_explicit_and_no_source_is_fabricated(self):
        prompt = '⟦USER⟧\n' + json.dumps({'items': list(range(20))})
        result = extract_typed_catalog(prompt, max_items=3)
        self.assertFalse(result.complete)
        self.assertLessEqual(len(result.items), 3)
        self.assert_sources(result, prompt)
        result = extract_typed_catalog('⟦USER⟧\nOne\n⟦USER⟧\nTwo', max_events=1)
        self.assertIn('event_limit', result.issues)
        deep = '⟦USER⟧\n' + json.dumps({'a': {'b': {'c': 3}}})
        result = extract_typed_catalog(deep, max_json_depth=1)
        self.assertFalse(result.complete)
        self.assertFalse(any(item.metadata.get('structured') for item in result.items))
        for kwargs in ({'max_items': 0}, {'max_items': True}, {'max_json_depth': 65}, {'max_text_span_chars': 0}):
            with self.assertRaises(ValueError):
                extract_typed_catalog(prompt, **kwargs)

    def test_tool_name_attribute_span_is_the_value_not_attribute_key(self):
        prompt = '⟦ASSISTANT_TOOL_CALL name="name"⟧\n{"name":"name"}'
        result = extract_typed_catalog(prompt)
        tool = next(item for item in result.items if item.kind == 'Tool')
        self.assertEqual(tool.source.start, prompt.index('"name"') + 1)
        self.assertEqual(prompt[tool.source.start:tool.source.end], 'name')

    def test_unicode_and_outer_wrappers_preserve_original_offsets(self):
        prompt = '<prompt>\n⟦USER⟧\n{"name":"Игорь 😀","user_id":"Ю-1","date":"2031-03-24T12:00:00Z"}\n</prompt>'
        result = extract_typed_catalog(prompt)
        self.assert_sources(result, prompt)
        temporal = next(item for item in result.items if item.kind == 'Date')
        self.assertTrue(temporal.metadata['timezone_explicit'])

    def test_source_instruction_payload_is_never_executed(self):
        payload = '__import__("os").system("do-not-run")'
        prompt = '⟦TOOL_RESULT name="lookup" requestor="assistant"⟧\n' + json.dumps({'description': payload})
        with patch('os.system', side_effect=AssertionError('execution')) as execute:
            result = extract_typed_catalog(prompt)
            execute.assert_not_called()
        literal = next(item for item in result.items if item.value == payload)
        self.assertEqual(literal.kind, 'FieldValue')
        self.assertEqual(literal.authority, 'tool_observation')
        self.assertFalse(any(item.authority == 'system_policy' for item in result.items))


if __name__ == '__main__':
    unittest.main()
