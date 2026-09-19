#!/usr/bin/env python3
"""Validate model-produced atomic suspicions against their original CSV text.

The input JSONL transport contract is one object per case::

    {"id": "case-1", "suspicion": { ... AtomicSuspicion fields ... }}

Model output may omit cases (they are emitted with ``model_output_status`` set
to ``MISSING``), but duplicate and unknown ids are rejected.  This runner does
not read labels and never promotes a probabilistic suspicion to formal proof.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import subprocess
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping

from experiments.architectures_v2.source_grounding import (
    AtomicSuspicion,
    SpanClaim,
    validate_suspicion,
)


MAX_CSV_FIELD_CHARS = 16 * 1024 * 1024


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_cases(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(MAX_CSV_FIELD_CHARS)
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = {"id", "prompt", "response"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV misses required columns: {', '.join(sorted(missing))}")
        cases: list[dict[str, str]] = []
        seen: set[str] = set()
        for line_number, row in enumerate(reader, start=2):
            case_id = (row.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"empty id at CSV line {line_number}")
            if case_id in seen:
                raise ValueError(f"duplicate input id {case_id!r} at CSV line {line_number}")
            seen.add(case_id)
            cases.append(
                {"id": case_id, "prompt": row.get("prompt") or "", "response": row.get("response") or ""}
            )
    return cases


def _object(value: Any, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ValueError(f"{name} must be a JSON object")
    return value


def _string(value: Any, name: str, *, optional: bool = False) -> str | None:
    if optional and value is None:
        return None
    if not isinstance(value, str):
        raise ValueError(f"{name} must be a string")
    return value


def _span(value: Any, name: str) -> SpanClaim:
    raw = _object(value, name)
    document = _string(raw.get("document"), f"{name}.document")
    quote = _string(raw.get("quote"), f"{name}.quote")
    start, end = raw.get("start"), raw.get("end")
    for offset, offset_name in ((start, "start"), (end, "end")):
        if offset is not None and (isinstance(offset, bool) or not isinstance(offset, int)):
            raise ValueError(f"{name}.{offset_name} must be an integer or null")
    return SpanClaim(document=document, quote=quote, start=start, end=end)  # type: ignore[arg-type]


def parse_suspicion(value: Any, *, context: str) -> AtomicSuspicion:
    raw = _object(value, context)
    score = raw.get("score")
    if isinstance(score, bool) or not isinstance(score, (int, float)):
        raise ValueError(f"{context}.score must be a number")
    if not 0.0 <= float(score) <= 1.0:
        raise ValueError(f"{context}.score must be within [0, 1]")
    attributes = _object(raw.get("reason_attributes", {}), f"{context}.reason_attributes")
    if not all(isinstance(key, str) and isinstance(item, str) for key, item in attributes.items()):
        raise ValueError(f"{context}.reason_attributes keys and values must be strings")
    target_raw = raw.get("target")
    return AtomicSuspicion(
        reason_type=_string(raw.get("reason_type"), f"{context}.reason_type"),  # type: ignore[arg-type]
        source_kind=_string(raw.get("source_kind"), f"{context}.source_kind"),  # type: ignore[arg-type]
        source=_span(raw.get("source"), f"{context}.source"),
        proposed_violation=_string(raw.get("proposed_violation"), f"{context}.proposed_violation"),  # type: ignore[arg-type]
        score=float(score),
        target=None if target_raw is None else _span(target_raw, f"{context}.target"),
        entity=_string(raw.get("entity"), f"{context}.entity", optional=True),
        time_scope=_string(raw.get("time_scope"), f"{context}.time_scope", optional=True),
        field=_string(raw.get("field"), f"{context}.field", optional=True),
        reason_attributes=dict(attributes),
    )


def read_model_outputs(path: Path, known_ids: set[str]) -> dict[str, AtomicSuspicion]:
    records: dict[str, AtomicSuspicion] = {}
    with path.open("r", encoding="utf-8-sig") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                raise ValueError(f"blank JSONL record at line {line_number}")
            try:
                raw = _object(json.loads(line), f"JSONL line {line_number}")
            except json.JSONDecodeError as exc:
                raise ValueError(f"invalid JSON at JSONL line {line_number}: {exc.msg}") from exc
            case_id = _string(raw.get("id"), f"JSONL line {line_number}.id")
            assert case_id is not None
            if case_id in records:
                raise ValueError(f"duplicate model-output id {case_id!r} at JSONL line {line_number}")
            if case_id not in known_ids:
                raise ValueError(f"unknown model-output id {case_id!r} at JSONL line {line_number}")
            records[case_id] = parse_suspicion(
                raw.get("suspicion"), context=f"JSONL line {line_number}.suspicion"
            )
    return records


def read_config(path: Path) -> tuple[dict[str, Any], float]:
    try:
        config = _object(json.loads(path.read_text(encoding="utf-8-sig")), "config")
    except json.JSONDecodeError as exc:
        raise ValueError(f"invalid config JSON: {exc.msg}") from exc
    threshold = config.get("positive_threshold", 0.5)
    if isinstance(threshold, bool) or not isinstance(threshold, (int, float)):
        raise ValueError("config positive_threshold must be a number")
    threshold = float(threshold)
    if not 0.0 <= threshold <= 1.0:
        raise ValueError("config positive_threshold must be within [0, 1]")
    return dict(config), threshold


def git_sha() -> str | None:
    try:
        return subprocess.run(
            ["git", "rev-parse", "HEAD"],
            check=True,
            capture_output=True,
            text=True,
            cwd=Path(__file__).resolve().parents[2],
        ).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(args: argparse.Namespace) -> int:
    started = time.perf_counter()
    started_at = datetime.now(UTC).isoformat()
    input_path = Path(args.input).resolve(strict=True)
    model_output_path = Path(args.model_output).resolve(strict=True)
    config_path = Path(args.config).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve()
    if output_dir.exists():
        raise ValueError(f"refusing to overwrite existing output path: {output_dir}")

    cases = read_cases(input_path)
    model_outputs = read_model_outputs(model_output_path, {case["id"] for case in cases})
    config, threshold = read_config(config_path)
    output_dir.mkdir(parents=True, exist_ok=False)

    counts = {"ANCHORED": 0, "UNANCHORED": 0, "positive": 0, "missing": 0}
    records_path = output_dir / "records.jsonl"
    with records_path.open("x", encoding="utf-8", newline="\n") as destination:
        for case in cases:
            suspicion = model_outputs.get(case["id"])
            if suspicion is None:
                counts["missing"] += 1
                record: dict[str, Any] = {
                    "id": case["id"],
                    "model_output_status": "MISSING",
                    "grounding": None,
                    "probabilistic_label": 0,
                    "formal_status": "UNRESOLVED",
                }
            else:
                grounded = validate_suspicion(
                    suspicion,
                    {"prompt": case["prompt"], "response": case["response"]},
                    positive_threshold=threshold,
                )
                counts[grounded.grounding_status] += 1
                counts["positive"] += grounded.probabilistic_label
                record = {
                    "id": case["id"],
                    "model_output_status": "PRESENT",
                    "grounding": grounded.to_dict(),
                    "probabilistic_label": grounded.probabilistic_label,
                    "formal_status": grounded.formal_status,
                }
            destination.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")

    manifest = {
        "runner": "architectures_v2/source_grounding",
        "started_at_utc": started_at,
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "elapsed_seconds": round(time.perf_counter() - started, 6),
        "git_sha": git_sha(),
        "input_sha256": file_sha256(input_path),
        "model_output_sha256": file_sha256(model_output_path),
        "config_sha256": file_sha256(config_path),
        "config": config,
        "case_count": len(cases),
        "model_output_count": len(model_outputs),
        "counts": counts,
        "formal_status_policy": "UNRESOLVED; probabilistic labels are not proof certificates",
    }
    (output_dir / "run_manifest.json").write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )
    print(json.dumps({"output_dir": str(output_dir), "counts": counts}, ensure_ascii=False))
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CSV with id,prompt,response")
    parser.add_argument("--model-output", required=True, help="Raw atomic-suspicion JSONL")
    parser.add_argument("--config", required=True, help="JSON variant/config file")
    parser.add_argument("--output-dir", required=True, help="New directory for records and manifest")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (OSError, ValueError) as exc:
        print(f"source_grounding: {exc}", file=sys.stderr)
        raise SystemExit(2)
