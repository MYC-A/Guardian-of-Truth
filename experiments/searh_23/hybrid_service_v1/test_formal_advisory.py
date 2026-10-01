"""Formal shadow wiring preserves uncertainty and pins the complete journal."""
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path.insert(0, str(ROOT / "service"))
from runtime import GuardianServiceRuntime  # noqa: E402
from modular_helpers import formal_advisory  # noqa: E402


class FormalAdvisoryTest(unittest.TestCase):
    def test_advisory_never_calls_relation_a_certified_verdict(self):
        text, coverage = formal_advisory({"status": "VALID",
            "relation": "CONTRADICTS", "reason": "derived",
            "translation": {"status": "FORMALIZED", "atoms": []},
            "proof": []})
        self.assertEqual(coverage["formal"], "ADVISORY")
        self.assertIn("MODEL_TRANSLATION_UNVERIFIED", text)
        self.assertIn("provenance only", text)
        self.assertNotIn('"status":"CONFIRMED"', text)

    def test_runtime_refuses_changed_or_incomplete_journal(self):
        with tempfile.TemporaryDirectory() as temp:
            folder = Path(temp)
            journal = folder / "results.jsonl"
            journal.write_text(json.dumps({"run_id": "r1", "id": "c1",
                "status": "VALID", "relation": "INSUFFICIENT"}) + "\n")
            digest = hashlib.sha256(journal.read_bytes()).hexdigest()
            (folder / "status.json").write_text(json.dumps(
                {"run_id": "r1", "state": "RUNNING"}))
            config = {"config_id": "test", "stages": {
                "formal_advisory": {"results_file": str(journal),
                                    "sha256": digest, "run_id": "r1"}}}
            with patch("runtime.load_config", return_value=config):
                with self.assertRaisesRegex(ValueError, "incomplete"):
                    GuardianServiceRuntime("test")
                (folder / "status.json").write_text(json.dumps(
                    {"run_id": "r1", "state": "SUCCEEDED"}))
                self.assertIn("c1", GuardianServiceRuntime("test")._formal_records)
                journal.write_text(journal.read_text() + " ")
                with self.assertRaisesRegex(ValueError, "hash mismatch"):
                    GuardianServiceRuntime("test")


if __name__ == "__main__":
    unittest.main()
