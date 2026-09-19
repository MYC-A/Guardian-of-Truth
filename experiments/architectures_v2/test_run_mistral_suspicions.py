import csv
import json
from argparse import Namespace
from pathlib import Path

import pytest

from guardian_truth.llm_client import ClientConfig, Completion

from experiments.architectures_v2.run_mistral_suspicions import (
    A0_SCHEMA,
    A1_SCHEMA,
    EXPECTED_MODEL,
    parse_a1,
    read_cases,
    run,
)


class FakeClient:
    def __init__(self, completions, *, model=EXPECTED_MODEL):
        self.config = ClientConfig(base_url="https://api.mistral.ai/v1", model=model,
                                   api_key_env="MISTRAL_API_KEY")
        self.completions = list(completions)
        self.calls = []

    def complete(self, messages, *, schema=None):
        self.calls.append({"messages": messages, "schema": schema})
        item = self.completions.pop(0)
        if isinstance(item, Exception):
            raise item
        return item


def completion(payload, *, model=EXPECTED_MODEL, usage=None):
    return Completion(json.dumps(payload), usage or {"total_tokens": 11}, model)


def write_csv(path: Path, rows):
    with path.open("w", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "prompt", "response", "gold"])
        writer.writeheader()
        for row in rows:
            writer.writerow({**row, "gold": "must-not-be-read"})


def args(input_path: Path, output_dir: Path, variant="A1", **overrides):
    values = {
        "input": str(input_path), "output_dir": str(output_dir), "variant": variant,
        "max_rows": None, "max_input_chars": 1_000_000, "max_output_tokens": 2048,
        "timeout_seconds": 120.0, "max_retries": 2, "positive_threshold": 0.5,
    }
    values.update(overrides)
    return Namespace(**values)


def records(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()]


def suspicion(*, quote, start, end, score=0.9):
    return {
        "reason_type": "contradiction", "source_kind": "tool_result",
        "source": {"document": "prompt", "quote": quote, "start": start, "end": end},
        "target": None, "entity": None, "time_scope": None, "field": "status",
        "reason_attributes": {"evidence": "explicit"},
        "proposed_violation": "The response contradicts tool evidence.", "score": score,
    }


