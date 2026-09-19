#!/usr/bin/env python3
"""Run Granite Guardian 3.3 8B from an already-local model directory.

This is an experiment runner.  It intentionally does not call production
Guardian code and it never resolves a Hugging Face model id over the network.
"""

from __future__ import annotations

import argparse
import csv
import hashlib
import json
import math
import os
import re
import sys
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, Iterable


MODEL_ID = "ibm-granite/granite-guardian-3.3-8b"
SUPPORTED_CRITERIA = ("groundedness", "function_call")
SCORE_RE = re.compile(r"<score>\s*(yes|no)\s*</score>", re.IGNORECASE | re.DOTALL)


@dataclass(frozen=True)
class BoundText:
    text: str
    original_chars: int
    kept_chars: int
    truncated: bool
    reason: str | None


def bounded_text(text: str, limit: int, field: str) -> BoundText:
    """Keep both ends, so a late assistant conclusion is not silently lost."""
    if len(text) <= limit:
        return BoundText(text, len(text), len(text), False, None)
    marker = "\n\n[... omitted by offline_guardian context bound ...]\n\n"
    if limit <= len(marker):
        kept = text[:limit]
        return BoundText(
            kept, len(text), len(kept), True,
            f"{field}_exceeds_max_context_chars:{len(text)}>{limit}; marker did not fit",
        )
    remaining = limit - len(marker)
    head = remaining // 2
    tail = remaining - head
    kept = text[:head] + marker + text[-tail:]
    return BoundText(
        kept,
        len(text),
        len(kept),
        True,
        f"{field}_exceeds_max_context_chars:{len(text)}>{limit}; kept head and tail",
    )


