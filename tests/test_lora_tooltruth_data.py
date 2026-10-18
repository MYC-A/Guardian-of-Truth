"""Published-data safeguards for the new training targets and upload boundary."""
import hashlib
import json
import tarfile
import unittest
from pathlib import Path
from guardian_truth.transcript import parse_document, analyze_turn

DATA=Path(__file__).resolve().parents[1]/'docs/judge_20261013/lora_tooltruth_evidence_20261018'


class ToolTruthData(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(DATA/'data-audit-inputs.tar.gz') as t:
            cls.raw={m.name:t.extractfile(m).read() for m in t.getmembers() if m.isfile()}
        cls.train=[json.loads(l) for l in cls.raw['train.jsonl'].splitlines()]
        cls.controlled=[json.loads(l) for l in cls.raw['tooltruth_train_gold.jsonl'].splitlines()]
        cls.validation=[json.loads(l) for l in cls.raw['tooltruth_validation_gold.jsonl'].splitlines()]

    def test_uploaded_package_has_only_training_targets(self):
        with tarfile.open(DATA/'training-inputs-v2.tar.gz') as t:
            uploaded={m.name:t.extractfile(m).read() for m in t.getmembers() if m.isfile()}
        self.assertFalse(any('gold' in n for n in uploaded))
        manifest=json.loads(uploaded['GPU_MANIFEST.json'])
        for n,r in manifest['files'].items():
            self.assertEqual(hashlib.sha256(uploaded[n]).hexdigest(),r['sha256'])
        for n in ['natural_validation_inputs.jsonl','tooltruth_validation_inputs.jsonl','tooltruth_primary_inputs.jsonl']:
            self.assertTrue(all('label' not in r and 'oracle' not in r for r in map(json.loads,uploaded[n].splitlines())))

    def test_evaluation_entities_and_prefixes_are_separate(self):
        self.assertEqual(len(self.train),666)
        self.assertEqual(len(self.controlled),420)
        self.assertEqual(len(self.validation),168)
        self.assertFalse({r['group'] for r in self.train}&{r['group'] for r in self.validation})
        self.assertFalse({r['prompt'] for r in self.train}&{r['prompt'] for r in self.validation})

    def test_same_claim_and_same_action_can_have_opposite_truth(self):
        for family in ['completion','consent']:
            pairs={}
            for r in self.controlled+self.validation:
                if r['family']==family:pairs.setdefault(r['conversation'],[]).append(r)
            for rows in pairs.values():
                self.assertEqual({r['label'] for r in rows},{0,1})
                self.assertEqual(rows[0]['response'],rows[1]['response'])
                self.assertNotEqual(rows[0]['prompt'],rows[1]['prompt'])

    def test_confirmation_does_not_clear_ineligible_action(self):
        for r in self.controlled+self.validation:
            if r['family']=='eligibility' and not r['oracle']['eligible']:
                self.assertIn('Yes, cancel',r['prompt'])
                calls=parse_document(r['response'],doc='response').calls(owner='assistant')
                self.assertEqual(r['label'],int(calls[0].tool!='transfer_to_human_agents'))

    def test_permitted_transfer_can_contain_a_false_claim(self):
        for r in self.controlled+self.validation:
            if r['family']=='summary':
                c=parse_document(r['response'],doc='response').calls(owner='assistant')
                self.assertEqual(len(c),1)
                self.assertEqual(c[0].tool,'transfer_to_human_agents')
                self.assertEqual(r['label'],int('full refund has already arrived' in c[0].value['summary']))
                self.assertFalse(analyze_turn(r['prompt'],r['response']).hard)

    def test_style_controls_remove_superficial_corruption_cues(self):
        records=json.loads(self.raw['SOURCE_RECORDS.json'])
        with tarfile.open(DATA/'style-probe-controls.tar.gz') as t:
            rows=[json.loads(l) for l in t.extractfile('style_probe_gold.jsonl').read().splitlines()]
        self.assertEqual(len(rows),72)
        self.assertEqual(sum(r['label'] for r in rows),36)
        for r in rows:
            self.assertNotIn('different.',r['response'])
            if r['family'] in ('fact','history_scope'):
                actual=records[r['domain']+':'+r['oracle']['user_id']]['user']['email']
                claimed=r['response'].split()[-1].removesuffix('.')
                self.assertEqual(r['label'],int(claimed!=actual))
            else:
                c=parse_document(r['response'],doc='response').calls(owner='assistant')[0]
                expected=r['oracle']['eligible_id']
                argument=next(iter(c.value.values()))
                self.assertEqual(len(argument),len(expected))
                self.assertEqual(r['label'],int(argument!=expected))


if __name__=='__main__':unittest.main()
