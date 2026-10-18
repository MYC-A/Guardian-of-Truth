import unittest
from scripts.prepare_consent_seed_data_20261018 import case,DOMAINS,VARIANTS
from guardian_truth.transcript import analyze_turn


class ConsentSeedControls(unittest.TestCase):
    def test_every_domain_has_both_labels_without_structural_shortcut(self):
        for domain in DOMAINS:
            rows=[case(domain,3,v) for v in VARIANTS]
            self.assertEqual({r['label'] for r in rows},{0,1})
            for row in rows:
                self.assertFalse(analyze_turn(row['prompt'],row['response']).hard,
                                 (domain,row['variant']))

    def test_price_and_object_counterfactuals_keep_the_same_prior_approval(self):
        for domain in DOMAINS:
            original=case(domain,4,'literal')
            for variant in ['object_changed','value_changed','different_action']:
                mutated=case(domain,4,variant)
                self.assertEqual(original['prompt'],mutated['prompt'])
                self.assertNotEqual(original['response'],mutated['response'])
                self.assertEqual(mutated['label'],1)

    def test_history_approval_is_not_forced_into_literal_latest_yes(self):
        for domain in DOMAINS:
            row=case(domain,2,'consent_in_history')
            self.assertTrue(row['prompt'].endswith('Thank you.\n'))
            self.assertEqual(row['label'],0)

    def test_authorization_does_not_override_ineligibility(self):
        for domain in DOMAINS:
            row=case(domain,2,'ineligible')
            self.assertIn('Yes, please proceed',row['prompt'])
            self.assertIn('"eligible":false',row['prompt'])
            self.assertEqual(row['label'],1)
