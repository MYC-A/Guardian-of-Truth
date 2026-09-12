"""Deterministic versioned artifact integrity and prediction-seal boundaries."""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
from typing import Any


def canonical(value: Any) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":"), allow_nan=False).encode("utf-8")


def digest(value: Any) -> str:
    return hashlib.sha256(canonical(value)).hexdigest()


def file_digest(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def write_new(path: Path, value: Any) -> None:
    """Never silently replace a frozen input, prediction or result."""
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("x", encoding="utf-8", newline="\n") as handle:
        handle.write(json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + "\n")


def verify_files(root: Path, entries: dict[str, str]) -> list[str]:
    failures = []
    base = root.resolve()
    for relative, expected in entries.items():
        target = (base / relative).resolve()
        if not target.is_relative_to(base):
            failures.append(relative + ":OUTSIDE_ROOT")
        elif not target.is_file():
            failures.append(relative + ":MISSING")
        elif file_digest(target) != expected:
            failures.append(relative + ":HASH_MISMATCH")
    return failures


def prediction_seal(rows: list[dict], case_ids: list[str], *,
                    architecture_commit: str, configuration_sha256: str) -> dict:
    """Seal only full, exactly-once predictions. Gold is not an input."""
    observed = [row.get("case_id") for row in rows]
    if (len(observed) != len(set(observed)) or len(case_ids) != len(set(case_ids))
            or set(observed) != set(case_ids)):
        raise ValueError("prediction coverage mismatch")
    if len(architecture_commit) != 40 or len(configuration_sha256) != 64:
        raise ValueError("full candidate/configuration identities required")
    return {"schema_version": "guardian-vnext-prediction-seal-v1",
            "architecture_commit": architecture_commit,
            "configuration_sha256": configuration_sha256,
            "prediction_sha256": digest(rows), "case_ids_sha256": digest(case_ids),
            "count": len(rows), "gold_joined": False}


def load_gold_after_seal(path: Path, *, expected_gold_sha256: str,
                         rows: list[dict], case_ids: list[str], seal: dict,
                         architecture_commit: str, configuration_sha256: str) -> dict:
    expected = prediction_seal(rows, case_ids, architecture_commit=architecture_commit,
                               configuration_sha256=configuration_sha256)
    if seal != expected:
        raise ValueError("invalid prediction seal; gold was not opened")
    if file_digest(path) != expected_gold_sha256:
        raise ValueError("gold storage hash mismatch")
    gold = json.loads(path.read_text(encoding="utf-8"))
    if set(gold.get("labels", {})) != set(case_ids):
        raise ValueError("gold IDs mismatch")
    return gold
