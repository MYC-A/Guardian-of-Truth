"""Regression checks for the hotel FP-reviewer's source binding and scoring."""

import contextlib
import csv
import io
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "experiments" / "searh_23"))
import fp_refute_layer_v4 as layer  # noqa: E402


class FPRefuteV4Tests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        hotel = ROOT / "outputs" / "searh_23" / "hotel_p"
        with (ROOT / "outputs" / "searh_23" / "contrast_hotel_v2" / "cases.csv").open(encoding="utf-8") as source:
            cls.cases = {row["id"]: row for row in csv.DictReader(source)}
        with (hotel / "pgjudge" / "records.jsonl").open(encoding="utf-8") as source:
            cls.records = {row["id"]: row for row in map(json.loads, source)}
        with (hotel / "extract" / "cards.jsonl").open(encoding="utf-8") as source:
            cls.cards = {row["id"]: [card for card in row["cards"] if card.get("quote_grounded")]
                         for row in map(json.loads, source)}

    def verdicts(self, case_id, response):
        case = self.cases[case_id]
        sig = layer.case_signals(case["prompt"], response)
        record = self.records[case_id]
        return [layer.refute_card(self.cards[case_id][index - 1], sig, record.get("reason") or "")[0]
                for index in record["violated_cards"]]

    def test_refund_approval_must_match_target_reservation(self):
        case_id = "hotel2__pair13::ok"
        response = self.cases[case_id]["response"]
        self.assertEqual(self.verdicts(case_id, response), ["REFUTED", "REFUTED"])
        changed = response.replace("R-2301", "R-9999")
        self.assertIsNone(layer.structural_violation(self.cases[case_id]["prompt"], changed))
        self.assertNotEqual(self.verdicts(case_id, changed)[0], "REFUTED")

    def test_refund_approval_must_match_target_amount(self):
        case_id = "hotel2__pair13::ok"
        changed = self.cases[case_id]["response"].replace('"amount": 240', '"amount": 999')
        self.assertNotEqual(self.verdicts(case_id, changed)[0], "REFUTED")

    def test_approval_for_another_reservation_cannot_clear_alarm(self):
        case_id = "hotel2__pair01::ok"
        original_prompt = self.cases[case_id]["prompt"]
        prompt = original_prompt.replace('"approval_status": "granted", "reason": "erroneous charge", "reservation_id": "R-4471"',
                                '"approval_status": "granted", "reason": "erroneous charge", "reservation_id": "R-9999"')
        self.assertNotEqual(prompt, original_prompt)
        sig = layer.case_signals(prompt, self.cases[case_id]["response"])
        card = self.cards[case_id][0]
        self.assertEqual(self.verdicts(case_id, self.cases[case_id]["response"]), ["REFUTED"])
        self.assertNotEqual(layer.refute_card(card, sig)[0], "REFUTED")

    def test_guard_is_decisive_for_one_hotel_positive_and_fn_is_counted(self):
        hotel = ROOT / "outputs" / "searh_23" / "hotel_p"
        suite = ROOT / "outputs" / "searh_23" / "contrast_hotel_v2"
        with tempfile.TemporaryDirectory() as output:
            argv = ["fp_refute_layer_v4.py", "--records", str(hotel / "pgjudge" / "records.jsonl"),
                    "--cards", str(hotel / "extract" / "cards.jsonl"),
                    "--gold-json", str(suite / "expected.json"),
                    "--cases", str(suite / "cases.csv"), "--out-dir", output]
            with patch.object(sys, "argv", argv), patch.object(layer, "structural_violation", return_value=None):
                with contextlib.redirect_stdout(io.StringIO()):
                    layer.main()
            result = json.loads((Path(output) / "refute_layer_v4.json").read_text(encoding="utf-8"))
        self.assertEqual(result["tp_wrongly_refuted"], 1)
        self.assertEqual(result["after"]["TP"], 13)
        self.assertEqual(result["after"]["FN"], 1)
        self.assertEqual(result["after"]["R"], 0.9286)
        self.assertEqual(result["after"]["F1"], 0.8667)
        lost = [row["id"] for row in result["per_case"] if row["gold"] == 1 and row["new_label"] == 0]
        self.assertEqual(lost, ["hotel2__pair13::viol"])


if __name__ == "__main__":
    unittest.main()
