import copy
import unittest
from scripts.v6_verifier_data import select_pairs,verifier_text
from guardian_truth.judge.prompting import QUESTION


def pair(n,group=None,domain='retail',family='consent',template='approval'):
    return [dict(id=f'{n}:{label}',pair_id=str(n),source='tau2',domain=domain,
        family=family,template_id=template,split_component=f'c{n}',group_id=group or f'g{n}',
        label=label,proof={'confirmation':'exact' if label==0 else 'different_object'},
        audit_status='MECHANICAL_SOURCE_CHECKED_HUMAN_UNVERIFIED') for label in (0,1)]


class DataBoundary(unittest.TestCase):
    def test_whole_pairs_distinct_groups_and_stable_input_order(self):
        rows=pair(1,'same')+pair(2,'same')+pair(3)+pair(4,domain='airline')
        selected=select_pairs(rows,3)
        self.assertEqual(6,len(selected))
        self.assertEqual(3,len({r['group_id'] for r in selected}))
        self.assertEqual(selected,select_pairs(list(reversed(rows)),3))

    def test_incomplete_or_inconsistent_pair_cannot_enter_training(self):
        good=pair(1);bad=pair(2);bad[1]['split_component']='other'
        rows=good+bad+pair(3)[:1]
        self.assertEqual(select_pairs(rows,1),good)
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            select_pairs(rows,2)

    def test_unchecked_proof_and_template_flood_are_rejected(self):
        rows=sum([pair(n) for n in range(6)],[])
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            select_pairs(rows,5)
        rows=copy.deepcopy(pair(8));rows[0]['proof']={}
        with self.assertRaisesRegex(ValueError,'INSUFFICIENT'):
            select_pairs(rows,1)

    def test_current_turn_and_label_semantics_preserved(self):
        original='POLICY\nCURRENT TURN unchanged\n'+QUESTION+'\nASSISTANT'
        rendered=verifier_text(original)
        self.assertTrue(rendered.startswith('POLICY\nCURRENT TURN unchanged\n'))
        self.assertTrue(rendered.endswith(QUESTION+'\nASSISTANT'))
        self.assertEqual(1,rendered.count('<verifier_review>'))
        self.assertIn('YES means a violation is present',rendered)


if __name__=='__main__':unittest.main()