def bound_pair(prompt: str, response: str, max_context_chars: int) -> tuple[BoundText, BoundText]:
    # Reserve more of the budget for the response, which is the judged text.
    prompt_limit = max(1, max_context_chars * 2 // 5)
    response_limit = max(1, max_context_chars - prompt_limit)
    return (
        bounded_text(prompt, prompt_limit, "prompt"),
        bounded_text(response, response_limit, "response"),
    )


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_cases(path: Path) -> list[dict[str, str]]:
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"id", "prompt", "response"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV misses required columns: {', '.join(sorted(missing))}")
        cases = []
        seen_ids: set[str] = set()
        for line_no, row in enumerate(reader, start=2):
            case_id = (row.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"input CSV has an empty id at line {line_no}")
            if case_id in seen_ids:
                raise ValueError(f"input CSV has duplicate id {case_id!r} at line {line_no}")
            seen_ids.add(case_id)
            cases.append({
                "id": case_id,
                "prompt": row.get("prompt") or "",
                "response": row.get("response") or "",
                # Optional column; it is never inferred from the prompt.
                "tools": row.get("tools") or "",
            })
    return cases


def read_tools_json(path: Path | None) -> list[dict[str, Any]] | None:
    if path is None:
        return None
    loaded = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
        raise ValueError("--tools-json must contain a JSON list of tool objects")
    return loaded


def case_tools(case: dict[str, str], common_tools: list[dict[str, Any]] | None) -> list[dict[str, Any]] | None:
    if case["tools"].strip():
        loaded = json.loads(case["tools"])
        if not isinstance(loaded, list) or not all(isinstance(item, dict) for item in loaded):
            raise ValueError(f"case {case['id']}: tools column must be a JSON list of objects")
        return loaded
    return common_tools


def parse_score(text: str) -> str | None:
    matches = SCORE_RE.findall(text)
    return matches[-1].lower() if matches else None


def _normalise_token(token: str) -> str:
    return token.strip().lower().replace("▁", "").replace("Ġ", "")


def probability_from_logprobs(logprobs: Any) -> tuple[float | None, str | None]:
    """Estimate P(yes) from any returned yes/no alternative pair.

    The number is a model score, not a calibrated probability and never proof.
    """
    if not isinstance(logprobs, list):
        return None, "token_logprobs_unavailable"
    for candidates in logprobs:
        if not isinstance(candidates, dict):
            continue
        values: dict[str, float] = {}
        for candidate in candidates.values():
            token = getattr(candidate, "decoded_token", None) or getattr(candidate, "token", None)
            logprob = getattr(candidate, "logprob", None)
            if token is not None and logprob is not None and _normalise_token(str(token)) in {"yes", "no"}:
                values[_normalise_token(str(token))] = float(logprob)
        if set(values) == {"yes", "no"}:
            high = max(values.values())
            yes = math.exp(values["yes"] - high)
            no = math.exp(values["no"] - high)
            return yes / (yes + no), "returned_yes_no_logprob_softmax"
    return None, "yes_no_pair_not_in_returned_logprobs"


def make_output_dir(requested: str | None) -> Path:
    if requested:
        output_dir = Path(requested)
    else:
        stamp = datetime.now(UTC).strftime("%Y%m%dT%H%M%SZ")
        output_dir = Path("outputs") / "research_granite_guardian" / stamp
    if "research_granite_guardian" not in output_dir.as_posix():
        raise ValueError("output directory must be under a research_granite_guardian namespace")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


class GraniteLocalRunner:
    def __init__(self, model_path: Path, max_new_tokens: int, tensor_parallel_size: int,
                 backend: str, device_map: str) -> None:
        # Set before imports: accidental hub fallback must fail rather than download.
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        try:
            from transformers import AutoModelForCausalLM, AutoTokenizer
            import torch
        except ImportError as exc:
            raise RuntimeError("real execution needs installed transformers and torch") from exc
        self.tokenizer = AutoTokenizer.from_pretrained(
            str(model_path), local_files_only=True, trust_remote_code=False
        )
        self.backend = backend
        self.max_new_tokens = max_new_tokens
        self.torch = torch
        self.word_token_ids = {
            word: [token_id for token, token_id in self.tokenizer.get_vocab().items()
                   if _normalise_token(token) == word]
            for word in ("yes", "no")
        }
        if backend == "transformers":
            self.model = AutoModelForCausalLM.from_pretrained(
                str(model_path), local_files_only=True, trust_remote_code=False,
                torch_dtype="auto", device_map=device_map,
            )
            self.sampling_params = None
        elif backend == "vllm":
            try:
                from vllm import LLM, SamplingParams
            except ImportError as exc:
                raise RuntimeError("--backend vllm was requested, but vllm is not installed") from exc
            self.model = LLM(model=str(model_path), tensor_parallel_size=tensor_parallel_size)
            self.sampling_params = SamplingParams(temperature=0.0, logprobs=20, max_tokens=max_new_tokens)
        else:
            raise ValueError(f"unsupported backend: {backend}")

    def judge(
        self,
        criterion: str,
        prompt: BoundText,
        response: BoundText,
        tools: list[dict[str, Any]] | None,
    ) -> dict[str, Any]:
        if criterion == "groundedness":
            messages = [{"role": "assistant", "content": response.text}]
            chat = self.tokenizer.apply_chat_template(
                messages,
                guardian_config={"criteria_id": "groundedness"},
                documents=[{"doc_id": "prompt_context", "text": prompt.text}],
                think=False,
                tokenize=False,
                add_generation_prompt=True,
            )
        elif criterion == "function_call":
            if tools is None:
                return {
                    "status": "skipped_missing_tools",
                    "raw_model_output": None,
                    "risk_token": None,
                    "probabilistic_score": None,
                    "score_method": None,
                    "note": "function_call needs declared tools; none supplied via tools column or --tools-json",
                }
            messages = [
                {"role": "user", "content": prompt.text},
                {"role": "assistant", "content": response.text},
            ]
            chat = self.tokenizer.apply_chat_template(
                messages,
                guardian_config={"criteria_id": "function_call"},
                available_tools=tools,
                think=False,
                tokenize=False,
                add_generation_prompt=True,
            )
        else:
            raise ValueError(f"unsupported criterion: {criterion}")

        if self.backend == "transformers":
            model_inputs = self.tokenizer(chat, add_special_tokens=False, return_tensors="pt").to(self.model.device)
            input_token_count = int(model_inputs["input_ids"].shape[-1])
            with self.torch.inference_mode():
                generated = self.model.generate(
                    **model_inputs, do_sample=False, max_new_tokens=self.max_new_tokens,
                    return_dict_in_generate=True, output_scores=True,
                )
            completion_ids = generated.sequences[0, input_token_count:]
            raw = self.tokenizer.decode(completion_ids, skip_special_tokens=True).strip()
            score, method = self._transformers_score(generated.scores, completion_ids)
            output_token_count = int(completion_ids.shape[-1])
        else:
            tokenized = self.tokenizer(chat, add_special_tokens=False)
            input_ids = tokenized["input_ids"]
            input_token_count = len(input_ids[0]) if input_ids and isinstance(input_ids[0], list) else len(input_ids)
            generated = self.model.generate([chat], self.sampling_params, use_tqdm=False)[0].outputs[0]
            raw = generated.text.strip()
            score, method = probability_from_logprobs(getattr(generated, "logprobs", None))
            output_token_count = len(getattr(generated, "token_ids", ()) or ())
        return {
            "status": "ok" if parse_score(raw) else "unparseable_model_score",
            "raw_model_output": raw,
            "risk_token": parse_score(raw),
            "probabilistic_score": score,
            "score_method": method,
            "token_count": {
                "input": input_token_count,
                "output": output_token_count,
            },
            "note": "yes means the selected Granite criterion found risk; this score is not a formal certificate",
        }

    def _transformers_score(self, scores: Any, completion_ids: Any) -> tuple[float | None, str | None]:
        """Use logits at a generated yes/no token, when the tokenizer exposes both."""
        if not self.word_token_ids["yes"] or not self.word_token_ids["no"]:
            return None, "yes_no_tokens_not_single_vocab_tokens"
        for logits, token_id in zip(reversed(scores), reversed(completion_ids.tolist())):
            if _normalise_token(self.tokenizer.convert_ids_to_tokens(int(token_id))) not in {"yes", "no"}:
                continue
            row = logits[0]
            yes_logit = self.torch.logsumexp(row[self.word_token_ids["yes"]], dim=0)
            no_logit = self.torch.logsumexp(row[self.word_token_ids["no"]], dim=0)
            return float(self.torch.softmax(self.torch.stack((yes_logit, no_logit)), dim=0)[0].item()), \
                "generated_yes_no_token_logit_softmax"
        return None, "generated_score_did_not_contain_single_yes_no_token"


def run(args: argparse.Namespace) -> int:
    input_path = Path(args.input).resolve(strict=True)
    cases = read_cases(input_path)
    criteria = tuple(args.criteria)
    if any(item not in SUPPORTED_CRITERIA for item in criteria):
        raise ValueError(f"--criteria values must be in {SUPPORTED_CRITERIA}")
    output_dir = make_output_dir(args.output_dir)
    common_tools = read_tools_json(Path(args.tools_json).resolve(strict=True)) if args.tools_json else None
    config = {
        "runner": "offline_guardian/granite_guardian_3_3_8b",
        "model_id": MODEL_ID,
        "model_path": str(Path(args.model_path).resolve()) if args.model_path else None,
        "offline_only": True,
        "criteria": criteria,
        "think": False,
        "max_context_chars": args.max_context_chars,
        "max_new_tokens": args.max_new_tokens,
        "backend": args.backend,
        "device_map": args.device_map,
        "tensor_parallel_size": args.tensor_parallel_size,
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "case_count": len(cases),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "dry_run": args.dry_run,
    }
    (output_dir / "run_config.json").write_text(json.dumps(config, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")

    runner: GraniteLocalRunner | None = None
    if not args.dry_run:
        if not args.model_path:
            raise ValueError("--model-path is required unless --dry-run is used")
        model_path = Path(args.model_path).resolve(strict=True)
        if not model_path.is_dir():
            raise ValueError("--model-path must be an existing local model directory")
        runner = GraniteLocalRunner(
            model_path, args.max_new_tokens, args.tensor_parallel_size, args.backend, args.device_map
        )

    status_counts: dict[str, int] = {}
    with (output_dir / "records.jsonl").open("w", encoding="utf-8") as out:
        for case in cases:
            prompt, response = bound_pair(case["prompt"], case["response"], args.max_context_chars)
            try:
                tools = case_tools(case, common_tools)
            except (ValueError, json.JSONDecodeError) as exc:
                tools = None
                tool_error = str(exc)
            else:
                tool_error = None
            for criterion in criteria:
                started = time.perf_counter()
                if tool_error and criterion == "function_call":
                    result = {"status": "invalid_tools", "raw_model_output": None, "risk_token": None,
                              "probabilistic_score": None, "score_method": None, "note": tool_error}
                elif args.dry_run:
                    result = {"status": "dry_run", "raw_model_output": None, "risk_token": None,
                              "probabilistic_score": None, "score_method": None,
                              "note": "no model was loaded or downloaded"}
                else:
                    try:
                        assert runner is not None
                        result = runner.judge(criterion, prompt, response, tools)
                    except Exception as exc:  # preserve remaining cases for diagnosis
                        result = {"status": "runtime_error", "raw_model_output": None, "risk_token": None,
                                  "probabilistic_score": None, "score_method": None,
                                  "note": f"{type(exc).__name__}: {exc}"}
                record = {
                    "id": case["id"],
                    "criterion": criterion,
                    "formal_proof_status": "UNRESOLVED",
                    "model_decision_type": "probabilistic_guardian_score",
                    "latency_ms": round((time.perf_counter() - started) * 1000, 3),
                    "input_chars": {"prompt": prompt.original_chars, "response": response.original_chars},
                    "bounded_input_chars": {"prompt": prompt.kept_chars, "response": response.kept_chars},
                    "input_truncation": {
                        "applied": prompt.truncated or response.truncated,
                        "reason": [item for item in (prompt.reason, response.reason) if item],
                        "strategy": "head_tail_per_field",
                    },
                    **result,
                }
                status_counts[record["status"]] = status_counts.get(record["status"], 0) + 1
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
    summary = {"output_dir": str(output_dir), "records": sum(status_counts.values()), "status_counts": status_counts,
               "input_sha256": config["input_sha256"], "finished_at_utc": datetime.now(UTC).isoformat()}
    (output_dir / "summary.json").write_text(json.dumps(summary, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False))
    return 0


def parse_args(argv: Iterable[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", required=True, help="Fresh CSV with id,prompt,response columns")
    parser.add_argument("--model-path", help="Existing local Granite model directory; model IDs are rejected")
    parser.add_argument("--output-dir", help="Must be inside a research_granite_guardian namespace")
    parser.add_argument("--tools-json", help="Optional local JSON list of declared function-call tools")
    parser.add_argument("--criteria", nargs="+", choices=SUPPORTED_CRITERIA, default=["groundedness"])
    parser.add_argument("--max-context-chars", type=int, default=12000)
    parser.add_argument("--max-new-tokens", type=int, default=16)
    parser.add_argument("--backend", choices=("transformers", "vllm"), default="transformers",
                        help="transformers is default; vllm is used only when already installed")
    parser.add_argument("--device-map", default="auto", help="Transformers device_map, default: auto")
    parser.add_argument("--tensor-parallel-size", type=int, default=1)
    parser.add_argument("--dry-run", action="store_true", help="Validate input/output contract without loading a model")
    args = parser.parse_args(argv)
    if args.max_context_chars < 2 or args.max_new_tokens < 1 or args.tensor_parallel_size < 1:
        parser.error("context, generation, and tensor-parallel limits must be positive")
    return args


if __name__ == "__main__":
    try:
        raise SystemExit(run(parse_args()))
    except (OSError, ValueError, RuntimeError) as exc:
        print(f"offline_guardian: {exc}", file=sys.stderr)
        raise SystemExit(2)
