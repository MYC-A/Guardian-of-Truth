from __future__ import annotations

import csv
import hashlib
import json
from argparse import Namespace
from pathlib import Path

import pytest

from experiments.architectures_v2.run_source_grounding import run


def write_csv(path: Path, rows: list[dict[str, str]]) -> None:
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "prompt", "response"])
        writer.writeheader()
        writer.writerows(rows)


def suspicion(quote: str, start: int, end: int, *, score: float = 0.9) -> dict:
    return {
        "reason_type": "policy_order",
        "source_kind": "SYSTEM_POLICY",
        "source": {"document": "prompt", "quote": quote, "start": start, "end": end},
        "target": None,
        "proposed_violation": "required action omitted",
        "score": score,
        "reason_attributes": {"execution": "unknown"},
    }


def invoke(tmp_path: Path, rows: list[dict[str, str]], outputs: list[dict]) -> tuple[Path, Path, Path]:
    input_path = tmp_path / "input.csv"
    model_path = tmp_path / "model.jsonl"
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "run"
    write_csv(input_path, rows)
    model_path.write_text(
        "".join(json.dumps(item, ensure_ascii=False) + "\n" for item in outputs), encoding="utf-8"
    )
    config_path.write_text('{"positive_threshold": 0.8, "variant": "a0_suspicions"}\n', encoding="utf-8")
    run(
        Namespace(
            input=str(input_path),
            model_output=str(model_path),
            config=str(config_path),
            output_dir=str(output_dir),
        )
    )
    return output_dir, input_path, model_path


def test_run_emits_every_case_manifest_hashes_and_separate_statuses(tmp_path: Path) -> None:
    rows = [
        {"id": "anchored", "prompt": "Must verify first.", "response": "Done"},
        {"id": "unanchored", "prompt": "No matching text", "response": "Done"},
        {"id": "missing", "prompt": "Anything", "response": "Done"},
    ]
    outputs = [
        {"id": "anchored", "suspicion": suspicion("verify", 5, 11)},
        {"id": "unanchored", "suspicion": suspicion("verify", 0, 6)},
    ]
    output_dir, input_path, model_path = invoke(tmp_path, rows, outputs)

    records = [json.loads(line) for line in (output_dir / "records.jsonl").read_text(encoding="utf-8").splitlines()]
    assert [item["id"] for item in records] == ["anchored", "unanchored", "missing"]
    assert [item["probabilistic_label"] for item in records] == [1, 0, 0]
    assert all(item["formal_status"] == "UNRESOLVED" for item in records)
    assert records[0]["grounding"]["grounding_status"] == "ANCHORED"
    assert records[1]["grounding"]["grounding_status"] == "UNANCHORED"
    assert records[2]["model_output_status"] == "MISSING"

    manifest = json.loads((output_dir / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["counts"] == {"ANCHORED": 1, "UNANCHORED": 1, "missing": 1, "positive": 1}
    assert manifest["case_count"] == 3
    assert manifest["model_output_count"] == 2
    assert manifest["input_sha256"] == hashlib.sha256(input_path.read_bytes()).hexdigest()
    assert manifest["model_output_sha256"] == hashlib.sha256(model_path.read_bytes()).hexdigest()
    assert len(manifest["config_sha256"]) == 64


def test_large_csv_field_is_accepted(tmp_path: Path) -> None:
    large_prompt = "x" * 140_000 + " anchor"
    output_dir, _, _ = invoke(
        tmp_path,
        [{"id": "large", "prompt": large_prompt, "response": "ok"}],
        [{"id": "large", "suspicion": suspicion("anchor", 140_001, 140_007)}],
    )
    record = json.loads((output_dir / "records.jsonl").read_text(encoding="utf-8"))
    assert record["grounding"]["grounding_status"] == "ANCHORED"


@pytest.mark.parametrize(
    ("outputs", "message"),
    [
        (
            [
                {"id": "known", "suspicion": suspicion("text", 0, 4)},
                {"id": "known", "suspicion": suspicion("text", 0, 4)},
            ],
            "duplicate model-output id",
        ),
        ([{"id": "other", "suspicion": suspicion("text", 0, 4)}], "unknown model-output id"),
    ],
)
def test_bad_model_ids_fail_before_output_creation(tmp_path: Path, outputs: list[dict], message: str) -> None:
    input_path = tmp_path / "input.csv"
    model_path = tmp_path / "model.jsonl"
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "run"
    write_csv(input_path, [{"id": "known", "prompt": "text", "response": "ok"}])
    model_path.write_text("".join(json.dumps(item) + "\n" for item in outputs), encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match=message):
        run(Namespace(input=str(input_path), model_output=str(model_path), config=str(config_path), output_dir=str(output_dir)))
    assert not output_dir.exists()


def test_existing_output_path_is_rejected_without_changes(tmp_path: Path) -> None:
    output_dir = tmp_path / "run"
    output_dir.mkdir()
    sentinel = output_dir / "keep.txt"
    sentinel.write_text("keep", encoding="utf-8")
    input_path = tmp_path / "input.csv"
    model_path = tmp_path / "model.jsonl"
    config_path = tmp_path / "config.json"
    write_csv(input_path, [{"id": "known", "prompt": "text", "response": "ok"}])
    model_path.write_text("", encoding="utf-8")
    config_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match="refusing to overwrite"):
        run(Namespace(input=str(input_path), model_output=str(model_path), config=str(config_path), output_dir=str(output_dir)))
    assert sentinel.read_text(encoding="utf-8") == "keep"


def test_invalid_score_fails_before_output_creation(tmp_path: Path) -> None:
    input_path = tmp_path / "input.csv"
    model_path = tmp_path / "model.jsonl"
    config_path = tmp_path / "config.json"
    output_dir = tmp_path / "run"
    write_csv(input_path, [{"id": "known", "prompt": "text", "response": "ok"}])
    model_path.write_text(
        json.dumps({"id": "known", "suspicion": suspicion("text", 0, 4, score=1.1)}) + "\n",
        encoding="utf-8",
    )
    config_path.write_text("{}", encoding="utf-8")
    with pytest.raises(ValueError, match=r"score must be within \[0, 1\]"):
        run(Namespace(input=str(input_path), model_output=str(model_path), config=str(config_path), output_dir=str(output_dir)))
    assert not output_dir.exists()