def test_a1_schema_and_grounding_gate_exact_and_unanchored(tmp_path):
    input_path = tmp_path / "input.csv"
    write_csv(input_path, [
        {"id": "exact", "prompt": "status=failed", "response": "It succeeded."},
        {"id": "bad", "prompt": "status=failed", "response": "It succeeded."},
    ])
    client = FakeClient([
        completion({"suspicions": [suspicion(quote="status=failed", start=0, end=13)]}),
        completion({"suspicions": [suspicion(quote="status=failed", start=1, end=14)]}),
    ])

    assert run(args(input_path, tmp_path / "out"), client=client,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0

    output = records(tmp_path / "out" / "records.jsonl")
    assert [item["probabilistic_label"] for item in output] == [1, 0]
    assert output[0]["grounded_suspicions"][0]["grounding_status"] == "ANCHORED"
    assert output[1]["grounded_suspicions"][0]["grounding_status"] == "UNANCHORED"
    assert output[1]["grounded_suspicions"][0]["formal_status"] == "UNRESOLVED"
    assert client.calls[0]["schema"] == A1_SCHEMA
    assert "must-not-be-read" not in json.dumps(client.calls)


def test_a0_flat_schema_and_max_rows_resume(tmp_path):
    input_path = tmp_path / "input.csv"
    write_csv(input_path, [
        {"id": "one", "prompt": "p", "response": "r"},
        {"id": "two", "prompt": "p", "response": "r"},
    ])
    first = FakeClient([completion({"label": 1, "reason_type": "claim", "reason": "wrong", "score": 0.8})])
    assert run(args(input_path, tmp_path / "out", "A0", max_rows=1), client=first,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0
    assert first.calls[0]["schema"] == A0_SCHEMA

    second = FakeClient([completion({"label": 0, "reason_type": "none", "reason": "supported", "score": 0.1})])
    assert run(args(input_path, tmp_path / "out", "A0"), client=second,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0
    assert [(item["id"], item["probabilistic_label"]) for item in records(
        tmp_path / "out" / "records.jsonl"
    )] == [("one", 1), ("two", 0)]
    manifest = json.loads((tmp_path / "out" / "run_manifest.json").read_text(encoding="utf-8"))
    assert manifest["finished"] is True
    assert manifest["request_count"] == 2
    assert manifest["token_counts"]["total_tokens"] == 22


def test_malformed_response_is_append_only_and_retried(tmp_path):
    input_path = tmp_path / "input.csv"
    write_csv(input_path, [{"id": "x", "prompt": "abc", "response": "def"}])
    output_dir = tmp_path / "out"
    malformed = FakeClient([Completion("not-json", {}, EXPECTED_MODEL)])
    assert run(args(input_path, output_dir), client=malformed,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0
    assert records(output_dir / "records.jsonl")[0]["status"] == "MALFORMED_RESPONSE"

    valid = FakeClient([completion({"suspicions": []})])
    assert run(args(input_path, output_dir), client=valid,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0
    assert [item["status"] for item in records(output_dir / "records.jsonl")] == [
        "MALFORMED_RESPONSE", "OK",
    ]

    skipped = FakeClient([])
    assert run(args(input_path, output_dir), client=skipped,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 0
    assert skipped.calls == []


def test_model_mismatch_is_rejected_and_config_conflict_refuses_resume(tmp_path):
    input_path = tmp_path / "input.csv"
    write_csv(input_path, [{"id": "x", "prompt": "abc", "response": "def"}])
    output_dir = tmp_path / "out"
    wrong_response = FakeClient([completion({"suspicions": []}, model="another-model")])
    assert run(args(input_path, output_dir), client=wrong_response,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL}) == 2
    assert records(output_dir / "records.jsonl")[0]["status"] == "MODEL_MISMATCH"

    with pytest.raises(ValueError, match="conflicting run config"):
        run(args(input_path, output_dir, positive_threshold=0.9), client=FakeClient([]),
            environ={"MISTRAL_MODEL": EXPECTED_MODEL})
    with pytest.raises(ValueError, match="MISTRAL_MODEL"):
        run(args(input_path, tmp_path / "other"), client=FakeClient([]),
            environ={"MISTRAL_MODEL": "wrong"})


def test_secret_is_absent_from_artifacts_and_oversize_is_explicit(tmp_path):
    secret = "mistral-secret-that-must-not-leak"
    input_path = tmp_path / "input.csv"
    write_csv(input_path, [{"id": "x", "prompt": "123456", "response": "789"}])
    output_dir = tmp_path / "out"
    client = FakeClient([])
    assert run(args(input_path, output_dir, max_input_chars=8), client=client,
               environ={"MISTRAL_MODEL": EXPECTED_MODEL, "MISTRAL_API_KEY": secret}) == 0
    assert client.calls == []
    combined = (output_dir / "records.jsonl").read_text(encoding="utf-8") + (
        output_dir / "run_manifest.json").read_text(encoding="utf-8")
    assert secret not in combined
    record = records(output_dir / "records.jsonl")[0]
    assert record["status"] == "INPUT_TOO_LARGE"
    assert record["formal_status"] == "UNRESOLVED"
    assert record["probabilistic_label"] == 0


def test_large_csv_field_and_strict_atomic_shape(tmp_path):
    input_path = tmp_path / "input.csv"
    prompt = "x" * 140_000
    write_csv(input_path, [{"id": "large", "prompt": prompt, "response": "ok"}])
    assert read_cases(input_path)[0]["prompt"] == prompt

    invalid = suspicion(quote="x", start=0, end=1)
    invalid["unexpected"] = "no"
    with pytest.raises(ValueError, match="keys differ"):
        parse_a1(json.dumps({"suspicions": [invalid]}))
