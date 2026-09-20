"""Resumable CLI for controlled Architecture B theory comparisons.

Inputs contain no gold labels. Model adapters run separately and emit donor
``RuleCandidate`` wire records; this command validates identical saved outputs
across B0/B1/B2/B3 without importing model runtimes.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from datetime import UTC, datetime
from pathlib import Path

from .contracts import CaseInput, TheoryCandidate, Variant
from .orchestrator import run_case


def _sha(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _rows(path: Path) -> list[dict]:
    rows = []
    with path.open(encoding="utf-8") as source:
        for line_no, line in enumerate(source, 1):
            if line.strip():
                value = json.loads(line)
                if not isinstance(value, dict):
                    raise ValueError(f"{path}:{line_no}: expected JSON object")
                rows.append(value)
    return rows


def _candidate_map(specs: list[str]) -> tuple[dict[str, list[TheoryCandidate]], dict[str, str]]:
    result: dict[str, list[TheoryCandidate]] = {}
    hashes = {}
    parsed_specs = []
    declared_providers = set()
    for spec in specs:
        if "=" not in spec:
            raise ValueError("provider output must be NAME=PATH")
        provider, raw_path = spec.split("=", 1)
        if not provider:
            raise ValueError("provider output NAME must be non-empty")
        if provider in declared_providers:
            raise ValueError(f"duplicate provider output spec: {provider}")
        declared_providers.add(provider)
        path = Path(raw_path).resolve(strict=True)
        parsed_specs.append((provider, path))
        hashes[provider] = _sha(path)
    allowed_providers = {"mistral", "nuextract", "gliner", *declared_providers}
    seen_candidates = set()
    for provider, path in parsed_specs:
        seen_case_rows = set()
        selected_seen = False
        explicit_in_file = set()
        for row in _rows(path):
            case_id = row.get("case_id")
            if not isinstance(case_id, str):
                raise ValueError(f"{path}: candidate row missing case_id")
            if case_id in seen_case_rows:
                raise ValueError(f"{path}: duplicate case row for {case_id}")
            seen_case_rows.add(case_id)
            raw_candidates = row.get("candidates", [])
            if not isinstance(raw_candidates, list):
                raise ValueError(f"{path}: candidates must be a list")
            provider_runs = row.get("provider_runs", {})
            if provider_runs is not None and not isinstance(provider_runs, dict):
                raise ValueError(f"{path}: provider_runs must be an object")
            unknown_runs = set(provider_runs or {}) - allowed_providers
            if unknown_runs:
                raise ValueError(f"{path}: unknown provider_runs: {sorted(unknown_runs)}")
            if provider in (provider_runs or {}):
                selected_seen = True
            for raw in raw_candidates:
                if not isinstance(raw, dict):
                    raise ValueError(f"{path}: candidate must be an object")
                value = dict(raw)
                explicit = value.get("provider")
                if explicit is None:
                    if len(provider_runs or {}) > 1:
                        raise ValueError(f"{path}: provider missing in combined output candidate")
                    value["provider"] = provider
                    explicit = provider
                if not isinstance(explicit, str) or explicit not in allowed_providers:
                    raise ValueError(f"{path}: unknown candidate provider: {explicit!r}")
                if provider_runs and explicit not in provider_runs:
                    raise ValueError(f"{path}: candidate/provider_runs identity mismatch: "
                                     f"{explicit}")
                explicit_in_file.add(explicit)
                if explicit != provider:
                    # Combined provider_runner rows are intentionally read once
                    # per NAME=PATH spec. Other known providers are filtered.
                    continue
                selected_seen = True
                candidate = TheoryCandidate.parse(value)
                identity = (case_id, candidate.candidate_id)
                if identity in seen_candidates:
                    raise ValueError(f"{path}: duplicate candidate_id for {case_id}: "
                                     f"{candidate.candidate_id}")
                seen_candidates.add(identity)
                result.setdefault(case_id, []).append(candidate)
        if explicit_in_file and provider not in explicit_in_file and not selected_seen:
            raise ValueError(f"{path}: provider identity mismatch for requested {provider}")
    return result, hashes


def _git_sha() -> str | None:
    try:
        return subprocess.run(["git", "rev-parse", "HEAD"], check=True,
                              capture_output=True, text=True,
                              cwd=Path(__file__).resolve().parents[3]).stdout.strip()
    except (OSError, subprocess.CalledProcessError):
        return None


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve(strict=True)
    output_dir = Path(args.output_dir).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    records_path = output_dir / "records.jsonl"
    manifest_path = output_dir / "run_manifest.json"
    candidates, candidate_hashes = _candidate_map(args.provider_output)
    repairs, repair_hashes = _candidate_map(args.repair_output)
    fingerprint = {
        "variant": args.variant,
        "input_sha256": _sha(input_path),
        "provider_output_sha256": candidate_hashes,
        "repair_output_sha256": repair_hashes,
    }
    if manifest_path.exists():
        previous = json.loads(manifest_path.read_text(encoding="utf-8"))
        if previous.get("fingerprint") != fingerprint:
            raise ValueError("resume fingerprint differs from existing run")
    completed = set()
    if records_path.exists():
        completed = {row["case_id"] for row in _rows(records_path)}
    cases = [CaseInput.parse(row) for row in _rows(input_path)]
    if len({case.case_id for case in cases}) != len(cases):
        raise ValueError("duplicate case_id in input")
    known = {case.case_id for case in cases}
    if (set(candidates) | set(repairs)) - known:
        raise ValueError("model output contains unknown case_id")
    variant = Variant(args.variant)
    with records_path.open("a", encoding="utf-8", newline="\n") as destination:
        for case in cases:
            if case.case_id in completed:
                continue
            record = run_case(case, candidates.get(case.case_id, ()), variant,
                              repairs=repairs.get(case.case_id, ()))
            destination.write(json.dumps(record, ensure_ascii=False, sort_keys=True) + "\n")
            destination.flush()
    manifest = {
        "runner": "architectures_v2/b_theory",
        "finished_at_utc": datetime.now(UTC).isoformat(),
        "git_sha": _git_sha(),
        "fingerprint": fingerprint,
        "case_count": len(cases),
        "records_sha256": _sha(records_path),
        "gold_free": True,
        "proof_policy": "all model candidates remain hypotheses until existing binding and proof",
    }
    manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2,
                                        sort_keys=True) + "\n", encoding="utf-8")
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True)
    parser.add_argument("--variant", required=True, choices=[item.value for item in Variant])
    parser.add_argument("--provider-output", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--repair-output", action="append", default=[], metavar="NAME=PATH")
    parser.add_argument("--output-dir", required=True)
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"b_theory: {exc}", file=sys.stderr)
        raise SystemExit(2)
