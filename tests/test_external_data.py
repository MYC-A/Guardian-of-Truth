import unittest
from guardian_truth.external_data import adapt_ragtruth


class ExternalDataTests(unittest.TestCase):
    def source(self,key='a'): return {'source_id':key,'prompt':'Facts about '+key,'task_type':'QA'}
    def response(self,key='a',identity='1',**kwargs):
        return {'source_id':key,'id':identity,'response':'A factual response '+identity,
                'split':'test','quality':'good','labels':[],**kwargs}

    def test_implicit_truth_is_not_positive_error(self):
        rows=[self.response(identity='1',labels=[{'implicit_true':True}]),
              self.response(identity='2',labels=[{'implicit_true':False}])]
        examples,report=adapt_ragtruth([self.source()],rows)
        self.assertEqual([e.label for e in examples],[0,1])
        self.assertEqual(len({e.component for e in examples}),1)
        self.assertEqual(report['splits']['test'],2)

    def test_refusal_and_truncation_not_silently_negatives(self):
        rows=[self.response(),self.response(identity='2',quality='incorrect_refusal'),
              self.response(identity='3',quality='truncated')]
        examples,report=adapt_ragtruth([self.source()],rows)
        self.assertEqual(len(examples),1)
        self.assertEqual(report['excluded']['non_good_quality'],2)

    def test_original_test_not_moved_to_calibration(self):
        examples,_=adapt_ragtruth([self.source()],[self.response()])
        self.assertEqual(examples[0].split,'test')

    def test_cross_split_source_is_rejected(self):
        with self.assertRaises(ValueError):
            adapt_ragtruth([self.source()],[self.response(),self.response(identity='2',split='train')])

    def test_selection_independent_of_labels(self):
        sources=[self.source(str(i)) for i in range(10)]
        rows=[self.response(str(i),str(i)) for i in range(10)]
        a,_=adapt_ragtruth(sources,rows,max_groups_per_split=3)
        b,_=adapt_ragtruth(sources,[{**r,'labels':[{}]} for r in rows],max_groups_per_split=3)
        self.assertEqual([e.id for e in a],[e.id for e in b])
        self.assertTrue(all('labels' not in e.prompt for e in b))


if __name__=='__main__': unittest.main()
