#!/usr/bin/env python3
"""Offline claim-pair diagnostic with a cached NLI DeBERTa model.

`prompt` is treated as a premise and `response` as a hypothesis.  This runner
does not parse an agent trace and does not produce proof certificates.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


MODEL_ID = "cross-encoder/nli-deberta-v3-base"


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as source:
        for block in iter(lambda: source.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as source:
        reader = csv.DictReader(source)
        missing = {"id", "prompt", "response"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV misses required columns: {', '.join(sorted(missing))}")
        seen: set[str] = set()
        cases = []
        for line_number, row in enumerate(reader, start=2):
            case_id = (row.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"empty id at line {line_number}")
            if case_id in seen:
                raise ValueError(f"duplicate id {case_id!r} at line {line_number}")
            seen.add(case_id)
            cases.append({"id": case_id, "prompt": row.get("prompt") or "", "response": row.get("response") or ""})
    return cases


def bound(text: str, limit: int, field: str) -> tuple[str, dict[str, Any]]:
    if len(text) <= limit:
        return text, {"field": field, "original_chars": len(text), "kept_chars": len(text), "truncated": False, "reason": None}
    marker = "\n[... omitted by offline_nli character bound ...]\n"
    usable = limit - len(marker)
    if usable <= 0:
        kept = text[:limit]
        reason = f"{field}_exceeds_max_field_chars; marker did not fit"
    else:
        left = usable // 2
        kept = text[:left] + marker + text[-(usable - left):]
        reason = f"{field}_exceeds_max_field_chars; kept head and tail"
    return kept, {"field": field, "original_chars": len(text), "kept_chars": len(kept), "truncated": True, "reason": reason}


def make_output_dir(requested: str | None) -> Path:
    directory = Path(requested) if requested else Path("outputs") / "research_offline_nli" / datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
    if "research_offline_nli" not in directory.as_posix():
        raise ValueError("output directory must be in a research_offline_nli namespace")
    if directory.exists() and any(directory.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {directory}")
    directory.mkdir(parents=True, exist_ok=True)
    return directory


class LocalNliRunner:
    def __init__(self, model_path: Path, device_map: str) -> None:
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            import torch
            from transformers import AutoConfig, AutoModelForSequenceClassification, AutoTokenizer
        except ImportError as exc:
            raise RuntimeError("real execution needs installed torch and transformers") from exc
        self.torch = torch
        self.config = AutoConfig.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True, trust_remote_code=False)
        self.model = AutoModelForSequenceClassification.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=False,
            torch_dtype="auto", device_map=device_map,
        )
        self.model.eval()
        self.label_map = {str(index): str(label) for index, label in sorted(self.config.id2label.items())}

    def predict(self, premise: str, hypothesis: str, max_tokens: int) -> dict[str, Any]:
        untruncated = self.tokenizer(premise, hypothesis, add_special_tokens=True, truncation=False)
        original_tokens = len(untruncated["input_ids"])
        model_limit = int(getattr(self.config, "max_position_embeddings", max_tokens) or max_tokens)
        effective_limit = min(max_tokens, model_limit)
        encoded = self.tokenizer(
            premise, hypothesis, add_special_tokens=True, truncation=True,
            max_length=effective_limit, return_tensors="pt",
        ).to(self.model.device)
        used_tokens = int(encoded["input_ids"].shape[-1])
        with self.torch.inference_mode():
            output = self.model(**encoded)
            logits = output.logits[0].detach().float().cpu()
            probabilities = self.torch.softmax(logits, dim=-1)
        return {
            "status": "ok",
            "logits": [float(value) for value in logits.tolist()],
            "probabilities": [float(value) for value in probabilities.tolist()],
            "predicted_label_id": int(self.torch.argmax(probabilities).item()),
            "predicted_label": self.label_map[str(int(self.torch.argmax(probabilities).item()))],
            "token_count": {"original_pair": original_tokens, "used_pair": used_tokens},
            "token_truncation": {
                "applied": original_tokens > used_tokens,
                "reason": f"pair_exceeds_effective_max_tokens:{original_tokens}>{effective_limit}" if original_tokens > used_tokens else None,
                "effective_max_tokens": effective_limit,
            },
        }


def import_smoke() -> dict[str, str]:
    try:
        import torch
        import transformers
    except ImportError as exc:
        raise RuntimeError("import smoke needs installed torch and transformers") from exc
    return {"torch": str(torch.__version__), "transformers": str(transformers.__version__)}


def run(args: argparse.Namespace) -> int:
    if args.import_smoke:
        print(json.dumps({"import_smoke": import_smoke()}))
        return 0
    input_path = Path(args.input).resolve(strict=True)
    cases = read_cases(input_path)
    output_dir = make_output_dir(args.output_dir)
    config = {
        "runner": "offline_nli/nli_deberta_v3_base",
        "model_id": MODEL_ID,
        "model_path": str(Path(args.model_path).resolve()) if args.model_path else None,
        "offline_only": True,
        "device_map": args.device_map,
        "max_field_chars": args.max_field_chars,
        "max_tokens": args.max_tokens,
        "input_path": str(input_path),
        "input_sha256": file_sha256(input_path),
        "case_count": len(cases),
        "dry_run": args.dry_run,
        "started_at_utc": datetime.now(UTC).isoformat(),
    }
    runner: LocalNliRunner | None = None
    if not args.dry_run:
        if not args.model_path:
            raise ValueError("--model-path is required unless --dry-run is used")
        model_path = Path(args.model_path).resolve(strict=True)
        if not model_path.is_dir():
            raise ValueError("--model-path must be an existing local model directory")
        runner = LocalNliRunner(model_path, args.device_map)
        config["label_map"] = runner.label_map
    (output_dir / "run_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    counts: dict[str, int] = {}
    with (output_dir / "records.jsonl").open("w", encoding="utf-8") as destination:
        for case in cases:
            premise, premise_trace = bound(case["prompt"], args.max_field_chars, "prompt")
            hypothesis, hypothesis_trace = bound(case["response"], args.max_field_chars, "response")
            started = time.perf_counter()
            if args.dry_run:
                result = {"status": "dry_run", "logits": None, "probabilities": None, "predicted_label_id": None,
                          "predicted_label": None, "token_count": None, "token_truncation": None,
                          "note": "no model weights were loaded or downloaded"}
            else:
                try:
                    assert runner is not None
                    result = runner.predict(premise, hypothesis, args.max_tokens)
                except Exception as exc:
                    result = {"status": "runtime_error", "logits": None, "probabilities": None, "predicted_label_id": None,
                              "predicted_label": None, "token_count": None, "token_truncation": None,
                              "note": f"{type(exc).__name__}: {exc}"}
            record = {
                "id": case["id"],
                "pair_interpretation": {"prompt": "premise", "response": "hypothesis"},
                "formal_proof_status": "UNRESOLVED",
                "model_decision_type": "probabilistic_nli_diagnostic",
                "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                "character_truncation": [premise_trace, hypothesis_trace],
                **result,
            }
            counts[record["status"]] = counts.get(record["status"], 0) + 1
            destination.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {"output_dir": str(output_dir), "records": sum(counts.values()), "status_counts": counts,
               "input_sha256": config["input_sha256"], "finished_at_utc": datetime.now(UTC).isoformat()}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=False, help="Claim-pair CSV with id,prompt,response")
    parser.add_argument("--model-path", help="Existing local model directory; never a Hugging Face id")
    parser.add_argument("--output-dir", help="Must be in a research_offline_nli namespace")
    parser.add_argument("--device-map", default="auto")
    parser.add_argument("--max-field-chars", type=int, default=6000)
    parser.add_argument("--max-tokens", type=int, default=512)
    parser.add_argument("--dry-run", action="store_true", help="Validate CSV/output contract without importing model libraries")
    parser.add_argument("--import-smoke", action="store_true", help="Import torch/transformers without opening weights")
    args = parser.parse_args(argv)
    if not args.import_smoke and not args.input:
        parser.error("--input is required unless --import-smoke is used")
    if args.max_field_chars < 1 or args.max_tokens < 1:
        parser.error("bounds must be positive")
    return args


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"offline_nli: {exc}", file=sys.stderr)
        raise SystemExit(2)
