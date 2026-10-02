"""Scope, arithmetic, continuation and quote regressions; no API dependency."""
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
import tempfile
import urllib.error
import io

ROOT = Path(__file__).resolve().parents[3]
sys.path.insert(0, str(ROOT / 'src'))
from guardian_truth.source_search import SourceStore, calculate
from guardian_truth.source_search.calculations import literals
from guardian_truth.source_search.pipeline import run, validate_assessment, contract
from guardian_truth.source_search.transport import ModelTransport


def case():
    return {'id': 'independent-mechanism-control', 'prompt': '''⟦SYSTEM⟧
Changes require recorded approval. Reading state is allowed.
⟦USER⟧
Please help with product P-1.
⟦ASSISTANT⟧
→ TOOL_CALL inspect: {"product_id":"P-1"}
← TOOL_RESPONSE inspect: {"orders":[{"order_id":"O-1","owner_id":"U-1","items":[{"product_id":"P-1","price":"20.00"}]},{"order_id":"O-2","owner_id":"U-2","items":[{"product_id":"P-1","price":"30.00"}]}]}
→ TOOL_CALL KB_search: {}
← TOOL_RESPONSE KB_search: A recorded approval is needed for a change, not for inspection. Report date: 2031-02-03. Tomorrow: 2031-02-04. Balance: $3,000.00. Limit: $4,000.00.
''', 'response': 'Please confirm, and then I can request the change.'}


def complete_vote(row, decision='NO_ERROR'):
    return {'decision': decision, 'explanation': 'A future conditional request is not completion.',
        'findings': [], 'checks': [{'question_id': q, 'status': 'CHECKED', 'reason': 'checked in source',
            'evidence': [{'source_id': 'prompt', 'quote': 'Changes require recorded approval.'}]} for q in
            ('scope', 'grounds', 'exceptions', 'alternatives', 'arithmetic')], 'open_questions': []}


