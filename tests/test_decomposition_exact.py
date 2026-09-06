import unittest

from guardian_truth.decomposition import MaterialCheck
from guardian_truth.decomposition_exact import resolve_exact
from guardian_truth.semantic import AnalysisContext
from guardian_truth.types import Catalog,EvidenceGraph,Source


def resolve(text,kind='value'):
    check=MaterialCheck('c1','explicit calculation',kind,Source('response',0,len(text)))
    context=AnalysisContext('',text,[],[],Catalog({},None,False,[]),[],EvidenceGraph(),[])
    return resolve_exact(check,context)


class ExactDecompositionTests(unittest.TestCase):
    def test_addition_multiplication_and_comparison(self):
        for text,relation in [('$317 + $343 = $660','SUPPORTED'),
                              ('3 * 4 = 11','CONTRADICTED'),
                              ('4200 < 5000','SUPPORTED'),
                              ('10 > 20','CONTRADICTED')]:
            with self.subTest(text=text):
                proof=resolve(text)
                self.assertEqual(proof.relation,relation)
                self.assertEqual(proof.sources,(Source('response',0,len(text)),))

    def test_ambiguous_digit_classes_abstain(self):
        for text in ('2024-05-27 = 1992','HAT317 + HAT343 = HAT660',
                     '#317 + #343 = #660','v3.1 < v4.0','15% < 20%',
                     'order317 + 343 = 660','317 / 343 = 0.9',
                     '317 - 343 = -26','1 USD + 2 USD = 3 USD',
                     'flight 317 + 343 = 660','order 317 + 343 = 660',
                     'version 3 < 4','год 2024 > 2023'):
            with self.subTest(text=text): self.assertIsNone(resolve(text))

    def test_multiple_expressions_and_wrong_type_abstain(self):
        self.assertIsNone(resolve('1 + 1 = 2 and 2 + 2 = 4'))
        self.assertIsNone(resolve('1 + 1 = 2','entity'))


if __name__=='__main__': unittest.main()
