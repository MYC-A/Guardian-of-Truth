"""Regression checks for the actual published training input package."""
import hashlib,json,tarfile,unittest
from pathlib import Path

ROOT=Path(__file__).resolve().parents[1]
DATA=ROOT/'docs/judge_20261013/lora_pilot_evidence_20261018'

class LoraDataTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        with tarfile.open(DATA/'training-inputs-v1b.tar.gz') as archive:
            cls.raw={m.name:archive.extractfile(m).read() for m in archive.getmembers() if m.isfile()}
        cls.rows={n:[json.loads(l) for l in raw.splitlines()] for n,raw in cls.raw.items() if n.endswith('.jsonl')}

    def test_no_evaluation_labels_in_uploaded_package(self):
        self.assertFalse(any('gold' in n for n in self.raw))
        for name,rows in self.rows.items():
            if name!='train.jsonl':self.assertTrue(all('label' not in r and 'oracle' not in r for r in rows))

    def test_no_train_validation_prefix_leak(self):
        train=self.rows['train.jsonl'];val=self.rows['natural_validation_inputs.jsonl']
        self.assertFalse({r['prompt'] for r in train}&{r['prompt'] for r in val})
        self.assertFalse({r['conversation'] for r in train}&{r['conversation'] for r in val})
        self.assertFalse({r['prompt'] for r in train}&{r['prompt'] for r in self.rows['dev520_inputs.jsonl']})

    def test_ineligibility_changes_violation_but_not_user_consent_target(self):
        train=self.rows['train.jsonl'];by={r['id']:r for r in train}
        pairs=[r for r in train if r['task']=='authorization' and ':ineligible:' in r['id']]
        self.assertEqual(len(pairs),10)
        for auth in pairs:
            whole=by[auth['id'].removesuffix(':authorization')]
            self.assertEqual(auth['label'],1)
            self.assertEqual(whole['label'],1)
            self.assertEqual(auth['prompt'],whole['prompt'])
            self.assertEqual(auth['response'],whole['response'])
            literal=by[auth['id'].replace(':ineligible:',':literal:')]
            literal_whole=by[literal['id'].removesuffix(':authorization')]
            self.assertEqual(literal['label'],1)
            self.assertEqual(literal_whole['label'],0)
            self.assertEqual(auth['prompt'].replace('"eligible":false','"eligible":true'),literal['prompt'])
            self.assertEqual(auth['response'],literal['response'])

    def test_uploaded_bytes_match_training_manifest(self):
        manifest=json.loads(self.raw['MANIFEST.json'])
        for name,raw in self.raw.items():
            if name!='MANIFEST.json':self.assertEqual(hashlib.sha256(raw).hexdigest(),manifest['files'][name]['sha256'])
        self.assertEqual(len(self.rows['train.jsonl']),666)
        self.assertEqual(len(manifest['purged_training_prefix_ids']),13)

    def test_same_task_same_input_never_has_conflicting_targets(self):
        found={}
        for r in self.rows['train.jsonl']:
            key=(r['task'],r['prompt'],r['response'])
            self.assertEqual(found.setdefault(key,r['label']),r['label'])

if __name__=='__main__':unittest.main()
