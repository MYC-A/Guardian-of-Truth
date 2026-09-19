#!/usr/bin/env python3
"""Score sealed NLI diagnostics against separate groundedness gold labels."""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
from pathlib import Path
from typing import Iterable


LABEL_TO_BINARY = {"contradiction": 1, "entailment": 0, "neutral": 0}


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_gold(path: Path) -> dict[str, int]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = {"id", "label", "criterion"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"gold CSV misses columns: {', '.join(sorted(missing))}")
        gold: dict[str, int] = {}
        for line_number, row in enumerate(reader, start=2):
            if (row.get("criterion") or "").strip() != "groundedness":
                continue
            case_id = (row.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"gold has empty id at line {line_number}")
            if case_id in gold:
                raise ValueError(f"duplicate groundedness gold id {case_id!r}")
            try:
                label = int(row.get("label") or "")
            except ValueError as exc:
                raise ValueError(f"gold id {case_id!r} has a non-integer label") from exc
            if label not in (0, 1):
                raise ValueError(f"gold id {case_id!r} has label outside 0/1")
            gold[case_id] = label
    if not gold:
        raise ValueError("gold has no groundedness rows")
    return gold


def read_predictions(path: Path) -> dict[str, int]:
    predictions: dict[str, int] = {}
    with path.open("r", encoding="utf-8") as source:
        for line_number, line in enumerate(source, start=1):
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                raise ValueError(f"records line {line_number} is invalid JSON") from exc
            if not isinstance(row, dict):
                raise ValueError(f"records line {line_number} is not an object")
            case_id = row.get("id")
            if not isinstance(case_id, str) or not case_id.strip():
                raise ValueError(f"records line {line_number} has invalid id")
            case_id = case_id.strip()
            if case_id in predictions:
                raise ValueError(f"duplicate prediction id {case_id!r}")
            if row.get("status") != "ok":
                raise ValueError(f"prediction {case_id!r} status is not ok")
            if "criterion" in row and row["criterion"] != "groundedness":
                raise ValueError(f"prediction {case_id!r} criterion is not groundedness")
            label = row.get("predicted_label")
            if not isinstance(label, str) or label.casefold() not in LABEL_TO_BINARY:
                raise ValueError(f"prediction {case_id!r} has unknown NLI label {label!r}")
            predictions[case_id] = LABEL_TO_BINARY[label.casefold()]
    if not predictions:
        raise ValueError("records contain no predictions")
    return predictions


def score(records_path: Path, gold_path: Path) -> dict[str, object]:
    predictions = read_predictions(records_path)
    gold = read_gold(gold_path)
    missing = sorted(set(gold) - set(predictions))
    extra = sorted(set(predictions) - set(gold))
    if missing or extra:
        raise ValueError(f"prediction/gold id mismatch: missing={missing}, extra={extra}")
    tp = fp = fn = tn = 0
    for case_id, expected in gold.items():
        predicted = predictions[case_id]
        if predicted == 1 and expected == 1:
            tp += 1
        elif predicted == 1:
            fp += 1
        elif expected == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    return {
        "evaluation_type": "post_hoc_nli_diagnostic",
        "decision_rule": "contradiction=1; entailment_or_neutral=0",
        "criterion": "groundedness",
        "records_sha256": sha256_file(records_path),
        "gold_sha256": sha256_file(gold_path),
        "count": len(gold),
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "precision": round(precision, 6),
        "recall": round(recall, 6),
        "f1": round(f1, 6),
    }


def write_new_json(path: Path, payload: dict[str, object]) -> None:
    if path.exists():
        raise ValueError(f"refusing to overwrite output: {path}")
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    if temporary.exists():
        raise ValueError(f"temporary output already exists: {temporary}")
    try:
        temporary.write_text(json.dumps(payload, indent=2, sort_keys=True) + "\n", encoding="utf-8")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--records", required=True, type=Path)
    parser.add_argument("--gold", required=True, type=Path)
    parser.add_argument("--output", required=True, type=Path)
    return parser.parse_args(argv)


def main(argv: Iterable[str] | None = None) -> int:
    args = parse_args(argv)
    result = score(args.records.resolve(strict=True), args.gold.resolve(strict=True))
    write_new_json(args.output, result)
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except (OSError, ValueError) as exc:
        print(f"score_nli_records: {exc}", file=sys.stderr)
        raise SystemExit(2)
