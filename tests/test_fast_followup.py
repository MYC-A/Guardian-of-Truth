"""Failure-mode checks for the frozen, label-free follow-up runner."""
from __future__ import annotations

import csv
import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "experiments/searh_23"))
import fast_followup_run as followup  # noqa: E402


class FastFollowupTest(unittest.TestCase):
    def test_suite_is_balanced_and_inference_file_has_no_labels(self):
        suite = ROOT / "experiments/searh_23/service_desk_v1"
        cases = followup.read_cases(suite / "cases.csv")
        gold = followup.read_gold(suite / "expected.json")
        self.assertEqual(len(cases), 32)
        self.assertEqual(set(gold), {case["id"] for case in cases})
        counts = {(label, call): 0 for label in (0, 1) for call in (False, True)}
        for case in cases:
            has_call = any(e.role == "assistant" and e.kind == "call"
                           for e in followup.parse_events(case["response"], "response"))
            counts[(gold[case["id"]], has_call)] += 1
        self.assertEqual(set(counts.values()), {8})
        refund = next(case for case in cases if case["id"] == "desk_v1__call_ok_refund")
        self.assertIn("подтверждаю возврат $40", refund["prompt"])

    def test_prepare_rejects_gold_and_freeze_detects_changed_input(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = root / "cases.csv"
            with cases.open("w", encoding="utf-8", newline="") as handle:
                writer = csv.DictWriter(handle, fieldnames=["id", "prompt", "response", "gold"])
                writer.writeheader()
                writer.writerow({"id": "one", "prompt": "p", "response": "r", "gold": 1})
            with self.assertRaisesRegex(ValueError, "exactly id,prompt,response"):
                followup.prepare(cases, root / "run")
            cases.write_text("id,prompt,response\none,p,r\n", encoding="utf-8")
            followup.prepare(cases, root / "run")
            cases.write_text("id,prompt,response\none,p,changed\n", encoding="utf-8")
            with self.assertRaisesRegex(ValueError, "frozen cases changed"):
                followup.frozen(root / "run")

    def test_incomplete_run_cannot_seal_or_score(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = root / "cases.csv"
            cases.write_text("id,prompt,response\none,p,r\n", encoding="utf-8")
            gold = root / "gold.json"
            gold.write_text('{"one":1}', encoding="utf-8")
            run_dir = root / "run"
            followup.prepare(cases, run_dir)
            with self.assertRaisesRegex(RuntimeError, "prediction stages incomplete"):
                followup.score_stage(run_dir, gold)
            self.assertFalse((run_dir / "prediction_seal.json").exists())

    def test_source_safe_guard_retains_explicit_schema_violation(self):
        self.assertIsNone(followup.source_safe_guard(
            "undeclared tool called: x (not in [AVAILABLE TOOLS])"))
        self.assertEqual(followup.source_safe_guard(
            "execute_replacement missing required argument(s): case_id"),
            "execute_replacement missing required argument(s): case_id")

    def test_score_counts_tp_lost_by_tq_after_fp_clearance(self):
        with tempfile.TemporaryDirectory() as temp:
            root = Path(temp)
            cases = root / "cases.csv"
            cases.write_text("id,prompt,response\none,p,r\ntwo,p,r\n", encoding="utf-8")
            gold = root / "gold.json"
            gold.write_text('{"one":1,"two":0}', encoding="utf-8")
            run_dir = root / "run"
            followup.prepare(cases, run_dir)

            def jsonl(relative, rows):
                path = run_dir / relative
                path.parent.mkdir(parents=True, exist_ok=True)
                path.write_text("".join(json.dumps(row) + "\n" for row in rows),
                                encoding="utf-8")

            jsonl("local.jsonl", [
                {"id": cid, "status": "OK", "structural": {"label": 0},
                 "input_sha256": hashlib.sha256("p\0r".encode()).hexdigest(),
                 "c1": {str(budget): 1 for budget in followup.CONTEXT_BUDGETS},
                 "function_call": {"label": None}} for cid in ("one", "two")])
            jsonl("pgjudge/extract/cards.jsonl", [
                {"id": cid, "status": "OK", "cards": []} for cid in ("one", "two")])
            jsonl("pgjudge/pgjudge/records.jsonl", [
                {"id": cid, "status": "OK", "label": 1} for cid in ("one", "two")])
            (run_dir / "refute.json").write_text(json.dumps({"per_case": [
                {"id": "one", "pgjudge": 1, "new_label": 1,
                 "v31_label": 1, "v4_label": 1, "v4_safe_label": 1},
                {"id": "two", "pgjudge": 1, "new_label": 0,
                 "v31_label": 0, "v4_label": 0, "v4_safe_label": 0}]}), encoding="utf-8")
            (run_dir / "tq_questions_fast_followup.json").write_text(
                json.dumps({"per_case": [{"id": "one", "new_label": 0}]}), encoding="utf-8")
            jsonl("e2e_R1.jsonl", [
                {"id": cid, "status": "OK", "label": label,
                 "source_commit": "300dc2edd20e631928b9997a8f581ab8659a75b2",
                 "cases_sha256": json.loads((run_dir / "manifest.json").read_text())[
                     "cases_sha256"],
                 "input_sha256": hashlib.sha256("p\0r".encode()).hexdigest()}
                for cid, label in (("one", 1), ("two", 0))])
            jsonl("feasibility.jsonl", [
                {"id": cid, "status": "OK", "verdict": verdict,
                 "input_sha256": hashlib.sha256("p\0r".encode()).hexdigest()}
                for cid, verdict in (("one", "CANDIDATE"), ("two", "UNKNOWN"))])
            followup.score_stage(run_dir, gold)
            result = json.loads((run_dir / "score.json").read_text(encoding="utf-8"))
            self.assertEqual(result["scores"]["v4_safe"]["TP"], 1)
            self.assertEqual(result["scores"]["tq"]["FN"], 1)
            self.assertEqual(result["comparisons"]["v4_safe -> tq"]["tp_lost"], ["one"])
            self.assertEqual(result["comparisons"]["c1_12000 -> c1_12000_and_v4_safe"]
                             ["fp_removed"], ["two"])
            self.assertEqual(result["comparisons"]["c1_12000 -> c1_12000_and_tq"]
                             ["tp_lost"], ["one"])
            self.assertEqual(result["scores"]["e2e_r1"]["FP"], 0)
            self.assertEqual(result["scores"]["feasibility_proposal"]["TP"], 1)
            self.assertEqual(result["comparisons"]["c1_12000 -> e2e_r1"]
                             ["fp_removed"], ["two"])


if __name__ == "__main__":
    unittest.main()
