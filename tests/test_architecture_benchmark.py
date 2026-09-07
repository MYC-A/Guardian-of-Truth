import importlib.util
from pathlib import Path
import unittest


SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'benchmark_architecture.py'
SPEC=importlib.util.spec_from_file_location('benchmark_architecture',SCRIPT)
BENCHMARK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class ArchitectureBenchmarkTests(unittest.TestCase):
    def test_quota_window_is_deterministic_and_bounded(self):
        rows=[{'id':str(i)} for i in range(5)]
        self.assertEqual([row['id'] for row in BENCHMARK.window_rows(rows,1,2)],['1','2'])
        self.assertEqual([row['id'] for row in BENCHMARK.window_rows(rows,3,None)],['3','4'])
        for start,count in ((-1,1),(5,1),(0,0)):
            with self.subTest(start=start,count=count),self.assertRaises(ValueError):
                BENCHMARK.window_rows(rows,start,count)

    def test_call_telemetry_counts_only_real_structured_calls(self):
        records=[{'review':{'reading_trace':[
            {'stage':'extractor','call':1,'valid':True},
            {'stage':'routing','call':None,'valid':True},
            {'stage':'semantic_verifier','call':2,'valid':False},
            {'stage':'semantic_verifier','call':3,'valid':True,
             'relations':{'c1':'SUPPORTED','c2':'INSUFFICIENT'}},
            {'stage':'final_judge','call':4,'valid':True},
        ]}}]
        result=BENCHMARK.call_telemetry(records)
        self.assertEqual((result['total'],result['valid'],result['invalid']),(4,3,1))
        self.assertEqual(result['by_stage']['semantic_verifier'],
                         {'total':2,'valid':1,'invalid':1})
        self.assertEqual(result['semantic_relation_counts'],
                         {'INSUFFICIENT':1,'SUPPORTED':1})

    def test_one_shot_call_validity_uses_usage_and_parsed_rounds(self):
        records=[{'review':{'semantic_usage':{'llm_calls':1},
                            'reading_trace':[{'round':1}] }},
                 {'review':{'semantic_usage':{'llm_calls':1},
                            'reading_trace':[]}}]
        result=BENCHMARK.call_telemetry(records)
        self.assertEqual(result['by_stage']['one_shot'],
                         {'total':2,'valid':1,'invalid':1})


if __name__=='__main__':
    unittest.main()
