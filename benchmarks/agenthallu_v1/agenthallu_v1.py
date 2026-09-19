#!/usr/bin/env python3
"""Freeze AgentHallu v1 by question and build a label-free DEV view."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import re
import subprocess
import sys
import time
import unicodedata
from collections import Counter
from datetime import UTC, datetime
from pathlib import Path, PurePosixPath
from typing import Any, Iterable, Mapping


EXPECTED_SOURCE_COMMIT = "9ffe8bc888feaf15d89833f4b0e3c4697f44acc1"
LICENSE = "CC-BY-4.0"
MANIFEST_VERSION = "agenthallu_v1"
REQUIRED_FIELDS = {"question", "history", "is_hallucination"}
FORBIDDEN_PAYLOAD_FIELDS = {
    "true_answer",
    "explanation",
    "is_hallucination",
    "hallucination_step",
    "hallucination_category",
    "hallucination_subcategory",
    "hallucination_reason",
    "model_id",
    "agent_type",
    "question_source",
    "question_domain",
    "framework",
    "source_path",
}


def canonical_json(value: Any) -> str:
    return json.dumps(
        value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False
    )


def normalized_question(question: Any) -> str:
    text = question if isinstance(question, str) else canonical_json(question)
    return " ".join(unicodedata.normalize("NFC", text).strip().split())


def sha256_bytes(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def question_sha256(question: Any) -> str:
    return sha256_bytes(normalized_question(question).encode("utf-8"))


def split_for_hash(question_hash: str) -> str:
    return "LOCKED" if int(question_hash[:8], 16) % 10 < 3 else "DEV"


def _git(repo: Path, *arguments: str) -> str:
    try:
        return subprocess.run(
            ["git", "-C", str(repo), *arguments],
            check=True,
            capture_output=True,
            text=True,
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError) as exc:
        raise ValueError(f"cannot inspect source Git repository: {exc}") from exc


def _load_object(path: Path) -> dict[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid JSON in {path}: {exc.msg}") from exc
    if not isinstance(value, dict):
        raise ValueError(f"sample must be a JSON object: {path}")
    return value


def validate_manifest_entries(entries: Iterable[Mapping[str, Any]]) -> None:
    assigned: dict[str, str] = {}
    paths: set[str] = set()
    for entry in entries:
        path = entry.get("source_path")
        question_hash = entry.get("question_hash")
        split = entry.get("split")
        if not isinstance(path, str) or not isinstance(question_hash, str) or split not in {"DEV", "LOCKED"}:
            raise ValueError("manifest entry has invalid source_path/question_hash/split")
        if path in paths:
            raise ValueError(f"duplicate source_path in manifest: {path}")
        paths.add(path)
        previous = assigned.setdefault(question_hash, split)
        if previous != split:
            raise ValueError(f"question hash crosses splits: {question_hash}")
        expected = split_for_hash(question_hash)
        if split != expected:
            raise ValueError(f"split does not match locked rule for question hash: {question_hash}")


def freeze(source_repo: Path, output_manifest: Path) -> dict[str, Any]:
    if output_manifest.exists():
        raise ValueError(f"refusing to overwrite existing output: {output_manifest}")
    source_repo = source_repo.resolve(strict=True)
    commit = _git(source_repo, "rev-parse", "HEAD")
    if commit != EXPECTED_SOURCE_COMMIT:
        raise ValueError(f"unexpected AgentHallu commit {commit}; expected {EXPECTED_SOURCE_COMMIT}")
    tree = _git(source_repo, "rev-parse", "HEAD^{tree}")
    data_root = source_repo / "AgentHallu"
    files = sorted(data_root.glob("*/*.json"))
    if not files:
        raise ValueError(f"no AgentHallu JSON samples under {data_root}")

    entries: list[dict[str, str]] = []
    for path in files:
        sample = _load_object(path)
        missing = REQUIRED_FIELDS - set(sample)
        if missing:
            raise ValueError(f"{path} misses required fields: {', '.join(sorted(missing))}")
        relative = path.relative_to(source_repo).as_posix()
        qhash = question_sha256(sample["question"])
        entries.append(
            {
                "source_path": relative,
                "file_sha256": file_sha256(path),
                "question_hash": qhash,
                "split": split_for_hash(qhash),
            }
        )
    validate_manifest_entries(entries)
    split_counts = dict(sorted(Counter(entry["split"] for entry in entries).items()))
    manifest = {
        "manifest_version": MANIFEST_VERSION,
        "created_at_utc": datetime.now(UTC).isoformat(),
        "source": {
            "name": "AgentHallu",
            "repository_commit": commit,
            "repository_tree": tree,
            "license": LICENSE,
            "sample_count": len(entries),
        },
        "split_rule": "LOCKED iff int(question_sha256[:8], 16) % 10 < 3; otherwise DEV",
        "normalization": "str as text, other JSON canonical; then NFC, strip, collapse whitespace",
        "split_counts": split_counts,
        "entries": entries,
    }
    output_manifest.parent.mkdir(parents=True, exist_ok=True)
    try:
        with output_manifest.open("x", encoding="utf-8", newline="\n") as destination:
            json.dump(manifest, destination, ensure_ascii=False, indent=2, sort_keys=True)
            destination.write("\n")
    except FileExistsError as exc:
        raise ValueError(f"refusing to overwrite existing output: {output_manifest}") from exc
    return manifest


def _source_step_key(value: Any) -> int | None:
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value
    if isinstance(value, str) and re.fullmatch(r"[+-]?\d+", value.strip()):
        return int(value.strip())
    return None


def resolve_event_ordinal(source_step: Any, history: list[Any]) -> tuple[int | None, str]:
    target = _source_step_key(source_step)
    if target is None:
        return None, "UNMAPPABLE"
    matches = [
        ordinal
        for ordinal, event in enumerate(history)
        if isinstance(event, dict) and _source_step_key(event.get("step")) == target
    ]
    if len(matches) == 1:
        return matches[0], "RESOLVED"
    if len(matches) > 1:
        return None, "AMBIGUOUS"
    return None, "UNMAPPABLE"


def _binary_label(value: Any, path: str) -> int:
    if value == "true" or value is True:
        return 1
    if value == "false" or value is False:
        return 0
    raise ValueError(f"invalid is_hallucination value in {path}")


def _assert_label_free(prompt: str, response: str) -> None:
    prompt_value = json.loads(prompt)
    response_value = json.loads(response)
    if set(prompt_value) != {"format", "task"} or prompt_value["format"] != "agent_trajectory_v1":
        raise ValueError("prompt payload violates label-free schema")
    if set(response_value) != {"events"} or not isinstance(response_value["events"], list):
        raise ValueError("response payload violates label-free schema")
    if FORBIDDEN_PAYLOAD_FIELDS & set(prompt_value):
        raise ValueError("prompt payload leaks source metadata or gold")
    if FORBIDDEN_PAYLOAD_FIELDS & set(response_value):
        raise ValueError("response payload leaks source metadata or gold")


def adapt_dev(source_repo: Path, manifest_path: Path, output_dir: Path) -> dict[str, Any]:
    if output_dir.exists():
        raise ValueError(f"refusing to overwrite existing output: {output_dir}")
    source_repo = source_repo.resolve(strict=True)
    manifest_path = manifest_path.resolve(strict=True)
    manifest = _load_object(manifest_path)
    if manifest.get("manifest_version") != MANIFEST_VERSION:
        raise ValueError("unsupported manifest version")
    entries = manifest.get("entries")
    if not isinstance(entries, list):
        raise ValueError("manifest entries must be a list")
    validate_manifest_entries(entries)
    source = manifest.get("source")
    if not isinstance(source, dict) or source.get("repository_commit") != EXPECTED_SOURCE_COMMIT:
        raise ValueError("manifest source commit is missing or unexpected")
    if _git(source_repo, "rev-parse", "HEAD") != EXPECTED_SOURCE_COMMIT:
        raise ValueError("source repository is not at the frozen commit")

    # Filter before opening any sample. Locked source files are never read here.
    dev_entries = [entry for entry in entries if entry["split"] == "DEV"]
    rows: list[dict[str, str]] = []
    binary_gold: list[dict[str, Any]] = []
    localization_gold: list[dict[str, Any]] = []
    mapping_counts: Counter[str] = Counter()
    framework_counts: Counter[str] = Counter()
    positive_count = 0
    for entry in dev_entries:
        relative = PurePosixPath(entry["source_path"])
        if relative.is_absolute() or ".." in relative.parts or len(relative.parts) != 3 or relative.parts[0] != "AgentHallu":
            raise ValueError(f"unsafe source path in manifest: {entry['source_path']}")
        path = source_repo.joinpath(*relative.parts)
        if file_sha256(path) != entry["file_sha256"]:
            raise ValueError(f"source file hash mismatch: {entry['source_path']}")
        sample = _load_object(path)
        if question_sha256(sample.get("question")) != entry["question_hash"]:
            raise ValueError(f"question hash mismatch: {entry['source_path']}")
        history = sample.get("history")
        if not isinstance(history, list):
            raise ValueError(f"history must be a list: {entry['source_path']}")
        framework, stem = relative.parts[1], Path(relative.parts[2]).stem
        case_id = f"agenthallu/v1/{framework}/{stem}"
        prompt = canonical_json({"task": sample["question"], "format": "agent_trajectory_v1"})
        response = canonical_json({"events": history})
        _assert_label_free(prompt, response)
        rows.append({"id": case_id, "prompt": prompt, "response": response})
        label = _binary_label(sample.get("is_hallucination"), entry["source_path"])
        positive_count += label
        binary_gold.append({"id": case_id, "label": label})
        if label:
            source_step = sample.get("hallucination_step")
            ordinal, mapping_status = resolve_event_ordinal(source_step, history)
        else:
            source_step, ordinal, mapping_status = None, None, "NOT_APPLICABLE"
        mapping_counts[mapping_status] += 1
        localization_gold.append(
            {
                "id": case_id,
                "label": label,
                "source_step": source_step,
                "event_ordinal": ordinal,
                "mapping_status": mapping_status,
            }
        )
        framework_counts[framework] += 1

    if len({row["id"] for row in rows}) != len(rows):
        raise ValueError("duplicate adapted id")
    started = time.perf_counter()
    output_dir.mkdir(parents=True, exist_ok=False)
    with (output_dir / "input.csv").open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "prompt", "response"])
        writer.writeheader()
        writer.writerows(rows)
    with (output_dir / "gold_binary.csv").open("x", encoding="utf-8", newline="") as destination:
        writer = csv.DictWriter(destination, fieldnames=["id", "label"])
        writer.writeheader()
        writer.writerows(binary_gold)
    with (output_dir / "localization_gold.jsonl").open("x", encoding="utf-8", newline="\n") as destination:
        for record in localization_gold:
            destination.write(canonical_json(record) + "\n")
    report = {
        "adapter_version": MANIFEST_VERSION,
        "manifest_sha256": file_sha256(manifest_path),
        "source_commit": EXPECTED_SOURCE_COMMIT,
        "split": "DEV",
        "counts": {
            "cases": len(rows),
            "positive": positive_count,
            "negative": len(rows) - positive_count,
            "frameworks": dict(sorted(framework_counts.items())),
            "localization": dict(sorted(mapping_counts.items())),
        },
        "schema_validation": {
            "label_free_input_columns": ["id", "prompt", "response"],
            "payload_keys_validated": True,
            "event_order_and_json_types_preserved": True,
            "locked_files_opened": 0,
        },
        "elapsed_seconds_write_only": round(time.perf_counter() - started, 6),
    }
    (output_dir / "adapt_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    return report


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    subparsers = parser.add_subparsers(dest="command", required=True)
    freeze_parser = subparsers.add_parser("freeze")
    freeze_parser.add_argument("--source-repo", required=True)
    freeze_parser.add_argument("--output-manifest", required=True)
    adapt_parser = subparsers.add_parser("adapt-dev")
    adapt_parser.add_argument("--source-repo", required=True)
    adapt_parser.add_argument("--manifest", required=True)
    adapt_parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    if args.command == "freeze":
        result = freeze(Path(args.source_repo), Path(args.output_manifest))
        print(canonical_json({"sample_count": result["source"]["sample_count"], "split_counts": result["split_counts"]}))
    else:
        result = adapt_dev(Path(args.source_repo), Path(args.manifest), Path(args.output_dir))
        print(canonical_json(result["counts"]))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"agenthallu_v1: {exc}", file=sys.stderr)
        raise SystemExit(2)
