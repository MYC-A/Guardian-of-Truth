import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from candidate_bank import candidate_for, BANK, DATA
from structural_v02 import parse_case_v02
import native_helper as helper


class NativeHelperTest(unittest.TestCase):
    def test_factored_candidate_builder_is_byte_equivalent_to_frozen_bank(self):
        inputs = [json.loads(line) for line in (DATA / "dev_input.jsonl").read_text(
            encoding="utf-8").splitlines()]
        bank = [json.loads(line) for line in (BANK / "dev.jsonl").read_text(
            encoding="utf-8").splitlines()]
        self.assertEqual([candidate_for(case) for case in inputs], bank)

    def test_changed_source_with_same_id_never_reuses_score(self):
        case = json.loads((DATA / "dev_input.jsonl").read_text(encoding="utf-8").splitlines()[0])
        row = candidate_for(case)
        with tempfile.TemporaryDirectory() as temp:
            file = Path(temp) / "scores.jsonl"
            record = dict(row, model="granite", support_score=.99, native_output="no")
            file.write_text(json.dumps(record) + "\n", encoding="utf-8")
            cfg = {"model": "granite", "replay": {"results_file": str(file),
                "sha256": hashlib.sha256(file.read_bytes()).hexdigest()}}
            calls = []
            active = {"model": "granite", "score": lambda doc, claim:
                (calls.append(doc) or {"support_score": .1, "native_output": "yes"})}
            with patch.dict(helper._ACTIVE, active, clear=True):
                ctx = parse_case_v02(case["id"], case["prompt"], case["response"])
                _, result = helper.native_advisory(cfg, ctx)
                self.assertEqual(result["origin"], "FROZEN_EXACT_SOURCE_REPLAY")
                self.assertEqual(calls, [])
                ctx = parse_case_v02(case["id"], case["prompt"] + "\nUpdated source.", case["response"])
                _, result = helper.native_advisory(cfg, ctx)
                self.assertEqual(result["origin"], "LIVE_NATIVE_GPU")
                self.assertEqual(result["support_score"], .1)
                self.assertEqual(len(calls), 1)


if __name__ == "__main__":
    unittest.main()
