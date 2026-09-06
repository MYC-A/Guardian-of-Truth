import importlib.util
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch


SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "compare_architectures.py"
spec = importlib.util.spec_from_file_location("compare_architectures", SCRIPT)
compare = importlib.util.module_from_spec(spec)
spec.loader.exec_module(compare)


LABELS = {"r0": 0, "r1": 1, "r2": 1}


def review(score, tokens=10, trace=None):
    return {"semantic_score": score, "semantic_usage": {"total_tokens": tokens},
            "reading_trace": trace if trace is not None else [{"round": 1}]}


def legacy(identifier, prediction, fallback=False):
    return {"id": identifier, "label": LABELS[identifier],
            "strict": {"label": prediction, "used_fallback": fallback},
            "overall": {"label": prediction, "used_fallback": fallback},
            "skipped_mechanical": False, "review": review(.9 if prediction else .1)}


def generic(identifier, prediction, *, fallback=False, calls=1, attempts=1,
            elapsed=2.0, ledger=None, score="auto"):
    score = (.9 if prediction else .1) if score == "auto" else score
    return {"id": identifier, "label": LABELS[identifier], "prediction": prediction,
            "decision": {"label": prediction, "used_fallback": fallback},
            "skipped_mechanical": False, "review": review(score),
            "logical_llm_calls": calls, "http_attempts": attempts,
            "elapsed_seconds": elapsed, "ledger": ledger}


