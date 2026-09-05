from types import SimpleNamespace
import unittest

from guardian_truth.reader import EvidenceReader
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
