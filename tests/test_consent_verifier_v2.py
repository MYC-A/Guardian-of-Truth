import unittest
from scripts.judge_consent_verifier_v2_20261018 import augmented, source_from_base
from scripts.analyze_consent_verifier_v2_20261018 import authorized
from scripts.prepare_consent_seed_data_20261018 import case, DOMAINS
from guardian_truth.judge.prompting import QUESTION, JUDGE_SYSTEM


class DirectVerifierTests(unittest.TestCase):
    def test_permission_does_not_make_ineligible_action_correct(self):
        for domain in DOMAINS:
            row=case(domain,0,'ineligible')
            self.assertEqual(authorized(row['oracle']),1)
            self.assertEqual(row['label'],1)

    def test_contrast_authorization_target(self):
        for domain in DOMAINS:
            for variant in ('no_consent','revoked','object_changed','value_changed','different_action',
                            'changed_offer','ambiguous_alternatives'):
                self.assertEqual(authorized(case(domain,0,variant)['oracle']),0)
            for variant in ('literal','paraphrase','ordinary_request','consent_in_history','irrelevant_followup'):
                self.assertEqual(authorized(case(domain,0,variant)['oracle']),1)

    def test_new_hint_preserves_independent_definition_and_original_source(self):
        source='<transcript>\nOriginal source and eligibility:false\n</transcript>\n'
        base=JUDGE_SYSTEM+'\n'+source+QUESTION+'\n<assistant>'
        for score in (-5.,5.):
            text=augmented(base,score)
            self.assertIn(JUDGE_SYSTEM,text)
            self.assertIn(source,text)
            self.assertTrue(text.endswith(QUESTION+'\n<assistant>'))
            self.assertIn('YES if ANY material violation remains',text)
            self.assertEqual(source_from_base(base),source)

    def test_inexact_auth_cannot_silently_become_no(self):
        for score in (None,float('nan'),float('inf')):
            with self.assertRaises(ValueError):augmented('<transcript>\nx\n'+QUESTION,score)


if __name__=='__main__':unittest.main()
