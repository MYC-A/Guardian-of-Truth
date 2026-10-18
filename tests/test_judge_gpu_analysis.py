import unittest
from scripts.analyze_judge_gpu_run_20261018 import scope_result


class SavedGpuAnalysisTests(unittest.TestCase):
    def fixture(self):
        rows = [dict(id=str(i), primary=a, final=b, hard=False)
                for i,(a,b) in enumerate(zip([2.,3.,1.,0.],[3.,0.,2.,1.]))]
        gold = [dict(label=y, group='family'+str(i//2)) for i,y in enumerate([1,0,1,0])]
        return rows,gold

    def test_final_can_correct_max_retained_false_alarm(self):
        rows,gold = self.fixture()
        result = scope_result(rows,gold,list(range(4)))
        methods=result['methods']
        self.assertEqual(methods['available_max']['f1_at_rate']['0.4']['fp'],1)
        self.assertEqual(methods['final_only']['f1_at_rate']['0.4']['fp'],0)
        self.assertEqual(result['primary_comparison']['delta_f1'],.5)
        self.assertEqual(result['primary_comparison']['grouped_ci']['groups'],2)

    def test_missing_final_is_reported_without_overall_substitution(self):
        rows,gold = self.fixture(); rows[2]['final']=None
        result = scope_result(rows,gold,list(range(4)))
        self.assertEqual(result['methods']['final_only']['missing'],1)
        self.assertEqual(result['methods']['available_max']['missing'],0)
        self.assertEqual(result['methods']['final_only']['ranking_scope'],'EXACT_SUBSET_ONLY')

    def test_hard_override_shared_and_repeatable(self):
        rows,gold = self.fixture(); rows[3]['hard']=True
        first=scope_result(rows,gold,list(range(4)))
        second=scope_result(rows,gold,list(range(4)))
        self.assertEqual(first,second)
        for method in first['methods'].values():
            self.assertGreaterEqual(method['f1_at_rate']['0.3']['fp'],1)


if __name__=='__main__':
    unittest.main()
