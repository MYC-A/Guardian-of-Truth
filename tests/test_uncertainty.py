"""Offline contracts for the bounded uncertainty experiment, not quality claims."""

import copy
import contextlib
import importlib.util
import io
import json
from pathlib import Path
import sys
import tempfile
from types import SimpleNamespace
import unittest
from unittest.mock import patch

from guardian_truth.decision import decide
from guardian_truth.language import LanguageAnalyzer, LanguageConfig, RunBudget
from guardian_truth.llm_client import Completion
from guardian_truth.parsing import parse_events
from guardian_truth.pipeline import Detector
from guardian_truth.reader import EvidenceReader
from guardian_truth.semantic import SemanticResult
from guardian_truth.types import EvidenceGraph
from guardian_truth.uncertainty import (
    claim_memory, diagnose, recovery_action, refresh_memory, safe_request,
)


def assessment(verdict='ok', ids=None, *, claim_verdict=None):
    ids = ['p0'] if ids is None else ids
    state = claim_verdict or {'ok':'supported', 'error':'contradicted', 'unknown':'unknown'}[verdict]
    return {'verdict':verdict, 'risk':0.8 if verdict != 'ok' else 0.1,
            'reason':'A retained model explanation', 'evidence_ids':ids,
            'claims':[{'text':'Material candidate claim', 'verdict':state,
                       'reason':'A retained claim explanation', 'evidence_ids':ids}],
            'requests':[], 'plan':[]}


def missing(ids=None, *, kind='MISSING_EVIDENCE', need='Missing exception', request=None):
    output = assessment('unknown', ids)
    output['claims'][0]['uncertainty'] = {'kind':kind, 'need':need, 'request':request}
    return output


class FakeClient:
    def __init__(self, *answers):
        self.answers = list(answers)
        self.messages = []
        self.payloads = []

    def complete(self, messages):
        self.messages.append(copy.deepcopy(messages))
        payload = json.loads(messages[-1]['content'])
        self.payloads.append(payload)
        answer = self.answers[len(self.payloads)-1]
        if isinstance(answer, Exception):
            raise answer
        if callable(answer):
            answer = answer(payload)
        return Completion(answer if isinstance(answer, str) else json.dumps(answer), {'total_tokens':7})


def run(client, recovery='directed', *, prompt=None, **config):
    prompt = prompt or '\u27e6SYSTEM\u27e7\nA local policy source.'
    analyzer = LanguageAnalyzer(client, LanguageConfig(mode='graph', recovery=recovery, **config),
                                budget=RunBudget(max_requests=5))
    return Detector(semantic=analyzer).review(prompt, 'Material candidate claim')


def long_prompt():
    return '\u27e6SYSTEM\u27e7\n' + 'anchor ' * 300 + 'unseen ' * 700