class ArchitectureComparisonTests(unittest.TestCase):
    def setUp(self):
        self.folder = tempfile.TemporaryDirectory()
        self.root = Path(self.folder.name)

    def tearDown(self):
        self.folder.cleanup()

    def json(self, name, value):
        path = self.root / name
        path.write_text(json.dumps(value), encoding="utf-8")
        return path

    def jsonl(self, name, rows):
        path = self.root / name
        path.write_text("\n".join(json.dumps(row) for row in rows) + "\n", encoding="utf-8")
        return path

    def artifacts(self):
        a_rows = [legacy("r0", 1), legacy("r1", 0, True), legacy("r2", 1)]
        b_rows = [generic("r0", 0), generic("r1", 0, fallback=True), generic("r2", 1)]
        contradiction = [{"check_id": "c1", "verifier": "deterministic",
                          "relation": "CONTRADICTED"}]
        c_rows = [generic("r0", 0, calls=2), generic("r1", 1, calls=3,
                  ledger=contradiction), generic("r2", 0, fallback=True, score=None)]
        reports = {
            "a": {"budget": {"requests": 9, "seconds": 12.5},
                  "reported_total_tokens": 30},
            "b": {"metrics": {"http_attempts": 3, "elapsed_seconds": 6}},
            "c": {"metrics": {"http_attempts": 3, "elapsed_seconds": 6}},
        }
        paths = {}
        for name, rows in (("a", a_rows), ("b", b_rows), ("c", c_rows)):
            paths[name] = (self.jsonl(name + ".jsonl", rows),
                           self.json(name + "-report.json", reports[name]))
        return paths

    def load(self, paths, selected=None):
        return tuple(compare.load_run(name.upper(), *paths[name], selected)
                     for name in ("a", "b", "c"))

    def test_metrics_cost_validity_deterministic_and_transitions(self):
        paths = self.artifacts()
        a, b, c = self.load(paths)
        result = compare.compare(a, b, c)
        self.assertEqual(a["metrics"], {"n": 3, "tp": 1, "fp": 1, "fn": 1,
                                        "tn": 0, "precision": .5, "recall": .5,
                                        "f1": .5, "fallback": 1})
        self.assertEqual(a["cost"]["http_attempts"], {"value": 9, "source": "report"})
        self.assertEqual(b["cost"]["logical_llm_calls"]["value"], 3)
        self.assertEqual(c["structured_output"], {"valid_rows": 2, "semantic_rows": 3,
                                                   "rate": 2 / 3})
        self.assertEqual(c["deterministic_catches"], {"available": True,
            "contradicted_checks": 1, "caught_rows": 1, "row_ids": ["r1"]})
        self.assertFalse(a["deterministic_catches"]["available"])
        self.assertEqual(result["transitions"]["A_to_B"]["corrected"],
                         [{"id": "r0", "gold": 0, "from": 1, "to": 0}])
        self.assertEqual([row["id"] for row in result["transitions"]["A_to_C"]["corrected"]],
                         ["r0", "r1"])
        self.assertEqual([row["id"] for row in result["transitions"]["A_to_C"]["regressed"]],
                         ["r2"])
        self.assertEqual(result["transitions"]["B_to_C"]["counts"],
                         {"changed": 2, "corrected": 1, "regressed": 1})

    def test_fixed_ids_validate_order_and_do_not_apply_full_report_cost(self):
        paths = self.artifacts()
        a, b, c = self.load(paths, ["r2", "r0"])
        result = compare.compare(a, b, c, fixed_ids=["r2", "r0"])
        self.assertEqual(result["scope"]["ids"], ["r2", "r0"])
        self.assertTrue(result["scope"]["fixed_ids_applied"])
        self.assertIsNone(a["cost"]["http_attempts"]["value"])
        self.assertEqual(a["cost"]["reported_tokens"]["value"], 20)

    def test_reason_audit_is_optional_and_recomputed_only_from_present_rows(self):
        paths = self.artifacts()
        a, b, c = self.load(paths)
        missing = compare.compare(a, b, c)["architectures"]["B"]["reason_audit"]
        self.assertFalse(missing["available"])
        self.assertIsNone(missing["reason_precision"])
        reason = self.json("reason.json", {"summary": {"wrong_reason_tp": 999}, "rows": [
            {"id": "r2", "gold": 1, "prediction": 1,
             "material_valid_reason": True, "cited_material_valid_reason": False}]})
        result = compare.compare(a, b, c, reason_paths={"B": reason})
        audited = result["architectures"]["B"]["reason_audit"]
        self.assertEqual(audited["reason_precision"]["verified_correct"], 1)
        self.assertEqual(audited["cited_reason_precision"]["verified_wrong"], 1)
        self.assertEqual(audited["wrong_reason_tp"], 0)
        self.assertEqual(audited["coverage"], 1)

    def test_rejects_id_gold_and_reason_prediction_mismatches(self):
        paths = self.artifacts()
        a, b, c = self.load(paths)
        c["rows"][0]["gold"] = 1
        with self.assertRaises(ValueError):
            compare.compare(a, b, c)
        a, b, c = self.load(paths)
        reason = self.json("bad-reason.json", {"rows": [
            {"id": "r2", "gold": 1, "prediction": 0, "material_valid_reason": True}]})
        with self.assertRaises(ValueError):
            compare.load_reason_audit(reason, b)

    def test_duplicate_json_and_jsonl_ids_are_rejected(self):
        bad = self.root / "duplicate.json"
        bad.write_text('{"metrics":{},"metrics":{}}', encoding="utf-8")
        with self.assertRaises(ValueError):
            compare._read_json(bad)
        rows = self.jsonl("duplicate.jsonl", [legacy("r0", 0), legacy("r0", 0)])
        report = self.json("report.json", {})
        with self.assertRaises(ValueError):
            compare.load_run("A", rows, report)

    def test_cli_writes_new_json_without_external_calls(self):
        paths = self.artifacts()
        ids = self.json("ids.json", {"ids": ["r0", "r1", "r2"]})
        output = self.root / "comparison.json"
        argv = ["--a-audit", str(paths["a"][0]), "--a-report", str(paths["a"][1]),
                "--b-audit", str(paths["b"][0]), "--b-report", str(paths["b"][1]),
                "--c-audit", str(paths["c"][0]), "--c-report", str(paths["c"][1]),
                "--ids-file", str(ids), "--output", str(output)]
        result = compare.main(argv)
        self.assertEqual(json.loads(output.read_text(encoding="utf-8"))["scope"], result["scope"])
        self.assertEqual(len(result["input_sha256"]), 7)
        with patch("sys.stderr"), self.assertRaises(SystemExit):
            compare.main(argv)


if __name__ == "__main__":
    unittest.main()
