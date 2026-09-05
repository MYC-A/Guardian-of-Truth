import json
import math
import unittest
from unittest.mock import patch

from guardian_truth.language import BudgetExceeded, LanguageAnalyzer, LanguageConfig, RunBudget
from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.pipeline import Detector


def assessment(verdict='ok', risk=0.1, claim='supported', ids=None):
    return {'verdict': verdict, 'risk': risk, 'reason': 'Material assessment',
            'evidence_ids': ['prompt'], 'claims': [
                {'text': 'Material claim', 'verdict': claim, 'reason': 'Evidence comparison',
                 'evidence_ids': ['prompt'] if ids is None else ids}],
            'requests': [], 'plan': []}


class FakeClient:
    def __init__(self, *outputs):
        self.outputs = iter(outputs)
        self.messages = []

    def complete(self, messages):
        self.messages.append(messages)
        output = next(self.outputs)
        if isinstance(output, Exception):
            raise output
        return Completion(json.dumps(output), {'total_tokens': 10})


class LanguageTests(unittest.TestCase):
    def test_shadow_gate_recovers_score_without_changing_production(self):
        review, client = self.review(assessment(ids=['response']))
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_claim_missing_grounding',review.unresolved)
        shadow=review.reading_trace[-1]['overall_assessment']
        self.assertEqual(shadow['score'],.1)
        self.assertTrue(all(f['status']=='hypothesis' for f in shadow['findings']))
        self.assertEqual(len(client.messages),1)
        self.assertEqual(review.status,'unknown')

    def test_shadow_gate_still_requires_valid_global_grounding(self):
        for ids in (['response'],['missing'],[],None):
            output=assessment(); output['evidence_ids']=ids
            review,_=self.review(output)
            self.assertIsNone(review.reading_trace[-1]['overall_assessment']['score'])

    def test_shadow_gate_preserves_unknown_and_inconsistent_verdict(self):
        for output in (assessment('unknown'),assessment('error',.1)):
            review,_=self.review(output)
            self.assertIsNone(review.reading_trace[-1]['overall_assessment']['score'])

    def review(self, output, *, budget=None, prompt='Authoritative context.', config=None):
        client = FakeClient(output)
        analyzer = LanguageAnalyzer(client, config or LanguageConfig(mode='direct'), budget=budget)
        return Detector(semantic=analyzer).review(prompt, 'Candidate claim.'), client

    def test_grounded_scores_remain_hypotheses(self):
        for verdict, risk, claim in (('ok', 0.1, 'supported'), ('error', 0.9, 'contradicted')):
            with self.subTest(verdict=verdict):
                review, _ = self.review(assessment(verdict, risk, claim))
                self.assertEqual(review.semantic_score, risk)
                self.assertEqual(review.status, 'unknown')
                self.assertTrue(all(f.status == 'hypothesis' for f in review.findings))

    def test_contradicted_claim_cannot_receive_ok_score(self):
        review, _ = self.review(assessment(claim='contradicted'))
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_inconsistent_claims', review.unresolved)

    def test_error_needs_grounded_contradicted_claim(self):
        for claim in ('supported', 'unknown'):
            review, _ = self.review(assessment('error', 0.9, claim))
            self.assertIsNone(review.semantic_score)
            self.assertIn('language_inconsistent_claims', review.unresolved)

    def test_unknown_material_claim_prevents_ok(self):
        output = assessment()
        unknown = assessment(claim='unknown')['claims'][0]
        output['claims'].append(unknown)
        review, _ = self.review(output)
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_claims_unknown', review.unresolved)

    def test_independent_error_can_coexist_with_unknown_claim(self):
        output = assessment('error', 0.9, 'contradicted')
        output['claims'].append(assessment(claim='unknown')['claims'][0])
        review, _ = self.review(output)
        self.assertEqual(review.semantic_score, 0.9)

    def test_candidate_alone_does_not_ground_definitive_claims(self):
        for verdict, risk, claim in (('ok', 0.1, 'supported'), ('error', 0.9, 'contradicted')):
            review, _ = self.review(assessment(verdict, risk, claim, ['response']))
            self.assertIsNone(review.semantic_score)
            self.assertIn('language_claim_missing_grounding', review.unresolved)

    def test_supported_plan_requires_independent_evidence(self):
        output = assessment()
        output['plan'] = [{'tool': 'lookup', 'status': 'supported', 'reason': 'Proposed plan',
                           'evidence_ids': ['response']}]
        prompt = '⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- lookup — Read records.\n'
        review, _ = self.review(output, prompt=prompt)
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_plan_missing_grounding', review.unresolved)

    def test_all_client_error_categories_are_preserved_without_details(self):
        categories = ('authentication', 'forbidden', 'rate_limit', 'timeout', 'configuration', 'missing_api_key',
                      'invalid_api_key', 'invalid_request', 'invalid_response', 'truncated',
                      'connection', 'server', 'redirect', 'http_request', 'transport',
                      'request_too_large', 'model_or_endpoint_unavailable')
        for category in categories:
            with self.subTest(category=category):
                review, _ = self.review(ChatClientError(category))
                self.assertIn('language_' + category, review.unresolved)
                self.assertIsNone(review.semantic_score)
        review, _ = self.review(ChatClientError('synthetic-secret-text'))
        self.assertIn('language_client_error', review.unresolved)
        self.assertNotIn('synthetic-secret-text', repr(review))

    def test_late_fake_completion_is_discarded(self):
        now = [0.0]
        class Late(FakeClient):
            def complete(self, messages):
                now[0] = 100.0
                return super().complete(messages)
        with patch('guardian_truth.language.time.monotonic', side_effect=lambda: now[0]):
            budget = RunBudget(seconds=1)
            analyzer = LanguageAnalyzer(Late(assessment()), LanguageConfig(mode='direct'), budget=budget)
            review = Detector(semantic=analyzer).review('Context', 'Candidate')
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_run_budget_exceeded', review.unresolved)

    def test_budgeted_client_does_not_reserve_twice(self):
        class Budgeted(FakeClient):
            def complete_budgeted(self, messages, *, budget):
                budget.reserve(sum(len(message['content']) for message in messages))
                return self.complete(messages)
        budget = RunBudget(max_requests=1)
        analyzer = LanguageAnalyzer(Budgeted(assessment()), LanguageConfig(mode='direct'), budget=budget)
        review = Detector(semantic=analyzer).review('Context', 'Candidate')
        self.assertEqual(review.semantic_score, 0.1)
        self.assertEqual(budget.summary()['requests'], 1)

    def test_unread_citation_is_rejected(self):
        output = assessment(ids=['p999'])
        output['evidence_ids'] = ['p0']
        review, _ = self.review(output, config=LanguageConfig(mode='graph'),
                                prompt='⟦SYSTEM⟧\nAuthoritative context.')
        self.assertIsNone(review.semantic_score)
        self.assertIn('language_invalid_citation', review.unresolved)


class RunBudgetTests(unittest.TestCase):
    def test_invalid_limits_are_rejected(self):
        for name in ('max_requests', 'max_input_chars', 'seconds'):
            for value in (float('nan'), float('inf'), -1, 0, True, '1'):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    RunBudget(**{name: value})
        for name in ('max_requests', 'max_input_chars'):
            with self.subTest(name=name), self.assertRaises(ValueError):
                RunBudget(**{name: 1.5})

    def test_invalid_language_limits_are_rejected(self):
        for name in ('max_rounds', 'max_evidence_chars', 'max_prompt_chars'):
            for value in (float('nan'), float('inf'), True, 1.5):
                with self.subTest(name=name, value=value), self.assertRaises(ValueError):
                    LanguageConfig(**{name: value})

    def test_reservations_cannot_reduce_usage(self):
        budget = RunBudget(max_requests=1, max_input_chars=10)
        for value in (-1, True, 1.5, math.nan):
            with self.assertRaises(ValueError):
                budget.reserve(value)
        budget.reserve(10)
        with self.assertRaises(BudgetExceeded):
            budget.reserve(0)
        self.assertEqual(budget.summary()['input_chars'], 10)


if __name__ == '__main__':
    unittest.main()