class UncertaintyUnitTests(unittest.TestCase):
    def reader(self):
        prompt = long_prompt()
        reader = EvidenceReader(SimpleNamespace(prompt=prompt, response='Candidate', history=parse_events(prompt, 'prompt'),
                                                graph=EvidenceGraph()), max_evidence_chars=1800,
                                rolling=True)
        reader.read(['p0'])
        return reader

    def test_memory_is_hypothesis_and_filters_unread_sources(self):
        reader = self.reader()
        output = assessment('error', ['p1', 'response'])
        memory = claim_memory(output, reader)
        self.assertEqual(memory[0]['reported_verdict'], 'contradicted')
        self.assertEqual(memory[0]['state'], 'unknown')
        self.assertNotIn('p1', memory[0]['evidence_ids'])
        self.assertEqual(memory[0]['authority'], 'revisable_model_hypothesis')

    def test_eviction_invalidates_current_support_preserves_prior_judgment(self):
        reader = self.reader()
        memory = claim_memory(assessment(), reader)
        self.assertEqual(memory[0]['state'], 'supported')
        reader.read(['p1'])
        refreshed = refresh_memory(memory, reader)
        self.assertEqual(refreshed[0]['state'], 'unknown')
        self.assertEqual(refreshed[0]['reported_verdict'], 'supported')
        self.assertEqual(refreshed[0]['unavailable_evidence_ids'], ['p0'])
        self.assertEqual(refreshed[0]['current_evidence_ids'], [])
        self.assertEqual(memory[0]['state'], 'supported')

    def test_missing_citation_is_invalid_output_not_missing_world_evidence(self):
        items = diagnose(assessment('error', ['p999']),
                         SemanticResult(unresolved=['language_missing_grounding']), self.reader())
        self.assertEqual([item.kind for item in items], ['INVALID_OUTPUT'])
        self.assertEqual(recovery_action(items)[1], {'action':'recheck_same_evidence'})

    def test_explicit_missing_need_maps_to_bounded_search(self):
        reader = self.reader()
        items = diagnose(missing(need='specific policy exception'),
                         SemanticResult(unresolved=['language_assessment_unknown']), reader)
        self.assertEqual(items[0].kind, 'MISSING_EVIDENCE')
        self.assertEqual(recovery_action(items)[1],
                         {'action':'search', 'query':'specific policy exception'})

    def test_other_and_empty_need_do_not_trigger_recovery(self):
        for output in (missing(kind='OTHER'), missing(need=''), missing(kind='STALE_STATE')):
            with self.subTest(output=output):
                items = diagnose(output, SemanticResult(unresolved=['language_assessment_unknown']), self.reader())
                self.assertEqual(recovery_action(items), (None, None))

    def test_invalid_output_takes_priority_over_semantic_need(self):
        items = diagnose(missing(), SemanticResult(unresolved=['language_invalid_claim']), self.reader())
        self.assertEqual(recovery_action(items)[1], {'action':'recheck_same_evidence'})
        self.assertEqual([item.kind for item in items], ['INVALID_OUTPUT', 'MISSING_EVIDENCE'])

    def test_safe_requests_strip_extra_fields_and_reject_execution(self):
        for action in ('python', 'shell', 'http', 'fetch', 'run', 'tool_call'):
            self.assertIsNone(safe_request({'action':action, 'code':'raise RuntimeError()',
                                            'url':'https://example.invalid'}))
        self.assertEqual(safe_request({'action':'read', 'ids':['p1'], 'url':'https://example.invalid'}),
                         {'action':'read', 'ids':['p1']})
        self.assertIsNone(safe_request({'action':'entity', 'field':'id', 'value':True}))
        self.assertLessEqual(len(safe_request({'action':'search', 'query':'x'*1000})['query']), 300)


