from __future__ import annotations

import csv
import json

import pytest

from experiments.offline_nli.score_nli_records import score, write_new_json


def write_gold(path, rows):
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "label", "criterion"])
        writer.writeheader()
        writer.writerows(rows)


def write_records(path, rows):
    path.write_text("".join(json.dumps(row) + "\n" for row in rows), encoding="utf-8")


def test_scores_only_exact_groundedness_join(tmp_path):
    gold = tmp_path / "gold.csv"
    records = tmp_path / "records.jsonl"
    write_gold(gold, [
        {"id": "ok", "label": 0, "criterion": "groundedness"},
        {"id": "error", "label": 1, "criterion": "groundedness"},
        {"id": "tool", "label": 1, "criterion": "function_call"},
    ])
    write_records(records, [
        {"id": "ok", "status": "ok", "predicted_label": "entailment"},
        {"id": "error", "status": "ok", "predicted_label": "CONTRADICTION"},
    ])
    result = score(records, gold)
    assert (result["tp"], result["fp"], result["fn"], result["tn"]) == (1, 0, 0, 1)
    assert result["f1"] == 1.0
    assert result["count"] == 2
    assert len(result["records_sha256"]) == len(result["gold_sha256"]) == 64


@pytest.mark.parametrize("records", [
    [{"id": "a", "status": "runtime_error", "predicted_label": "contradiction"}],
    [{"id": "a", "status": "ok", "predicted_label": "other"}],
    [
        {"id": "a", "status": "ok", "predicted_label": "entailment"},
        {"id": "a", "status": "ok", "predicted_label": "entailment"},
    ],
])
def test_rejects_unscorable_records(tmp_path, records):
    gold = tmp_path / "gold.csv"
    predictions = tmp_path / "records.jsonl"
    write_gold(gold, [{"id": "a", "label": 0, "criterion": "groundedness"}])
    write_records(predictions, records)
    with pytest.raises(ValueError):
        score(predictions, gold)


def test_rejects_missing_or_extra_ids(tmp_path):
    gold = tmp_path / "gold.csv"
    records = tmp_path / "records.jsonl"
    write_gold(gold, [{"id": "a", "label": 0, "criterion": "groundedness"}])
    write_records(records, [{"id": "b", "status": "ok", "predicted_label": "neutral"}])
    with pytest.raises(ValueError, match="id mismatch"):
        score(records, gold)


def test_refuses_to_overwrite_report(tmp_path):
    output = tmp_path / "metrics.json"
    output.write_text("existing", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        write_new_json(output, {"f1": 1.0})
