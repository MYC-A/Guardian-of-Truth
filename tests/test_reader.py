from types import SimpleNamespace
import unittest

from guardian_truth.reader import EvidenceReader
from guardian_truth.parsing import parse_events
from guardian_truth.provenance import build_graph
from guardian_truth.types import EntityKey, Event, EvidenceGraph, FactNode, Source


def reader():
    prompt = 'x' * 18000
    source = Source('prompt', 0, len(prompt))
    fact = FactNode('f0', 0, 'lookup', 'assistant', [], 'id', 'A',
                    [EntityKey('id', 'A')], [source], True)
    context = SimpleNamespace(prompt=prompt, response='candidate',
        history=[Event('assistant', 'result', prompt, source, 'lookup')],
        graph=EvidenceGraph(facts=[fact]))
    return EvidenceReader(context)


class ReaderTests(unittest.TestCase):
    def test_answer_entity_retrieval_survives_distractors_and_case_is_not_normalized(self):
        import json
        for identifier in ('CASE_A17','RECORD_Z92'):
            prompt = '⟦SYSTEM⟧\n'+'Policy. '*700
            prompt += '\n⟦TOOL_RESULT name="lookup" requestor="assistant"⟧\n'+json.dumps(
                {'record_id':identifier,'status':'complete'})
            prompt += '\n⟦USER⟧\n'+'complete status record '*500
            history = parse_events(prompt,'prompt')
            context = SimpleNamespace(prompt=prompt,response='Completed record '+identifier,
                                      history=history,graph=build_graph(history,[]))
            evidence = EvidenceReader(context,max_evidence_chars=3600)
            evidence.initialize()
            self.assertTrue(any(identifier in item['text'] and item['kind']=='result'
                                for item in evidence.packet()))
            context.response=identifier.lower()
            self.assertEqual(EvidenceReader(context).response_entity_chunks(),[])

    def test_metadata_is_bounded_even_when_a_fact_contains_a_large_value(self):
        import json
        evidence = reader()
        evidence.facts['f0'].value = 'large scalar '*10000
        evidence.read(['p0'])
        metadata = evidence.metadata()
        size = sum(len(json.dumps(value,ensure_ascii=False)) for value in metadata.values())
        self.assertLessEqual(size,6000)
        self.assertTrue(metadata['graph']['truncated'])
        self.assertEqual(evidence.facts['f0'].value,'large scalar '*10000)
        self.assertEqual(evidence.request({'action':'read','ids':['p9']})['added'],['p9'])

    def test_rolling_reads_replace_old_chunks_and_invalidate_their_citations(self):
        evidence = EvidenceReader(reader().context, max_evidence_chars=3600, rolling=True)
        evidence.read(['p0','p1'])
        feedback = evidence.request({'action':'read','ids':['p1','p8']})
        self.assertEqual(feedback['evicted'], ['p0'])
        self.assertEqual(evidence.selected, ['p1','p8'])
        self.assertEqual(evidence.used_chars,3600)
        self.assertIsNone(evidence.citation('p0'))
        self.assertIsNotNone(evidence.citation('p8'))

    def test_rolling_does_not_evict_just_requested_sources_to_claim_false_progress(self):
        evidence = EvidenceReader(reader().context, max_evidence_chars=3600, rolling=True)
        evidence.read(['p0','p1'])
        feedback = evidence.request({'action':'read','ids':['p2','p3','p4']})
        self.assertEqual(evidence.selected,['p2','p3'])
        self.assertEqual(feedback['added'],['p2','p3'])
        self.assertIsNone(evidence.citation('p4'))

    def test_fixed_reader_still_preserves_original_window(self):
        evidence = EvidenceReader(reader().context,max_evidence_chars=3600)
        evidence.read(['p0','p1'])
        self.assertEqual(evidence.request({'action':'read','ids':['p8']})['added'],[])
        self.assertEqual(evidence.selected,['p0','p1'])

    def test_text_only_response_graph_includes_retrieved_observations(self):
        evidence = reader()
        self.assertEqual(evidence.graph_summary()['facts'], [])
        evidence.read(['p0'])
        self.assertEqual([f['id'] for f in evidence.graph_summary()['facts']], ['f0'])
        # A graph node is still NOT a citable original source.
        self.assertIsNone(evidence.citation('f0'))

    def test_repeated_graph_reads_advance_through_matching_chunks(self):
        evidence = reader()
        action = {'action': 'graph', 'fact_ids': ['f0']}
        self.assertEqual(evidence.request(action)['added'], [f'p{i}' for i in range(8)])
        self.assertEqual(evidence.request(action)['added'], ['p8', 'p9'])
        self.assertEqual(evidence.request(action)['status'], 'no_new_evidence')

    def test_entity_reads_advance_through_matching_chunks(self):
        evidence = reader()
        action = {'action': 'entity', 'field': 'id', 'value': 'A'}
        self.assertEqual(len(evidence.request(action)['added']), 8)
        self.assertEqual(evidence.request(action)['added'], ['p8', 'p9'])

    def test_citations_require_selected_original_spans(self):
        evidence = reader()
        self.assertIsNone(evidence.citation('p0'))
        evidence.read(['p0'])
        source = evidence.citation('p0')
        self.assertEqual(evidence.context.prompt[source.start:source.end], evidence.packet()[0]['text'])
        self.assertEqual(source.document, 'prompt')
        self.assertIsNone(evidence.citation('f0'))

    def test_limits_reject_noninteger_values(self):
        context = reader().context
        for name in ('chunk_chars', 'max_evidence_chars'):
            for value in (True, 1800.0, float('nan')):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    EvidenceReader(context, **{name: value})


if __name__ == '__main__':
    unittest.main()
