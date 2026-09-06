"""Offline measurement invariants, not a test of semantic relevance."""

import importlib.util
from pathlib import Path
import unittest

from guardian_truth.pipeline import Detector


class ReaderSelectionMeasurementTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        path = Path(__file__).parents[1]/'scripts'/'ablate_reader_selection.py'
        spec = importlib.util.spec_from_file_location('reader_selection_test_runner', path)
        cls.runner = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(cls.runner)

    def test_union_deduplicates_overlapping_and_touching_intervals(self):
        self.assertEqual(self.runner.union([(5,15),(0,10),(15,20),(0,10)]), [[0,20]])

    def test_coverage_does_not_double_count_selected_or_audited_characters(self):
        result = self.runner.coverage([(0,10),(5,15)], [(7,12),(10,20)])
        self.assertEqual(result['union_chars'], 15)
        self.assertEqual(result['covered_union_chars'], 8)
        self.assertEqual(result['partial'], 2)
        self.assertEqual(result['full'], 0)

    def test_empty_evidence_has_no_invented_coverage(self):
        result = self.runner.coverage([], [(0,10)])
        self.assertEqual(result['spans'], 0)
        self.assertIsNone(result['union_character_coverage'])

    def test_removing_priority_does_not_change_case_without_entity_or_result(self):
        probe = self.runner.SelectionProbe()
        review = Detector(semantic=probe).review(
            '\u27e6SYSTEM\u27e7\n'+'General policy. '*400+'\n\u27e6USER\u27e7\nQuestion.', 'Answer.')
        self.assertNotIn('semantic_backend_error', review.unresolved)
        self.assertEqual(probe.selections['current'], probe.selections['without_priority'])
        self.assertLessEqual(probe.selections['current']['chars'], 4800)


if __name__ == '__main__':
    unittest.main()
