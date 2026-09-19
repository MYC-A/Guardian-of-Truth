from __future__ import annotations

import csv
import json
import shutil
from pathlib import Path

import pytest

from benchmarks.agenthallu_v1 import agenthallu_v1 as adapter


FIXTURE_SOURCE = Path(__file__).parent / "fixtures" / "source"


def source_repo(tmp_path: Path) -> Path:
    destination = tmp_path / "source"
    shutil.copytree(FIXTURE_SOURCE, destination)
    return destination


@pytest.fixture
def fake_git(monkeypatch: pytest.MonkeyPatch) -> None:
    def result(_repo: Path, *arguments: str) -> str:
        return adapter.EXPECTED_SOURCE_COMMIT if arguments[-1] == "HEAD" else "fixture-tree"

    monkeypatch.setattr(adapter, "_git", result)


def test_question_normalization_for_string_list_and_nfc() -> None:
    assert adapter.normalized_question("  alpha\n beta\t") == "alpha beta"
    assert adapter.normalized_question([{"b": 2, "a": "x y"}, None]) == '[{"a":"x y","b":2},null]'
    assert adapter.normalized_question("Cafe\u0301") == adapter.normalized_question("Café")


def test_freeze_groups_same_question_and_contains_no_gold(tmp_path: Path, fake_git: None) -> None:
    source = source_repo(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    manifest = adapter.freeze(source, manifest_path)

    assert manifest["source"]["sample_count"] == 3
    assert manifest["split_counts"] == {"DEV": 2, "LOCKED": 1}
    first, second = manifest["entries"][:2]
    assert first["question_hash"] == second["question_hash"]
    assert first["split"] == second["split"] == "DEV"
    serialized = manifest_path.read_text(encoding="utf-8")
    for forbidden in (
        "true_answer",
        "is_hallucination",
        "hallucination_reason",
        "secret-reference",
        "Test task",
    ):
        assert forbidden not in serialized


def test_adapt_dev_is_label_free_preserves_events_and_never_opens_locked(
    tmp_path: Path, fake_git: None
) -> None:
    source = source_repo(tmp_path)
    # Exercise fields beyond the default Python CSV reader limit.
    large_path = source / "AgentHallu" / "TestFramework" / "002.json"
    large = json.loads(large_path.read_text(encoding="utf-8"))
    large["history"][0]["content"] = "x" * 140_000
    large_path.write_text(json.dumps(large, ensure_ascii=False), encoding="utf-8")
    manifest_path = tmp_path / "manifest.json"
    adapter.freeze(source, manifest_path)

    # If adapt-dev tries to hash or load LOCKED content, this missing file fails the test.
    (source / "AgentHallu" / "TestFramework" / "003.json").unlink()
    output = tmp_path / "adapted"
    report = adapter.adapt_dev(source, manifest_path, output)
    assert report["counts"]["cases"] == 2
    assert report["counts"]["positive"] == 1
    assert report["schema_validation"]["locked_files_opened"] == 0

    csv.field_size_limit(1024 * 1024)
    with (output / "input.csv").open(encoding="utf-8", newline="") as source_csv:
        rows = list(csv.DictReader(source_csv))
    assert [row["id"] for row in rows] == [
        "agenthallu/v1/TestFramework/001",
        "agenthallu/v1/TestFramework/002",
    ]
    first_prompt, first_response = json.loads(rows[0]["prompt"]), json.loads(rows[0]["response"])
    assert set(first_prompt) == {"format", "task"}
    assert set(first_response) == {"events"}
    assert first_response["events"][1]["tool_responses"] == [None, False, 3.5]
    assert len(json.loads(rows[1]["response"])["events"][0]["content"]) == 140_000
    all_input = (output / "input.csv").read_text(encoding="utf-8")
    for leaked in ("secret-reference", "secret-explanation", "secret-category", "fixture-model"):
        assert leaked not in all_input

    localization = [
        json.loads(line)
        for line in (output / "localization_gold.jsonl").read_text(encoding="utf-8").splitlines()
    ]
    assert localization[0] == {
        "event_ordinal": 1,
        "id": "agenthallu/v1/TestFramework/001",
        "label": 1,
        "mapping_status": "RESOLVED",
        "source_step": "2",
    }
    assert localization[1]["source_step"] is None
    assert localization[1]["event_ordinal"] is None
    assert localization[1]["mapping_status"] == "NOT_APPLICABLE"


def test_duplicate_and_missing_source_steps_are_not_guessed() -> None:
    duplicate = [{"step": 1}, {"step": 2}, {"step": 2}]
    assert adapter.resolve_event_ordinal("2", duplicate) == (None, "AMBIGUOUS")
    assert adapter.resolve_event_ordinal("7", duplicate) == (None, "UNMAPPABLE")
    assert adapter.resolve_event_ordinal("1", duplicate) == (0, "RESOLVED")


def test_freeze_and_adapter_outputs_are_immutable(tmp_path: Path, fake_git: None) -> None:
    source = source_repo(tmp_path)
    manifest_path = tmp_path / "manifest.json"
    adapter.freeze(source, manifest_path)
    original = manifest_path.read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        adapter.freeze(source, manifest_path)
    assert manifest_path.read_bytes() == original

    output = tmp_path / "adapted"
    adapter.adapt_dev(source, manifest_path, output)
    sentinel = (output / "input.csv").read_bytes()
    with pytest.raises(ValueError, match="refusing to overwrite"):
        adapter.adapt_dev(source, manifest_path, output)
    assert (output / "input.csv").read_bytes() == sentinel


def test_manifest_rejects_same_question_hash_across_splits() -> None:
    qhash = adapter.question_sha256("Test task")
    with pytest.raises(ValueError, match="question hash crosses splits"):
        adapter.validate_manifest_entries(
            [
                {"source_path": "AgentHallu/F/1.json", "question_hash": qhash, "split": "DEV"},
                {"source_path": "AgentHallu/F/2.json", "question_hash": qhash, "split": "LOCKED"},
            ]
        )
