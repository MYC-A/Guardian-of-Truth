"""Batch runner for real donor extractors with injectable test doubles."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections.abc import Callable, Sequence
from pathlib import Path
from typing import Any

from guardian_truth.semantic_pipeline_v1.render import render_rule
from guardian_truth.semantic_pipeline_v1.types import to_wire

from .contracts import CaseInput


def _canonical(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def _digest(value: Any) -> str:
    return hashlib.sha256(_canonical(value).encode("utf-8")).hexdigest()


def _theory(case_id: str, provider: str, wire_candidates: list[dict]) -> dict:
    digest = _digest(wire_candidates)
    elements = []
    for item in wire_candidates:
        try:
            from guardian_truth.semantic_pipeline_v1.rule_ir import rule_from_dict
            interpretation = render_rule(rule_from_dict(item["rule"]))
        except Exception:
            interpretation = "structured donor RuleIR hypothesis"
        elements.append({"element_id": item["candidate_id"],
                         "interpretation": interpretation,
                         "wire_candidate": item})
    return {"candidate_id": f"{provider}:{case_id}:{digest[:16]}",
            "provider": provider, "elements": elements, "clause_accounts": []}


def _sources(cases: Sequence[CaseInput]):
    return [(case, source) for case in cases for source in case.sources]


def _safe_error(exc: Exception, secrets: Sequence[str] = ()) -> str:
    message = f"{type(exc).__name__}: {exc}"
    for secret in secrets:
        if secret:
            message = message.replace(secret, "[REDACTED]")
    return message[:1000]


def _redact(value: Any, secrets: Sequence[str]) -> Any:
    if isinstance(value, str):
        for secret in secrets:
            if secret:
                value = value.replace(secret, "[REDACTED]")
        return value
    if isinstance(value, list):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, tuple):
        return [_redact(item, secrets) for item in value]
    if isinstance(value, dict):
        return {key: _redact(item, secrets) for key, item in value.items()
                if "api_key" not in str(key).casefold()}
    return value


def _extract(extractor, **kwargs):
    """Return normalized candidates and a genuinely pre-normalization response."""
    if hasattr(extractor, "extract_with_raw"):
        captured = extractor.extract_with_raw(**kwargs)
        return list(captured.candidates), captured.raw_response
    # Kept only for injected legacy fakes. Never mislabel normalized wire as raw.
    return list(extractor.extract(**kwargs)), None


def run_provider_batch(cases: Sequence[CaseInput], providers: Sequence[str], *,
                       mistral_model: str, nuextract_model: str,
                       gliner_model: str, gliner_python: str,
                       device: str = "cuda", api_key_env: str = "MISTRAL_API_KEY",
                       mistral_factory: Callable | None = None,
                       nuextract_loader: Callable | None = None,
                       nuextract_factory: Callable | None = None,
                       gliner_factory: Callable | None = None) -> list[dict]:
    """Execute each selected model once per batch lifecycle.

    The NuExtract loader is called exactly once. GLiNER is emitted as
    independent evidence and is blocked from proof admission downstream.
    """
    selected = tuple(dict.fromkeys(providers))
    unknown = set(selected) - {"mistral", "nuextract", "gliner"}
    if unknown:
        raise ValueError(f"unknown providers: {sorted(unknown)}")
    if "mistral" in selected and mistral_model != "ministral-14b-latest":
        raise ValueError("Mistral provider model must be ministral-14b-latest")
    rows = {case.case_id: {"case_id": case.case_id, "candidates": [],
                          "provider_runs": {}} for case in cases}
    items = _sources(cases)

    if "mistral" in selected:
        from .raw_capture import RawMistralExtractor
        factory = mistral_factory or (lambda: RawMistralExtractor(
            model=mistral_model, api_key_env=api_key_env))
        extractor = factory()
        if hasattr(extractor, "client") and hasattr(extractor.client, "validate_configuration"):
            extractor.client.validate_configuration()
        for case in cases:
            started, candidates, raw_responses, error = time.perf_counter(), [], [], None
            try:
                for source in case.sources:
                    extracted, raw = _extract(extractor, segment_id=source.source_id,
                                              source_text=source.text, context=())
                    candidates.extend(extracted)
                    if raw is not None:
                        raw_responses.append({"source_id": source.source_id, "response": raw})
            except Exception as exc:
                error = _safe_error(exc, (os.environ.get(api_key_env, ""),))
            _store(rows[case.case_id], "mistral", candidates, started, error,
                   {"model": mistral_model}, raw_responses,
                   secrets=(os.environ.get(api_key_env, ""),))

    if "nuextract" in selected:
        from guardian_truth.semantic_pipeline_v1.models.nuextract import NuExtractRuleExtractor
        from .raw_capture import RawNuExtractExtractor
        loader = nuextract_loader or NuExtractRuleExtractor.load
        factory = nuextract_factory or (lambda model, processor: RawNuExtractExtractor(
            model_name=nuextract_model, model=model, processor=processor))
        load_started = time.perf_counter()
        model, processor = loader(nuextract_model, device)
        load_seconds = time.perf_counter() - load_started
        extractor = factory(model, processor)
        for case in cases:
            started, candidates, raw_responses, error = time.perf_counter(), [], [], None
            try:
                for source in case.sources:
                    extracted, raw = _extract(extractor, segment_id=source.source_id,
                                              source_text=source.text, context=())
                    candidates.extend(extracted)
                    if raw is not None:
                        raw_responses.append({"source_id": source.source_id, "response": raw})
            except Exception as exc:
                error = _safe_error(exc)
            _store(rows[case.case_id], "nuextract", candidates, started, error,
                   {"model": nuextract_model, "batch_model_load_seconds": round(load_seconds, 6),
                    "batch_model_load_count": 1}, raw_responses)

    if "gliner" in selected:
        from guardian_truth.semantic_pipeline_v1.models.gliner_optional import (
            GLiNER2Sidecar, normalize_gliner2_evidence)
        factory = gliner_factory or (lambda: GLiNER2Sidecar(
            model_name=gliner_model, python_executable=gliner_python))
        started = time.perf_counter()
        raw_items = [{"id": f"{case.case_id}\0{source.source_id}", "text": source.text}
                     for case, source in items]
        response, error = None, None
        try:
            response = factory().extract_batch(raw_items, device=device)
        except Exception as exc:
            error = _safe_error(exc)
        returned = {item["id"]: item for item in (response or {}).get("rows", [])}
        for case in cases:
            candidates = []
            if error is None:
                for source in case.sources:
                    row = returned.get(f"{case.case_id}\0{source.source_id}", {})
                    candidates.extend(normalize_gliner2_evidence(
                        row, segment_id=source.source_id, source_text=source.text,
                        model_name=gliner_model))
            _store(rows[case.case_id], "gliner", candidates, started, error,
                   {"model": gliner_model, "role": "EVIDENCE_ONLY_CLAUSE_GAP_HINT",
                    "batch_response_metadata": {key: value for key, value in (response or {}).items()
                                                if key != "rows"}},
                   ([{"response": returned.get(f"{case.case_id}\0{source.source_id}")}
                     for source in case.sources] if response is not None else []))
    return [rows[case.case_id] for case in cases]


def _store(row: dict, provider: str, candidates, started: float,
           error: str | None, extra: dict, raw_responses=(), secrets=()) -> None:
    wire = [to_wire(item) for item in candidates]
    status = "EXECUTED" if error is None else "FAILED"
    raw = list(raw_responses)
    redacted = _redact(raw, secrets)
    row["provider_runs"][provider] = {
        "status": status, "error": error,
        "latency_seconds": round(time.perf_counter() - started, 6),
        "wire_sha256": _digest(wire), "wire_candidates": wire,
        "raw_available": bool(raw),
        "raw_responses": redacted,
        "raw_sha256": _digest(raw) if raw else None,
        "redacted_raw_sha256": _digest(redacted) if raw else None,
        "raw_note": ("captured before RuleCandidate normalization"
                     if raw else "legacy injected extractor did not expose pre-normalization raw"),
        **extra,
    }
    if error is None:
        row["candidates"].append(_theory(row["case_id"], provider, wire))


def _read_cases(path: Path) -> list[CaseInput]:
    return [CaseInput.parse(json.loads(line)) for line in path.read_text(encoding="utf-8").splitlines()
            if line.strip()]


def run_cli(args) -> int:
    path = Path(args.input).resolve(strict=True)
    output = Path(args.output).resolve()
    cases = _read_cases(path)
    input_sha = hashlib.sha256(path.read_bytes()).hexdigest()
    fingerprint = _digest({"input_sha256": input_sha, "providers": args.provider,
                           "mistral_model": args.mistral_model,
                           "nuextract_model": args.nuextract_model,
                           "gliner_model": args.gliner_model, "device": args.device})
    completed = set()
    if output.exists():
        existing = [json.loads(line) for line in output.read_text(encoding="utf-8").splitlines()
                    if line.strip()]
        if any(row.get("run_fingerprint") != fingerprint for row in existing):
            raise ValueError("resume fingerprint differs from existing output")
        completed = {row["case_id"] for row in existing}
    pending = [case for case in cases if case.case_id not in completed]
    if not pending:
        return 0
    rows = run_provider_batch(
        pending, args.provider, mistral_model=args.mistral_model,
        nuextract_model=args.nuextract_model, gliner_model=args.gliner_model,
        gliner_python=args.gliner_python, device=args.device,
        api_key_env=args.api_key_env)
    output.parent.mkdir(parents=True, exist_ok=True)
    with output.open("a", encoding="utf-8", newline="\n") as destination:
        for row in rows:
            destination.write(json.dumps({**row, "run_fingerprint": fingerprint},
                                         ensure_ascii=False, sort_keys=True) + "\n")
            destination.flush()
    return 0


def parse_args(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="CaseInput JSONL")
    parser.add_argument("--output", required=True, help="append-only provider JSONL")
    parser.add_argument("--provider", action="append", required=True,
                        choices=["mistral", "nuextract", "gliner"])
    parser.add_argument("--mistral-model", default="ministral-14b-latest")
    parser.add_argument("--nuextract-model", default="numind/NuExtract3-W4A16")
    parser.add_argument("--gliner-model", default="fastino/gliner2.5-multi-v1")
    parser.add_argument("--gliner-python", default="/mnt/data/guardian/gliner2_env/bin/python")
    parser.add_argument("--device", default="cuda")
    parser.add_argument("--api-key-env", default="MISTRAL_API_KEY")
    return parser.parse_args(argv)


if __name__ == "__main__":
    try:
        raise SystemExit(run_cli(parse_args()))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        print(f"b_provider_runner: {exc}", file=sys.stderr)
        raise SystemExit(2)