class Tests(unittest.TestCase):
    def test_read_window_past_eof_is_clipped_without_inventing_text(self):
        store = SourceStore(case())
        result = store.read_source('h0', start=0, end=200)
        self.assertEqual(result['text'], store.text('h0'))
        self.assertTrue(result['end_clipped_to_source'])
        self.assertFalse(result['was_truncated'])
        self.assertEqual(result['requested_end'], 200)
        with self.assertRaises(ValueError):
            store.read_source('h0', start=result['source_length'], end=200)

    def test_native_operation_error_preserves_tool_call_protocol(self):
        calls = []
        native = {'id': 'failed-read', 'type': 'function', 'function': {'name': 'read_source',
            'arguments': '{"source_id":"missing"}'}}
        def ask(messages):
            calls.append(messages[-1])
            if len(calls) == 1:
                return {'status': 'OK', 'content': json.dumps({'action': {
                    'op': 'read_source', 'args': {'source_id': 'missing'}}}),
                    'native_tool_calls': [native], 'native_assistant_message': {
                        'role': 'assistant', 'content': None, 'tool_calls': [native]}}
            self.assertEqual(messages[-1]['role'], 'tool')
            self.assertEqual(messages[-1]['tool_call_id'], 'failed-read')
            self.assertIn('unknown source_id', messages[-1]['content'])
            return {'status': 'UNAVAILABLE', 'reason': 'test_stop'}
        result = run(case(), ask)
        self.assertEqual(result['decision'], 'UNKNOWN')
        self.assertEqual(len(calls), 2)

    def test_search_contract_states_phase_and_does_not_offer_final_schema(self):
        self.assertIn('CURRENT ROLE: SEARCH CONTROLLER', contract('SEARCH'))
        self.assertNotIn('Assessment schema:', contract('SEARCH'))
        self.assertIn('CURRENT ROLE: JUDGE', contract('JUDGE'))
    def test_full_index_reaches_second_order_and_keeps_owners_distinct(self):
        store = SourceStore(case())
        result = store.traverse({'field': 'product_id', 'value': 'P-1'}, strategy='BFS', max_depth=1)
        orders = {r['entity']['value'] for r in result['items'] if r['entity']['field'] == 'order_id'}
        self.assertEqual(orders, {'O-1', 'O-2'})
        facts = store.lookup_entity('order_id', 'O-2', limit=40)['items']
        self.assertTrue(facts)
        self.assertTrue(all(any(e == {'field': 'owner_id', 'value': 'U-2'} for e in f['entities']) for f in facts))
        self.assertNotIn('text', next(iter(store.quotes.values())))

    def test_typed_identifiers_and_json_paths_do_not_merge(self):
        store = SourceStore(case())
        self.assertEqual(store.lookup_entity('order_id', 'P-1')['total'], 0)
        self.assertEqual(store.lookup_entity('product_id', 1)['total'], 0)

    def test_plain_text_sources_are_searchable_and_exact(self):
        store = SourceStore(case())
        hit = store.search_sources('recorded inspection', source_types=['result'])['items'][0]
        read = store.read_source(hit['source_ref'])
        self.assertIn('not for inspection', read['text'])
        self.assertEqual(read['text'], store.raw[read['document']][read['start']:read['end']])

    def test_dates_and_grouped_decimal_are_computed_from_source(self):
        store = SourceStore(case())
        sid = next(s['id'] for s in store.sources.values() if s.get('tool') == 'KB_search' and s['kind'] == 'result')
        dates = literals(store, sid, 'date')
        self.assertEqual(calculate(store, 'difference', dates[:2])['result'], '-1')
        numbers = literals(store, sid, 'decimal')
        operands = [next(r for r in numbers if r['literal'] == v) for v in ('3,000.00', '4,000.00')]
        self.assertEqual(calculate(store, 'percentage', operands)['result'], '75.00')

    def test_unzoned_datetime_and_mixed_date_precision_are_unknown(self):
        row = {'prompt': '2031-02-03T10:00:00 2031-02-04T10:00:00Z 2031-02-03', 'response': 'ok'}
        store = SourceStore(row)
        refs = literals(store, 'prompt', 'datetime')
        self.assertEqual(calculate(store, 'compare', refs[:2])['status'], 'UNKNOWN')
        self.assertEqual(calculate(store, 'compare', refs[1:])['status'], 'UNKNOWN')

    def test_bad_id_recovered_only_with_unique_exact_quote(self):
        store = SourceStore(case())
        ref = store.resolve_quote({'source_id': 'invented', 'quote': 'Changes require recorded approval.'})
        self.assertEqual(ref['repair'], 'UNIQUE_EXACT_QUOTE_ID_RECOVERY')
        with self.assertRaises(ValueError):
            store.resolve_quote({'source_id': 'invented', 'quote': 'recorded approval'})
        with self.assertRaises(ValueError):
            store.resolve_quote({'source_id': 'invented', 'quote': 'This was never in the source.'})

    def test_code_keeps_open_checks_unknown(self):
        row = case(); store = SourceStore(row); vote = complete_vote(row)
        vote['checks'] = vote['checks'][:1]
        result = validate_assessment(store, vote)
        self.assertEqual(result['decision'], 'UNKNOWN')
        self.assertEqual(result['proposed_decision'], 'NO_ERROR')

    def test_next_question_uses_previous_result_and_judge_can_resume_search(self):
        row = case(); calls = []
        replies = [
            {'action': {'op': 'neighbors', 'args': {'entity': {'field': 'product_id', 'value': 'P-1'}}}, 'question_id': 'alternatives'},
            {'ready_for_judge': True},
            {'action': {'op': 'lookup_entity', 'args': {'field': 'order_id', 'value': 'O-2'}}},
            {'assessment': complete_vote(row)},
        ]
        def ask(messages):
            calls.append(messages[-1]['content'])
            if len(calls) == 2:
                self.assertIn('O-2', messages[-1]['content'])
            if len(calls) == 4:
                self.assertIn('U-2', messages[-1]['content'])
            return {'status': 'OK', 'content': json.dumps(replies[len(calls)-1])}
        result = run(row, ask)
        self.assertEqual(result['decision'], 'NO_ERROR')
        self.assertEqual([r['phase'] for r in result['trace']], ['SEARCH', 'SEARCH', 'JUDGE', 'JUDGE'])

    def test_unread_material_page_cannot_be_closed_by_confidence(self):
        row = case(); replies = iter([
            {'action': {'op': 'search_sources', 'args': {'query': 'recorded', 'limit': 1}}},
            {'ready_for_judge': True}, {'assessment': complete_vote(row)}])
        result = run(row, lambda _: {'status': 'OK', 'content': json.dumps(next(replies))})
        self.assertEqual(result['decision'], 'UNKNOWN')
        self.assertEqual(result['stop_reason'], 'unread_material_query_remainder')

    def test_402_or_429_is_terminal_not_a_model_reask(self):
        for status in (402, 429):
            calls = []
            def ask(messages):
                calls.append(1)
                return {'status': 'UNAVAILABLE', 'reason': f'http_{status}'}
            result = run(case(), ask)
            self.assertEqual(len(calls), 1)
            self.assertEqual(result['decision'], 'UNKNOWN')
            self.assertEqual(result['stop_reason'], f'http_{status}')

    def test_real_transport_breaker_persists_without_poll_or_retry(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ', {'MISTRAL_API_KEY': 'test-placeholder', 'MISTRAL_MODEL': 'test-model'}):
                transport = ModelTransport(directory)
                with patch('urllib.request.urlopen', side_effect=urllib.error.HTTPError('test', 429, '', {}, None)) as http:
                    self.assertEqual(transport([{'role': 'user', 'content': 'a'}])['reason'], 'http_429')
                    resumed = ModelTransport(directory)
                    self.assertEqual(resumed([{'role': 'user', 'content': 'b'}])['reason'], 'provider_circuit_open')
                    self.assertEqual(http.call_count, 1)
                self.assertEqual(resumed.snapshot()['actual_api_attempts'], 1)
                self.assertEqual(resumed.snapshot()['known_provider_tokens'], 0)
                self.assertGreater(resumed.snapshot()['unknown_usage_upper_bounds'], 0)

    def test_native_tool_call_is_decoded_and_reply_uses_same_call_id(self):
        with tempfile.TemporaryDirectory() as directory:
            with patch.dict('os.environ',{'MISTRAL_API_KEY':'test-placeholder','MISTRAL_MODEL':'test-model'}):
                transport=ModelTransport(directory)
                native={'id':'test-call-1','type':'function','function':{'name':'read_source',
                    'arguments':json.dumps({'source_id':'h0'})}}
                data={'choices':[{'finish_reason':'tool_calls','message':{'role':'assistant','content':'','tool_calls':[native]}}],
                      'usage':{'total_tokens':12}}
                with patch('urllib.request.urlopen',return_value=io.BytesIO(json.dumps(data).encode())):
                    rec=transport([{'role':'system','content':contract('SEARCH')},{'role':'user','content':'source index'}])
                self.assertEqual(rec['status'],'OK')
                self.assertEqual(json.loads(rec['content'])['action']['op'],'read_source')
                self.assertEqual(rec['native_tool_calls'][0]['id'],'test-call-1')
                calls=[]
                def ask(messages):
                    calls.append(messages[-1])
                    if len(calls)==1:
                        return rec
                    self.assertEqual(messages[-1]['role'],'tool')
                    self.assertEqual(messages[-1]['tool_call_id'],'test-call-1')
                    return {'status':'UNAVAILABLE','reason':'stop_after_verified_native_roundtrip'}
                result=run(case(),ask)
                self.assertEqual(result['trace'][0]['result']['source_id'],'h0')
                self.assertEqual(len(calls),2)


if __name__ == '__main__':
    unittest.main()
