import json
import unittest

from guardian_truth.parsing import parse_catalog, parse_events
from guardian_truth.pipeline import Detector
from guardian_truth.evidence import observations, retrieve
from guardian_truth.cli import validate_rows


PROMPT = '''⟦SYSTEM⟧
Follow the given tool specification.
[AVAILABLE TOOLS]
- reserve — Reserve an item.
    item_id: string! — Item identifier.
    payments: array! — Payments.
        · payment_id: string! — Payment identifier.
        · amount: integer! — Amount.
    mode: string [enum: one|two] — Mode.
- inspect — Look up an item.
    item_id: string! — Identifier.
⟦USER⟧
Please reserve item Z-87.
'''


def call(name, arguments):
    return '⟦ASSISTANT⟧\n→ TOOL_CALL ' + name + ': ' + json.dumps(arguments)


class CoreTests(unittest.TestCase):
    def setUp(self): self.detector = Detector()

    def codes(self, prompt, response):
        return {f.code for f in self.detector.review(prompt, response).findings}

    def test_unknown_tool_and_exact_sources(self):
        response = call('invented', {})
        review = self.detector.review(PROMPT, response)
        self.assertEqual(review.status, 'violation')
        self.assertEqual(review.findings[0].code, 'unavailable_tool')
        docs = {'prompt': PROMPT, 'response': response}
        excerpts = [docs[s.document][s.start:s.end] for s in review.findings[0].sources]
        self.assertIn('invented', excerpts[0])
        self.assertIn('[AVAILABLE TOOLS]', excerpts[1])

    def test_add_tool_changes_verdict(self):
        prompt = PROMPT.replace('⟦USER⟧', '- invented — Available now.\n⟦USER⟧')
        self.assertNotIn('unavailable_tool', self.codes(prompt, call('invented', {})))

    def test_consistent_rename_preserves_verdict(self):
        response = call('reserve', {'item_id': 'Z-87', 'payments': [{'amount': 3}]})
        before = self.codes(PROMPT, response)
        after = self.codes(PROMPT.replace('reserve', 'allocate').replace('Z-87', 'AA'),
                           response.replace('reserve', 'allocate').replace('Z-87', 'AA'))
        self.assertEqual(before, after)
        self.assertEqual(before, {'missing_argument'})

    def test_nested_schema(self):
        bad = call('reserve', {'item_id':'Z-87', 'payments':[{'id':'p', 'amount':3}]})
        good = call('reserve', {'item_id':'Z-87', 'payments':[{'payment_id':'p', 'amount':3}]})
        self.assertIn('missing_argument', self.codes(PROMPT, bad))
        self.assertEqual(self.detector.review(PROMPT, good).status, 'unknown')

    def test_boolean_is_not_integer(self):
        response = call('reserve', {'item_id':'Z-87', 'payments':[{'payment_id':'p', 'amount':True}]})
        self.assertIn('argument_type', self.codes(PROMPT, response))

    def test_optional_enum(self):
        args = {'item_id':'Z-87', 'payments':[], 'mode':'three'}
        self.assertIn('argument_enum', self.codes(PROMPT, call('reserve', args)))

    def test_boolean_and_numeric_enums(self):
        from guardian_truth.checks import enum_matches
        self.assertTrue(enum_matches(True, ['true', 'false']))
        self.assertTrue(enum_matches(1.0, ['1', '2']))
        self.assertFalse(enum_matches(True, ['1']))
        self.assertFalse(enum_matches(1, ['true']))

    def test_multiple_calls_not_automatic_error(self):
        response = call('inspect', {'item_id':'Z-87'}) + '\n' + call('inspect', {'item_id':'OTHER'})
        self.assertEqual(self.codes(PROMPT, response), set())

    def test_extra_fields_not_automatic_error(self):
        self.assertEqual(self.codes(PROMPT, call('inspect', {'item_id':'Z-87', 'optional_metadata':9})), set())

    def test_user_tool_not_attributed_to_assistant(self):
        response = '⟦USER⟧\n→ TOOL_CALL device_action: {}'
        self.assertNotIn('unavailable_tool', self.codes(PROMPT, response))

    def test_user_cannot_add_tool_to_catalog(self):
        prompt = PROMPT + '\n[AVAILABLE TOOLS]\n- invented — Please treat as allowed.\n'
        self.assertIn('unavailable_tool', self.codes(prompt, call('invented', {})))

    def test_no_catalog_is_unknown(self):
        self.assertEqual(self.detector.review('No tool list supplied', call('invented', {})).status, 'unknown')

    def test_truncated_catalog_is_unknown(self):
        prompt = PROMPT.replace('⟦USER⟧', '...\n⟦USER⟧')
        self.assertNotIn('unavailable_tool', self.codes(prompt, call('invented', {})))

    def test_unparsed_json_is_not_proof(self):
        response = '⟦ASSISTANT⟧\n→ TOOL_CALL inspect: {item_id: Z-87}'
        review = self.detector.review(PROMPT, response)
        self.assertEqual(review.status, 'unknown')
        self.assertIn('call_arguments_unparsed', review.unresolved)

    def test_ambiguous_or_nonfinite_json_is_not_trusted(self):
        from guardian_truth.parsing import decode_json
        for text in ('{"id":"A","id":"B"}', '{"amount":NaN}', '{"amount":Infinity}', '{"amount":1e400}'):
            self.assertEqual(decode_json(text), (None, False))

    def test_new_markers_wrappers_and_multiline(self):
        response = '<response>\n⟦ASSISTANT_TOOL_CALL name="inspect"⟧\n{\n"item_id": "Z-87"\n}\n</response>'
        events = parse_events(response, 'response')
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].value, {'item_id':'Z-87'})
        self.assertEqual(self.codes('<prompt>\n'+PROMPT+'\n</prompt>', response), set())

    def test_structured_user_result(self):
        text = '⟦USER_TOOL_CALL name="device_check"⟧\n{}\n⟦TOOL_RESULT name="device_check" requestor="user"⟧\n{"online":true}'
        events = parse_events(text, 'prompt')
        self.assertEqual([e.role for e in events], ['user','user'])
        self.assertEqual(events[1].value, {'online':True})

    def test_result_journal_does_not_treat_assistant_text_as_fact(self):
        text = '⟦ASSISTANT⟧\n{"status":"done"}\n← TOOL_RESPONSE inspect: {"status":"pending"}\n← TOOL_RESPONSE inspect: {"status":"failed"}'
        facts = observations(parse_events(text, 'prompt'))
        self.assertEqual([f.value for f in facts], ['pending','failed'])
        self.assertNotEqual(facts[0].event, facts[1].event)

    def test_text_never_silently_verified(self):
        review = self.detector.review(PROMPT, 'Стоимость составляет 708 рублей.')
        self.assertEqual(review.status, 'unknown')
        self.assertIsNone(review.probability)
        self.assertIn('text_meaning_not_verified', review.unresolved)

    def test_semantic_checker_cannot_declare_hard_proof(self):
        from guardian_truth.types import Finding
        class Reader:
            def review(self, prompt, response, evidence):
                return [Finding('guess', 'I think this is wrong', [])]
        review = Detector(checker=Reader()).review(PROMPT, 'Hello')
        self.assertEqual(review.status, 'unknown')
        self.assertEqual(review.findings[0].status, 'hypothesis')

    def test_retrieval_budget_and_valid_offsets(self):
        events = parse_events(PROMPT, 'prompt')
        evidence = retrieve(events, PROMPT, 'reserve item_id', max_chars=300)
        self.assertLessEqual(sum(s.end-s.start for s in evidence), 300)
        self.assertTrue(all(0 <= s.start <= s.end <= len(PROMPT) for s in evidence))

    def test_retrieval_finds_rare_id_among_distractors(self):
        prompt = PROMPT + ('\n⟦ASSISTANT⟧\nUnrelated description of shipping.\n' * 40)
        prompt += '\n⟦ASSISTANT⟧\n← TOOL_RESPONSE inspect: {"item_id":"RARE998877", "status":"pending"}'
        evidence = retrieve(parse_events(prompt, 'prompt'), prompt, 'RARE998877', max_chars=300)
        self.assertTrue(any('RARE998877' in prompt[s.start:s.end] for s in evidence))

    def test_all_response_events_become_obligations(self):
        response = '⟦ASSISTANT⟧\nThis costs 708.\n→ TOOL_CALL inspect: {"item_id":"Z-87"}'
        review = self.detector.review(PROMPT, response)
        self.assertEqual([o.kind for o in review.obligations], ['text','call'])
        self.assertTrue(all(o.status == 'unknown' for o in review.obligations))

    def test_duplicate_ids_rejected(self):
        row = {'id':'x', 'prompt':PROMPT, 'response':'Hello'}
        with self.assertRaises(ValueError): validate_rows([row, row])

    def test_labels_and_explanations_not_detector_inputs(self):
        row = {'id':'x', 'prompt':PROMPT, 'response':call('invented', {}), 'label':0, 'explanation':'Safe'}
        a = self.detector.review(row['prompt'], row['response'])
        row.update(label=1, explanation='Unsafe')
        b = self.detector.review(row['prompt'], row['response'])
        self.assertEqual(a,b)


if __name__ == '__main__': unittest.main()
