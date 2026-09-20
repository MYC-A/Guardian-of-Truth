"""Resumable 3--5 case runner for the bidirectional B3 cycle."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
from pathlib import Path

from .b3_cycle import run_b3_cycle
from .contracts import CaseInput, TheoryCritique
from .run_b_theory import _candidate_map, _rows, _sha


def _redact(value):
    secrets = tuple(value for key, value in os.environ.items()
                    if "KEY" in key.upper() and value)
    if isinstance(value, str):
        for secret in secrets:
            value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item) for key, item in value.items()
                if "api_key" not in str(key).casefold()}
    return value


def _artifact_map(paths: list[Path], role: str) -> dict[str, list[dict]]:
    result: dict[str, list[dict]] = {}
    for path in paths:
        for row in _rows(path):
            case_id = row.get("case_id")
            if not isinstance(case_id, str):
                continue
            payload = row.get("raw_responses") or row.get("raw_response")
            if payload is None and isinstance(row.get("provider_runs"), dict):
                payload = {
                    provider: {
                        "raw_responses": run.get("raw_responses"),
                        "source_raw_sha256": run.get("raw_sha256"),
                        "redacted_raw_sha256": run.get("redacted_raw_sha256"),
                    }
                    for provider, run in row["provider_runs"].items()
                    if isinstance(run, dict) and run.get("raw_available")
                } or None
            if payload is None:
                continue
            redacted = _redact(payload)
            source_canonical = json.dumps(payload, ensure_ascii=False, sort_keys=True,
                                          separators=(",", ":"))
            canonical = json.dumps(redacted, ensure_ascii=False, sort_keys=True,
                                   separators=(",", ":"))
            result.setdefault(case_id, []).append({
                "role": role, "source_file": path.name,
                "raw_response": redacted,
                "source_raw_sha256": hashlib.sha256(
                    source_canonical.encode("utf-8")).hexdigest(),
                "sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
                "normalization_status": "PRESERVED_PRE_NORMALIZATION_RESPONSE",
            })
    return result


def _critique_map(path: Path) -> dict[str, list[TheoryCritique]]:
    result: dict[str, list[TheoryCritique]] = {}
    for row in _rows(path):
        case_id = row.get("case_id")
        values = row.get("critiques", [])
        if not isinstance(case_id, str) or not isinstance(values, list):
            raise ValueError("critique rows require case_id and critiques list")
        result[case_id] = [TheoryCritique.parse(item) for item in values]
    return result


def _gap_map(path: Path | None) -> dict[str, list[dict]]:
    if path is None:
        return {}
    result = {}
    for row in _rows(path):
        case_id, evidence = row.get("case_id"), row.get("gap_evidence", [])
        if not isinstance(case_id, str) or not isinstance(evidence, list):
            raise ValueError("gap rows require case_id and gap_evidence list")
        result[case_id] = evidence
    return result


def run(args) -> int:
    input_path = Path(args.input).resolve(strict=True)
    critique_path = Path(args.critique_output).resolve(strict=True)
    gap_path = Path(args.gap_evidence).resolve(strict=True) if args.gap_evidence else None
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path, manifest_path = output_dir / "records.jsonl", output_dir / "run_manifest.json"
    originals, original_hashes = _candidate_map(args.original_output)
    repairs, repair_hashes = _candidate_map(args.repair_output)
    critiques, gaps = _critique_map(critique_path), _gap_map(gap_path)
    original_paths = [Path(item.split("=", 1)[1]).resolve(strict=True)
                      for item in args.original_output]
    repair_paths = [Path(item.split("=", 1)[1]).resolve(strict=True)
                    for item in args.repair_output]
    raw_originals = _artifact_map(original_paths, "ORIGINAL_PROVIDER_RESPONSE")
    raw_repairs = _artifact_map(repair_paths, "REPAIR_RESPONSE")
    raw_critiques = _artifact_map([critique_path], "CRITIQUE_RESPONSE")
    cases = [CaseInput.parse(row) for row in _rows(input_path)]
    if not 3 <= len(cases) <= 5:
        raise ValueError("B3 pilot requires 3 to 5 cases")
    known = {item.case_id for item in cases}
    if (set(originals) | set(repairs) | set(critiques) | set(gaps)) - known:
        raise ValueError("B3 input contains unknown case_id")
    fingerprint = {
        "input": _sha(input_path), "originals": original_hashes,
        "critiques": _sha(critique_path), "repairs": repair_hashes,
        "gap_evidence": _sha(gap_path) if gap_path else None,
    }
    if manifest_path.exists():
        prior = json.loads(manifest_path.read_text(encoding="utf-8"))
        if prior.get("fingerprint") != fingerprint:
            raise ValueError("resume fingerprint differs from existing run")
    completed = ({row["case_id"] for row in _rows(records_path)}
                 if records_path.exists() else set())
    with records_path.open("a", encoding="utf-8", newline="\n") as destination:
        for case in cases:
            if case.case_id in completed:
                continue
            original = originals.get(case.case_id, [])
            if len(original) != 2 or len({item.provider for item in original}) != 2:
                raise ValueError(f"{case.case_id}: expected exactly two independent originals")
            record = run_b3_cycle(case, original, critiques.get(case.case_id, []),
                                  repairs.get(case.case_id, []),
                                  gap_evidence=gaps.get(case.case_id, []))
            record["raw_artifacts"] = [*raw_originals.get(case.case_id, []),
                                       *raw_critiques.get(case.case_id, []),
                                       *raw_repairs.get(case.case_id, [])]
            destination.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            destination.flush()
    manifest_path.write_text(json.dumps({
        "runner": "architectures_v2/b_theory/b3_mutual_cycle",
        "fingerprint": fingerprint, "case_count": len(cases),
        "records_sha256": _sha(records_path),
        "formal_next_step": "formal_handoff.py runs every original and repair separately on N5",
        "selection_policy": "NO_DELETION_NO_MERGE_ALL_ALTERNATIVES_RETAINED",
    }, ensure_ascii=False, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="3--5 CaseInput JSONL rows")
    parser.add_argument("--original-output", action="append", required=True,
                        metavar="PROVIDER=PATH")
    parser.add_argument("--critique-output", required=True)
    parser.add_argument("--repair-output", action="append", required=True,
                        metavar="PROVIDER=PATH")
    parser.add_argument("--gap-evidence")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"b3_cycle: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
