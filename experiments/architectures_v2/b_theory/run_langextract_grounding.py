"""Append-only LangExtract grounding pass over saved provider theories."""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
from dataclasses import asdict
from enum import Enum
from pathlib import Path

from .contracts import CaseInput, TheoryCandidate
from .langextract_grounder import MistralLangExtractGrounder


def _rows(path: Path):
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def _default(value):
    if isinstance(value, Enum):
        return value.value
    raise TypeError(type(value).__name__)


def run_cli(args, *, grounder=None) -> int:
    case_path = Path(args.input).resolve(strict=True)
    provider_path = Path(args.provider_output).resolve(strict=True)
    output = Path(args.output).resolve()
    cases = {item.case_id: item for item in
             (CaseInput.parse(row) for row in _rows(case_path))}
    fingerprint = hashlib.sha256(
        (hashlib.sha256(case_path.read_bytes()).hexdigest() +
         hashlib.sha256(provider_path.read_bytes()).hexdigest() + args.model).encode()).hexdigest()
    completed = set()
    if output.exists():
        prior = _rows(output)
        if any(row.get("run_fingerprint") != fingerprint for row in prior):
            raise ValueError("resume fingerprint differs from existing output")
        completed = {row["case_id"] for row in prior}
    grounder = grounder or MistralLangExtractGrounder(
        model_id=args.model, api_key_env=args.api_key_env)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as destination:
        for row in _rows(provider_path):
            case_id = row.get("case_id")
            if case_id in completed:
                continue
            if case_id not in cases:
                raise ValueError(f"unknown case_id in provider output: {case_id}")
            started, grounded = time.perf_counter(), []
            for raw in row.get("candidates", []):
                grounded.append(asdict(grounder.ground(cases[case_id],
                                                       TheoryCandidate.parse(raw))))
            record = {**row, "candidates": grounded,
                      "langextract": {"status": "EXECUTED", "model": args.model,
                                      "base_url": "https://api.mistral.ai/v1",
                                      "role": "SOURCE_GROUNDING_ONLY",
                                      "latency_seconds": round(time.perf_counter() - started, 6)},
                      "run_fingerprint": fingerprint}
            destination.write(json.dumps(record, ensure_ascii=False, sort_keys=True,
                                         default=_default) + "\n")
            destination.flush()
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CaseInput JSONL")
    parser.add_argument("--provider-output", required=True)
    parser.add_argument("--output", required=True)
    parser.add_argument("--model", default="ministral-14b-latest")
    parser.add_argument("--api-key-env", default="MISTRAL_API_KEY")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli(parse_args()))
    except (OSError, RuntimeError, ValueError, json.JSONDecodeError) as exc:
        print(f"b_langextract: {type(exc).__name__}: {exc}", file=sys.stderr)
        raise SystemExit(2)
