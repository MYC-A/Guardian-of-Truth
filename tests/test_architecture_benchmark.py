import importlib.util
from pathlib import Path
import unittest


SCRIPT=Path(__file__).resolve().parents[1]/'scripts'/'benchmark_architecture.py'
SPEC=importlib.util.spec_from_file_location('benchmark_architecture',SCRIPT)
BENCHMARK=importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(BENCHMARK)


class ArchitectureBenchmarkTests(unittest.TestCase):
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


if __name__=='__main__':
    unittest.main()
