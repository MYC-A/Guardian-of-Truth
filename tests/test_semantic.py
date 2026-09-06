import unittest

from guardian_truth.pipeline import Detector
from guardian_truth.semantic import SemanticResult
from guardian_truth.types import Finding, Source


class SemanticTests(unittest.TestCase):
    def test_default_backend_is_none(self):
        review = Detector().review('Hello', 'Hello')
        self.assertEqual(review.semantic_backend, 'none')
        self.assertEqual(review.status, 'unknown')

    def test_backend_gets_structured_context_without_labels(self):
        captured = []
        class Fake:
            name = 'fake-local'
            def analyze(self, context):
                captured.append(context)
                return SemanticResult([Finding('meaning', 'Proposed discrepancy', [Source('response',0,5)])])
        review = Detector(semantic=Fake()).review('Hello', 'Hello')
        self.assertEqual(review.status, 'unknown')
        self.assertEqual(review.findings[0].status, 'hypothesis')
        self.assertEqual(review.semantic_backend, 'fake-local')
        context = captured[0]
        for field in ('label','explanation','id'):
            self.assertFalse(hasattr(context, field))
        for field in ('catalog','history','candidate','graph','obligations','evidence'):
            self.assertTrue(hasattr(context, field))

    def test_backend_failure_preserves_exact_verdict(self):
        class Broken:
            name = 'broken'
            def analyze(self, context):
                raise RuntimeError('secret backend information')
        prompt = '⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- known — Read.\n'
        response = '⟦ASSISTANT_TOOL_CALL name="missing"⟧\n{}'
        review = Detector(semantic=Broken()).review(prompt, response)
        self.assertEqual(review.status, 'violation')
        self.assertIn('semantic_backend_error', review.unresolved)
        self.assertNotIn('secret', str(review))

    def test_opt_in_backend_skips_after_mechanical_proof(self):
        class MustNotRun:
            name = 'language:decomposed'
            skip_when_mechanical_violation = True
            def analyze(self, context):
                raise AssertionError('semantic backend must not run')
        prompt = '⟦SYSTEM⟧\n[AVAILABLE TOOLS]\n- known — Read.\n'
        response = '⟦ASSISTANT_TOOL_CALL name="missing"⟧\n{}'
        review = Detector(semantic=MustNotRun()).review(prompt, response)
        self.assertEqual(review.status, 'violation')
        self.assertIn('unavailable_tool', {item.code for item in review.findings})
        self.assertEqual(review.reading_trace,
                         [{'stage':'mechanical_short_circuit','call':None,'valid':True}])
        self.assertEqual(review.semantic_usage, {'llm_calls':0})
        self.assertNotIn('semantic_backend_error', review.unresolved)

    def test_invalid_output_is_rejected(self):
        class Invalid:
            name = 'invalid'
            def analyze(self, context):
                return {'label':1}
        review = Detector(semantic=Invalid()).review('Hello','Hello')
        self.assertIn('semantic_invalid_output', review.unresolved)
        self.assertEqual(review.status, 'unknown')

    def test_invalid_spans_rejected(self):
        class Invalid:
            name = 'invalid'
            def analyze(self, context):
                return SemanticResult([
                    Finding('a','bad',[Source('explanation',0,1)]),
                    Finding('b','bad',[Source('prompt',0,100)]),
                    Finding('c','bad',[Source('response',-1,2)]),
                    Finding('d','bad',[Source('response',1,1)]),
                ])
        review = Detector(semantic=Invalid()).review('Hello','Hello')
        self.assertFalse(review.findings)
        self.assertIn('semantic_invalid_finding', review.unresolved)

    def test_backend_output_not_mutated(self):
        finding = Finding('guess','Proposed violation', [])
        class Fake:
            name = 'fake'
            def analyze(self, context):
                return SemanticResult([finding])
        review = Detector(semantic=Fake()).review('Hello','Hello')
        self.assertEqual(finding.status, 'violation')
        self.assertEqual(review.findings[0].status, 'hypothesis')
        self.assertIn('semantic_uncited_hypothesis', review.unresolved)

    def test_legacy_and_new_backend_cannot_both_be_selected(self):
        from guardian_truth.semantic import NoSemanticAnalyzer
        with self.assertRaises(ValueError):
            Detector(checker=object(), semantic=NoSemanticAnalyzer())


if __name__ == '__main__':
    unittest.main()
