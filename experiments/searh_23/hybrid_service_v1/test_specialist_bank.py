"""Integrity and scorer contract checks; no model downloads or API calls."""
import hashlib
import json
import tempfile
import unittest
from pathlib import Path

from candidate_bank import BANK, DATA
from score_specialist import score


class SpecialistBankTest(unittest.TestCase):
    def test_frozen_inputs_have_one_gold_blind_candidate_each(self):
        manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
        source_manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
        for split in ("dev", "sealed"):
            bank_path = BANK / f"{split}.jsonl"
            source_path = DATA / f"{split}_input.jsonl"
            self.assertEqual(hashlib.sha256(bank_path.read_bytes()).hexdigest(),
                             manifest["splits"][split]["sha256"])
            self.assertEqual(hashlib.sha256(source_path.read_bytes()).hexdigest(),
                             manifest["splits"][split]["source_input_sha256"])
            self.assertEqual(manifest["splits"][split]["source_input_sha256"],
                             source_manifest["splits"][split]["input_sha256"])
            rows = [json.loads(line) for line in bank_path.read_text(
                encoding="utf-8").splitlines()]
            original = [json.loads(line) for line in source_path.read_text(
                encoding="utf-8").splitlines()]
            self.assertEqual([r["id"] for r in rows], [r["id"] for r in original])
            self.assertEqual(len(rows), manifest["splits"][split]["n"])
            for row, source in zip(rows, original):
                self.assertEqual(row["document"], source["prompt"])
                self.assertEqual(row["target_quote"], source["response"])
                self.assertLessEqual(len(row["document"].split()), 500)
                self.assertNotIn("label", row)

    def test_scorer_rejects_incomplete_before_opening_gold(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            (folder / "run_config.json").write_text(json.dumps({"split": "dev"}))
            (folder / "status.json").write_text(json.dumps({"state": "RUNNING"}))
            with self.assertRaisesRegex(ValueError, "before complete run"):
                score(folder)

    def test_scorer_counts_invalid_as_no_error(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
            bank = [json.loads(line) for line in (BANK / "dev.jsonl").read_text(
                encoding="utf-8").splitlines()]
            ids = [bank[0]["id"], bank[2]["id"]]  # NO_ERROR, ERROR
            config = {"model": "factcg", "split": "dev", "case_ids": ids,
                      "bank_sha256": manifest["splits"]["dev"]["sha256"],
                      "threshold": .5}
            (folder / "run_config.json").write_text(json.dumps(config))
            (folder / "status.json").write_text(json.dumps(
                {"state": "SUCCEEDED", "run_id": "test"}))
            records = [
                {"run_id": "test", "id": ids[0], "status": "VALID",
                 "support_score": .9, "elapsed_s": .2},
                {"run_id": "test", "id": ids[1], "status": "INVALID",
                 "support_score": None, "elapsed_s": .3},
            ]
            (folder / "scores.jsonl").write_text("".join(
                json.dumps(row) + "\n" for row in records))
            report = score(folder)
            self.assertEqual(report["coverage"], .5)
            self.assertEqual(report["all_cases"]["fn"], 1)
            self.assertEqual(report["conditional_valid"]["tn"], 1)


if __name__ == "__main__":
    unittest.main()