class UncertaintyIntegrationTests(unittest.TestCase):
    def test_unknown_high_risk_never_becomes_error_label(self):
        client = FakeClient(missing(kind='OTHER'))
        review = run(client)
        self.assertIsNone(review.semantic_score)
        self.assertEqual(decide(review, use_semantic=True).label, 0)
        self.assertTrue(decide(review, use_semantic=True).used_fallback)
        self.assertEqual(len(client.payloads), 1)

    def test_observe_preserves_rejected_reason_claims_and_only_calls_once(self):
        output = assessment('error', ['p999'])
        client = FakeClient(output)
        review = run(client, 'observe')
        self.assertEqual(len(client.payloads), 1)
        trace = review.reading_trace[0]
        self.assertEqual(trace['model_assessment']['reason'], output['reason'])
        self.assertEqual(trace['model_assessment']['claims'], output['claims'])
        self.assertEqual(trace['uncertainties'][0]['kind'], 'INVALID_OUTPUT')
        self.assertEqual(trace['claim_state'][0]['state'], 'unknown')
        self.assertEqual(trace['claim_state'][0]['reported_verdict'], 'contradicted')
        self.assertNotIn('recovery', trace)

    def test_invalid_output_rechecks_exact_same_evidence_with_feedback(self):
        client = FakeClient(assessment('error', ['p999']), assessment())
        review = run(client)
        self.assertEqual(len(client.payloads), 2)
        first, second = client.payloads
        self.assertEqual(first['evidence'], second['evidence'])
        self.assertEqual(second['focused_uncertainty']['kind'], 'INVALID_OUTPUT')
        self.assertEqual(second['read_feedback'][0]['status'], 'same_evidence')
        self.assertEqual(second['previous_claims'][0]['reported_verdict'], 'contradicted')
        self.assertEqual(review.semantic_score, 0.1)
        self.assertEqual(review.semantic_usage['total_tokens'], 14)

    def test_missing_evidence_reads_then_rechecks_with_evicted_memory(self):
        output = missing(request={'action':'read', 'ids':['p1']})
        output['claims'].insert(0, assessment()['claims'][0])
        client = FakeClient(output, assessment('error', ['p1']))
        review = run(client, prompt=long_prompt(), max_evidence_chars=1800)
        self.assertEqual(len(client.payloads), 2)
        first, second = client.payloads
        self.assertEqual([e['id'] for e in first['evidence']], ['p0'])
        self.assertEqual([e['id'] for e in second['evidence']], ['p1'])
        self.assertEqual(second['focused_uncertainty']['kind'], 'MISSING_EVIDENCE')
        self.assertEqual(second['read_feedback'][0]['added'], ['p1'])
        self.assertEqual(second['read_feedback'][0]['evicted'], ['p0'])
        prior = second['previous_claims'][0]
        self.assertEqual(prior['reported_verdict'], 'supported')
        self.assertEqual(prior['state'], 'unknown')
        self.assertEqual(review.semantic_score, 0.8)

    def test_previous_claims_can_be_revised_instead_of_frozen(self):
        output = assessment('error', claim_verdict='supported')
        client = FakeClient(output, assessment('error'))
        review = run(client)
        self.assertEqual(client.payloads[1]['previous_claims'][0]['state'], 'supported')
        self.assertEqual(review.reading_trace[1]['claim_state'][0]['state'], 'contradicted')
        self.assertEqual(review.semantic_score, 0.8)

    def test_recovery_stops_after_one_cycle_even_if_second_answer_needs_more(self):
        client = FakeClient(missing(request={'action':'read', 'ids':['p1']}),
                            missing(['p1'], request={'action':'read', 'ids':['p2']}))
        review = run(client, prompt=long_prompt(), max_evidence_chars=1800)
        self.assertEqual(len(client.payloads), 2)
        self.assertIsNone(review.semantic_score)
        self.assertNotIn('recovery', review.reading_trace[1])

    def test_second_round_legacy_requests_cannot_start_third_call(self):
        second = missing()
        second['requests'] = [{'action':'read', 'ids':['p2']}]
        client = FakeClient(assessment('error', ['p999']), second)
        review = run(client, prompt=long_prompt(), max_evidence_chars=1800)
        self.assertEqual(len(client.payloads), 2)
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_unfinished_reading', review.unresolved)

    def test_legacy_requests_cannot_bypass_reason_driven_routing(self):
        output = missing(kind='OTHER')
        output['requests'] = [{'action':'read', 'ids':['p1']}]
        for mode in ('directed', 'repeat'):
            with self.subTest(mode=mode):
                client = FakeClient(output, assessment())
                with patch.object(EvidenceReader, 'request',
                                  return_value={'status':'no_new_evidence', 'added':[]}) as request:
                    review = run(client, mode, prompt=long_prompt(), max_evidence_chars=1800)
                request.assert_not_called()
                self.assertEqual(len(client.payloads), 2)
                if mode == 'repeat':
                    self.assertEqual(client.messages[0], client.messages[1])
                else:
                    self.assertEqual(client.payloads[0]['evidence'], client.payloads[1]['evidence'])
                    recovery = review.reading_trace[0]['recovery']
                    self.assertEqual(recovery['action'], {'action':'recheck_same_evidence'})
                    self.assertEqual(recovery['result']['added'], [])

    def test_repeat_uses_identical_initial_messages_without_directed_feedback(self):
        client = FakeClient(assessment('error', ['p999']), assessment())
        run(client, 'repeat')
        self.assertEqual(client.messages[0], client.messages[1])
        self.assertNotIn('focused_uncertainty', client.payloads[1])
        self.assertNotIn('previous_claims', client.payloads[1])

    def test_default_off_is_one_call_with_unchanged_instruction_protocol(self):
        self.assertEqual(LanguageConfig().recovery, 'off')
        client = FakeClient(assessment('error', ['p999']))
        review = run(client, 'off')
        self.assertEqual(len(client.payloads), 1)
        self.assertNotIn('Experimental diagnostic protocol', client.messages[0][0]['content'])
        self.assertIsNone(review.semantic_score)

    def test_unknown_other_stops_even_with_reader_request_in_detail(self):
        client = FakeClient(missing(kind='OTHER', request={'action':'read', 'ids':['p1']}))
        review = run(client, prompt=long_prompt(), max_evidence_chars=1800)
        self.assertEqual(len(client.payloads), 1)
        self.assertNotIn('recovery', review.reading_trace[0])

    def test_arbitrary_request_never_executes_remote_or_local_code(self):
        output = missing(need='', request={'action':'python', 'code':'raise RuntimeError()'})
        client = FakeClient(output)
        with patch('subprocess.run', side_effect=AssertionError('No process allowed')), \
             patch('urllib.request.urlopen', side_effect=AssertionError('No network allowed')):
            review = run(client)
        self.assertEqual(len(client.payloads), 1)
        self.assertIsNone(review.semantic_score)

    def test_transport_failure_does_not_invent_semantic_need(self):
        error = RuntimeError('Provider body must not be propagated')
        error.category = 'http_request'
        client = FakeClient(error)
        review = run(client)
        self.assertEqual(len(client.payloads), 1)
        self.assertIn('language_http_request', review.unresolved)
        self.assertEqual(review.reading_trace, [])
        self.assertNotIn('Provider body', str(review))

    def test_recovery_modes_are_explicitly_graph_only(self):
        for mode in ('direct', 'rlm'):
            with self.assertRaises(ValueError):
                LanguageConfig(mode=mode, recovery='directed')


class AblationRunnerTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).resolve().parents[1]/'scripts'/'ablate_uncertainty.py'
        spec = importlib.util.spec_from_file_location('guardian_uncertainty_runner_test', path)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    class BudgetedFake(FakeClient):
        config = SimpleNamespace(model='fake-offline', base_url='http://127.0.0.1:1/v1')

        def complete_budgeted(self, messages, *, budget):
            budget.reserve(sum(len(message['content']) for message in messages))
            return self.complete(messages)

    def test_capture_replay_spends_no_request_budget_and_repeats_no_usage(self):
        budget = RunBudget(max_requests=2)
        transport = self.BudgetedFake(assessment(), assessment('error'))
        messages = [{'role':'user', 'content':'{}'}]
        capture = self.runner.CaptureClient(transport)
        first = capture.complete_budgeted(messages, budget=budget)
        self.assertIs(capture.first, first)
        after_first = (budget.requests, budget.input_chars)
        branch = self.runner.CaptureClient(transport, replay=first)
        replayed = branch.complete_budgeted(messages, budget=budget)
        self.assertEqual(replayed.content, first.content)
        self.assertEqual(replayed.usage, {})
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual((budget.requests, budget.input_chars), after_first)
        branch.complete_budgeted(messages, budget=budget)
        self.assertEqual(len(transport.messages), 2)
        self.assertEqual(budget.requests, 2)

    def test_eligibility_distinguishes_actionable_from_other_or_generation_failure(self):
        self.assertFalse(self.runner.eligible(SimpleNamespace(reading_trace=[])))
        self.assertFalse(self.runner.eligible(SimpleNamespace(reading_trace=[{}])))
        for kind, need, request, expected in (
                ('OTHER', 'unknown', {'action':'read','ids':['p1']}, False),
                ('MISSING_EVIDENCE', '', None, False),
                ('MISSING_EVIDENCE', 'exception', {'action':'read','ids':['p1']}, True),
                ('INVALID_OUTPUT', 'repair citation', None, True)):
            with self.subTest(kind=kind, need=need):
                review = SimpleNamespace(reading_trace=[{'uncertainties':[
                    {'claim':'C', 'kind':kind, 'reason':'reason', 'need':need,
                     'known_evidence':[], 'attempted_actions':[], 'request':request}]}])
                self.assertEqual(self.runner.eligible(review), expected)

    def test_row_order_uses_only_id_and_is_deterministic(self):
        original = [{'id':key, 'label':index % 2, 'prompt':'old', 'response':'old'}
                    for index, key in enumerate(('c', 'a', 'b'))]
        changed = [dict(row, label=1-row['label'], prompt='changed', response='changed',
                        explanation='Gold explanation must not affect selection') for row in original]
        self.assertEqual([self.runner.row_order(row) for row in original],
                         [self.runner.row_order(row) for row in changed])
        self.assertEqual([row['id'] for row in sorted(original, key=self.runner.row_order)],
                         [row['id'] for row in sorted(reversed(changed), key=self.runner.row_order)])

    def run_main(self, *answers):
        transport = self.BudgetedFake(*answers)
        budget = RunBudget(max_requests=10)
        semantic = LanguageAnalyzer(transport, LanguageConfig(mode='graph', recovery='observe'), budget=budget)
        detector = Detector(semantic=semantic)
        rows = [{'id':'offline-row', 'label':0, 'prompt':'\u27e6SYSTEM\u27e7\nPolicy source.',
                 'response':'Material candidate claim'}]
        with tempfile.TemporaryDirectory() as folder:
            source = Path(folder)/'input.csv'
            source.write_text('offline fixture for hash', encoding='utf-8')
            output = Path(folder)/'out'
            argv = ['ablate_uncertainty.py', '--input', str(source), '--output-dir', str(output),
                    '--backend', 'local', '--mode', 'graph', '--bootstrap-samples', '10',
                    '--env-file', str(Path(folder)/'absent.env')]
            with patch.object(sys, 'argv', argv), \
                 patch.object(self.runner, 'read_rows', return_value=rows), \
                 patch.object(self.runner, 'load_env_file') as env_loader, \
                 patch.object(self.runner, 'detector_from_args', return_value=detector), \
                 contextlib.redirect_stdout(io.StringIO()):
                self.runner.main()
                env_loader.assert_called_once()
            record = json.loads((output/'audit.jsonl').read_text(encoding='utf-8'))
            report = json.loads((output/'report.json').read_text(encoding='utf-8'))
        return transport, budget, record, report

    def test_main_shared_first_generation_only_two_additional_calls(self):
        first = assessment('error', ['p999'])
        transport, budget, record, report = self.run_main(first, assessment(), assessment())
        self.assertEqual(len(transport.messages), 3)
        self.assertEqual(budget.requests, 3)
        self.assertEqual(report['budget']['requests'], 3)
        for branch in ('initial', 'directed', 'repeat'):
            observed = record['reviews'][branch]['reading_trace'][0]['model_assessment']
            self.assertEqual(observed['reason'], first['reason'])
            self.assertEqual(observed['claims'], first['claims'])
            self.assertEqual(record['reviews'][branch]['semantic_usage']['total_tokens'], 7)
        self.assertEqual(transport.messages[0], transport.messages[2])
        self.assertNotEqual(transport.messages[0], transport.messages[1])

    def test_main_noneligible_answer_has_no_branch_action_or_generation(self):
        transport, budget, record, _ = self.run_main(assessment())
        self.assertEqual(len(transport.messages), 1)
        self.assertEqual(budget.requests, 1)
        for branch in ('directed', 'repeat'):
            self.assertEqual(record['reviews'][branch], record['reviews']['initial'])
            self.assertNotIn('recovery', record['reviews'][branch]['reading_trace'][0])


if __name__ == '__main__':
    unittest.main()
