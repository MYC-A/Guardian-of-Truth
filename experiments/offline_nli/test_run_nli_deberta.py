from __future__ import annotations

import csv

from experiments.offline_nli.run_nli_deberta import read_cases


def test_read_cases_accepts_competition_prompt_larger_than_csv_default(tmp_path):
    source = tmp_path / "large.csv"
    prompt = "context " + "x" * 140_000
    with source.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "prompt", "response"])
        writer.writeheader()
        writer.writerow({"id": "large", "prompt": prompt, "response": "claim"})
    assert read_cases(source) == [{"id": "large", "prompt": prompt, "response": "claim"}]
