import importlib.util
from pathlib import Path
import unittest

class ClaimGateTests(unittest.TestCase):
    def test_shadow_does_not_override_hard_violation_or_mutate_review(self):
        path=Path(__file__).parents[1]/'scripts'/'ablate_claim_gate.py'
        spec=importlib.util.spec_from_file_location('claim_gate_script',path)
        module=importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        from guardian_truth.pipeline import Detector
        review=Detector().review('Context','Candidate')
        review.reading_trace=[{'overall_assessment':{'score':.9}}]
        strict,overall=module.gate_decisions(review)
        self.assertTrue(strict.used_fallback)
        self.assertEqual(overall.label,1)
        self.assertIsNone(review.semantic_score)
        review.status='violation'
        review.reading_trace[-1]['overall_assessment']['score']=0
        self.assertEqual([d.label for d in module.gate_decisions(review)],[1,1])
