import json
from pathlib import Path
import tempfile
import unittest
from scripts.eval_policyguard_20261018 import parse_label, transfer_prompt, load_requests


class PolicyGuardContractTest(unittest.TestCase):
    def test_invalid_generation_does_not_become_accusation(self):
        for text in ('', 'maybe', 'not a violation', 'no_violation because...', 'violation or no_violation'):
            self.assertIsNone(parse_label(text))
        self.assertEqual(parse_label(' no_violation\n'),0)
        self.assertEqual(parse_label('violation'),1)

    def test_source_and_current_turn_are_separate_and_verbatim(self):
        policy='\u27e6SYSTEM\u27e7\n<policy>Confirm item ID before buying.</policy>\n'
        history='\u27e6USER\u27e7\nConfirmed item 12.\n\u27e6ASSISTANT\u27e7\nPurchased 13.\n'
        response='\u27e6ASSISTANT\u27e7\nWhich item did you mean?\n'
        prompt=transfer_prompt(policy+history,response)
        self.assertIn('Policy: '+policy,prompt)
        self.assertIn('Trajectory Actions (history, context only):\n'+history,prompt)
        self.assertIn('Current turn under review:\n'+response,prompt)
        self.assertIn('Earlier turns are context',prompt)

    def test_missing_system_fails_instead_of_dropping_content(self):
        with self.assertRaises(ValueError):
            transfer_prompt('\u27e6USER\u27e7\nHello','Hi')

    def test_inference_refuses_gold_column(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'inputs.csv'
            path.write_text('id,prompt,response,label\n1,p,r,0\n')
            with self.assertRaisesRegex(ValueError,'MUST_NOT_CONTAIN_LABELS'):
                load_requests(path,'transfer',0)

    def test_native_inference_refuses_gold_in_json(self):
        with tempfile.TemporaryDirectory() as directory:
            path=Path(directory)/'input.jsonl'
            path.write_text(json.dumps(dict(id='a',policy_and_trajectory='Policy: p',label=0))+'\n')
            with self.assertRaisesRegex(ValueError,'MUST_NOT_CONTAIN_LABELS'):
                load_requests(path,'native',0)

    def test_long_source_is_preserved(self):
        history='\u27e6USER\u27e7\n'+'x'*150000+'KNOWN_EARLY_RESULT\n'
        prompt='\u27e6SYSTEM\u27e7\nPolicy\n'+history
        result=transfer_prompt(prompt,'Exact current action')
        self.assertIn(history,result)
        self.assertIn('Exact current action',result)
