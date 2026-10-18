import hashlib
import json
from pathlib import Path
import tempfile
import unittest

from guardian_truth.judge import blind_review as br
from guardian_truth.judge.review_stage import PrimaryInputs
from scripts.judge_stage import row_digest
from scripts.replay_judge_notes_20261018 import close_source


class SourceClosureTests(unittest.TestCase):
    def fixture(self, p, wrong_digest=False):
        cfg = dict(review_mode='open', review_content='answer_audit', review_schedule='per_chunk',
                   review_ranking='max_exact', review_input_reserve_tokens=2048)
        (p/'judge_config.json').write_text(json.dumps(cfg))
        row = dict(key=0, prompt='policy', response='turn', hints=[])
        (p/'stage_input.jsonl').write_text(json.dumps(row)+'\n')
        saved = dict(key=0, text='rendered input',
                     input_sha256=hashlib.sha256((p/'stage_input.jsonl').read_bytes()).hexdigest(),
                     row_sha256=row_digest(row['prompt'], row['response']) if wrong_digest else PrimaryInputs.row_sha(row),
                     model_input_sha256=br.sha('rendered input'))
        (p/'primary-inputs-test.jsonl').write_text(json.dumps(saved)+'\n')
        (p/'scores.jsonl').write_text(json.dumps(dict(key=0, review='prepass'))+'\n'+
                                    json.dumps(dict(key=0, review='final', base_sha256=br.sha('rendered input')))+'\n')

    def test_uses_actual_primary_spool_hash_contract(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p)
            self.assertEqual(close_source(p)[-1], [0])

    def test_other_row_hash_contract_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p, wrong_digest=True)
            with self.assertRaisesRegex(ValueError, 'SAVED_SOURCE_IDENTITY'):
                close_source(p)

    def test_modified_stage_input_is_rejected(self):
        with tempfile.TemporaryDirectory() as d:
            p=Path(d);self.fixture(p)
            row=json.loads((p/'stage_input.jsonl').read_text());row['response']='changed'
            (p/'stage_input.jsonl').write_text(json.dumps(row)+'\n')
            with self.assertRaisesRegex(ValueError, 'SAVED_SOURCE_IDENTITY'):
                close_source(p)


if __name__=='__main__':
    unittest.main()
