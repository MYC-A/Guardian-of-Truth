import unittest

from guardian_truth.reason_metrics import ReasonAnnotation, reason_metrics


class ReasonMetricsTests(unittest.TestCase):
    def test_semantic_positive_denominator_excludes_mechanical_fallback_and_negatives(self):
        rows = [ReasonAnnotation('tp',1,1,'semantic',True,True),
                ReasonAnnotation('wrong_reason_tp',1,1,'semantic',False,False),
                ReasonAnnotation('fp',0,1,'semantic',False,False),
                ReasonAnnotation('hard',1,1,'mechanical',True,True),
                ReasonAnnotation('fn',1,0,'fallback'),
                ReasonAnnotation('tn',0,0,'semantic')]
        result = reason_metrics(rows)
        self.assertEqual(result['semantic_positive_decisions'],3)
        self.assertEqual(result['reason_precision']['verified_lower_bound'],1/3)
        self.assertEqual(result['wrong_labels_all_decision_sources'],2)
        self.assertEqual(result['semantic_positive_categories'],{
            'CORRECT_LABEL_CORRECT_REASON':1,'CORRECT_LABEL_WRONG_REASON':1,
            'WRONG_LABEL':1,'UNADJUDICATED_REASON_TP':0})

    def test_partial_audit_reports_bounds_not_invented_certainty(self):
        result=reason_metrics([ReasonAnnotation('yes',1,1,'semantic',True,False),
                               ReasonAnnotation('unknown',1,1,'semantic')])
        rp=result['reason_precision']
        self.assertEqual((rp['verified_lower_bound'],rp['possible_upper_bound']),(.5,1))
        self.assertEqual(rp['audit_coverage'],.5)
        self.assertEqual(rp['audited_precision'],1)
        self.assertEqual(result['semantic_positive_categories']['UNADJUDICATED_REASON_TP'],1)
        self.assertEqual(result['cited_reason_precision']['verified_correct'],0)

    def test_gold_does_not_automatically_invalidate_an_annotated_reason(self):
        # A genuine dataset/serialization disagreement must remain visible.
        result=reason_metrics([ReasonAnnotation('disputed',0,1,'semantic',True,True)])
        self.assertEqual(result['reason_precision']['verified_lower_bound'],1)
        self.assertEqual(result['semantic_positive_categories']['WRONG_LABEL'],1)

    def test_empty_denominator_is_undefined_not_perfect_or_zero(self):
        self.assertIsNone(reason_metrics([])['reason_precision']['audited_precision'])
        self.assertIsNone(reason_metrics([])['reason_precision']['verified_lower_bound'])

    def test_invalid_annotations_and_duplicate_ids_are_rejected(self):
        with self.assertRaises(ValueError):
            ReasonAnnotation('a',True,1,'semantic')
        with self.assertRaises(ValueError):
            ReasonAnnotation('a',1,1,'semantic',False,True)
        with self.assertRaises(ValueError):
            ReasonAnnotation('a',1,1,'semantic','true')
        row=ReasonAnnotation('a',1,1,'semantic')
        with self.assertRaises(ValueError):
            reason_metrics([row,row])


if __name__ == '__main__':
    unittest.main()
