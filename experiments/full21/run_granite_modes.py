#!/usr/bin/env python3
"""FULL_21 Section 3: Granite Guardian 3.3-8B modes & context experiment runner.

Extends the flash control runner (experiments/full21/run_granite_guardian_flash.py,
identical per-case contract) with:
  * all officially supported criteria_ids from the checkpoint chat template
    (groundedness, answer_relevance, context_relevance, evasiveness,
    function_call, social_bias, jailbreak, profanity, sexual_content,
    unethical_behavior, violence, harm, harm_engagement)
  * --think flag (checkpoint judge{think} template branch)
  * --context-mode doc|conv:
      doc  = flash control contract: messages=[assistant: response],
             documents=[{prompt_context: bounded prompt}]
      conv = messages=[user: last ⟦USER⟧ turn of prompt, assistant: response]
             (documents omitted; last-user-turn extraction is recorded)
  * --variants: several configs in ONE process (single model load)

Everything else (bounding head_tail_per_field, budget split 2/5 prompt +
3/5 response, temperature 0, score parsing last <score> yes/no, records
schema, output namespace rules) is byte-compatible with the control runner.
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
BANK_CRITERIA = (
    "groundedness", "answer_relevance", "context_relevance", "evasiveness",
    "function_call", "social_bias", "jailbreak", "profanity",
    "sexual_content", "unethical_behavior", "violence", "harm", "harm_engagement",
)
SCORE_RE = re.compile(r"<score>\s*(yes|no)\s*</score>", re.IGNORECASE | re.DOTALL)
USER_TURN_RE = re.compile(r"⟦USER(?:[^⟧]*)⟧")


@dataclass(frozen=True)
class BoundText:
    text: str
    original_chars: int
    kept_chars: int
    truncated: bool
    reason: str | None


def bounded_text(text: str, limit: int, field: str) -> BoundText:
    if len(text) <= limit:
        return BoundText(text, len(text), len(text), False, None)
    marker = "\n\n[... omitted by offline_guardian context bound ...]\n\n"
    if limit <= len(marker):
        kept = text[:limit]
        return BoundText(kept, len(text), len(kept), True,
                         f"{field}_exceeds_max_context_chars:{len(text)}>{limit}; marker did not fit")
    remaining = limit - len(marker)
    head = remaining // 2
    tail = remaining - head
    kept = text[:head] + marker + text[-tail:]
    return BoundText(kept, len(text), len(kept), True,
                     f"{field}_exceeds_max_context_chars:{len(text)}>{limit}; kept head and tail")


def bound_pair(prompt: str, response: str, max_context_chars: int) -> tuple[BoundText, BoundText]:
    prompt_limit = max(1, max_context_chars * 2 // 5)
    response_limit = max(1, max_context_chars - prompt_limit)
    return (bounded_text(prompt, prompt_limit, "prompt"),
            bounded_text(response, response_limit, "response"))


def last_user_turn(prompt: str) -> tuple[str, bool]:
    """Extract the last ⟦USER⟧ block from the raw prompt blob."""
    matches = list(USER_TURN_RE.finditer(prompt))
    if not matches:
        return prompt, False
    start = matches[-1].end()
    nxt = USER_TURN_RE.search(prompt, start)
    # also stop at ASSISTANT/SYSTEM markers after the last user turn
    tail_stop = re.compile(r"⟦(?:ASSISTANT|SYSTEM)(?:[^⟧]*)⟧").search(prompt, start)
    ends = [m.start() for m in (nxt, tail_stop) if m]
    end = min(ends) if ends else len(prompt)
    return prompt[start:end].strip(), True


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def read_cases(path: Path) -> list[dict[str, str]]:
    csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
    with path.open("r", encoding="utf-8-sig", newline="") as handle:
        reader = csv.DictReader(handle)
        missing = {"id", "prompt", "response"} - set(reader.fieldnames or ())
        if missing:
            raise ValueError(f"input CSV misses required columns: {', '.join(sorted(missing))}")
        cases, seen = [], set()
        for line_no, row in enumerate(reader, start=2):
            case_id = (row.get("id") or "").strip()
            if not case_id:
                raise ValueError(f"empty id at line {line_no}")
            if case_id in seen:
                raise ValueError(f"duplicate id {case_id!r} at line {line_no}")
            seen.add(case_id)
            cases.append({"id": case_id, "prompt": row.get("prompt") or "",
                          "response": row.get("response") or "",
                          "tools": row.get("tools") or ""})
    return cases


def parse_score(text: str) -> str | None:
    matches = SCORE_RE.findall(text)
    return matches[-1].lower() if matches else None


def _normalise_token(token: str) -> str:
    return token.strip().lower().replace("▁", "").replace("Ġ", "")


def probability_from_logprobs(logprobs: Any) -> tuple[float | None, str | None]:
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


def make_output_dir(requested: str) -> Path:
    output_dir = Path(requested)
    if "research_granite_guardian" not in output_dir.as_posix():
        raise ValueError("output directory must be under a research_granite_guardian namespace")
    if output_dir.exists() and any(output_dir.iterdir()):
        raise ValueError(f"refusing to overwrite non-empty output directory: {output_dir}")
    output_dir.mkdir(parents=True, exist_ok=True)
    return output_dir


class GraniteLocalRunner:
    def __init__(self, model_path: Path, backend: str = "transformers", device_map: str = "auto"):
        os.environ["HF_HUB_OFFLINE"] = "1"
        os.environ["TRANSFORMERS_OFFLINE"] = "1"
        from transformers import AutoModelForCausalLM, AutoTokenizer
        import torch
        self.tokenizer = AutoTokenizer.from_pretrained(str(model_path), local_files_only=True,
                                                        trust_remote_code=False)
        self.backend = backend
        self.torch = torch
        if backend == "transformers":
            self.model = AutoModelForCausalLM.from_pretrained(
                str(model_path), local_files_only=True, trust_remote_code=False,
                torch_dtype="auto", device_map=device_map)
        else:
            raise ValueError(f"unsupported backend: {backend}")

    def build_chat(self, criterion: str, prompt_b: BoundText, response_b: BoundText,
                   context_mode: str, think: bool, conv_user: str | None) -> str:
        if context_mode == "doc":
            messages = [{"role": "assistant", "content": response_b.text}]
            chat = self.tokenizer.apply_chat_template(
                messages, guardian_config={"criteria_id": criterion},
                documents=[{"doc_id": "prompt_context", "text": prompt_b.text}],
                think=think, tokenize=False, add_generation_prompt=True)
        elif context_mode == "conv":
            messages = [
                {"role": "user", "content": (conv_user if conv_user is not None else prompt_b.text)},
                {"role": "assistant", "content": response_b.text},
            ]
            chat = self.tokenizer.apply_chat_template(
                messages, guardian_config={"criteria_id": criterion},
                think=think, tokenize=False, add_generation_prompt=True)
        elif context_mode == "query_doc":
            messages = [
                {"role": "user", "content": (conv_user if conv_user is not None else prompt_b.text)},
            ]
            chat = self.tokenizer.apply_chat_template(
                messages, guardian_config={"criteria_id": criterion},
                documents=[{"doc_id": "prompt_context", "text": prompt_b.text}],
                think=think, tokenize=False, add_generation_prompt=True)
        else:
            raise ValueError(f"unsupported context mode: {context_mode}")
        return chat

    def generate(self, chat: str, max_new_tokens: int) -> dict[str, Any]:
        model_inputs = self.tokenizer(chat, add_special_tokens=False, return_tensors="pt").to(self.model.device)
        input_token_count = int(model_inputs["input_ids"].shape[-1])
        with self.torch.inference_mode():
            generated = self.model.generate(
                **model_inputs, do_sample=False, max_new_tokens=max_new_tokens,
                return_dict_in_generate=True, output_scores=True)
        new_tokens = generated.sequences[0][model_inputs["input_ids"].shape[-1]:]
        text = self.tokenizer.decode(new_tokens, skip_special_tokens=True)
        logprobs = []
        if getattr(generated, "scores", None) is not None:
            for step_scores in generated.scores:
                top = step_scores[0].topk(min(20, step_scores.shape[-1]))
                import torch as _t
                entry = {}
                for lp, tid in zip(top.values.tolist(), top.indices.tolist()):
                    tok = self.tokenizer.decode([tid])
                    entry[str(len(entry))] = {"token": tok, "logprob": lp,
                                              "decoded_token": tok}
                logprobs.append(entry)
        prob, method = probability_from_logprobs(logprobs)
        return {"text": text, "input_token_count": input_token_count,
                "probabilistic_score": prob, "score_method": method}


def run_variant(runner: GraniteLocalRunner, cases: list[dict], variant: dict, input_path: Path) -> dict:
    out_dir = make_output_dir(variant["output_dir"])
    criterion = variant["criterion"]
    think = bool(variant.get("think", False))
    context_mode = variant.get("context_mode", "doc")
    max_context = int(variant.get("max_context_chars", 12000))
    max_new = int(variant.get("max_new_tokens", 16))
    run_config = {
        "runner": "full21/run_granite_modes",
        "model_id": MODEL_ID,
        "model_path": str(variant["model_path"]),
        "offline_only": True,
        "criteria": [criterion],
        "think": think,
        "context_mode": context_mode,
        "max_context_chars": max_context,
        "max_new_tokens": max_new,
        "backend": "transformers",
        "device_map": "auto",
        "input_path": str(input_path),
        "input_sha256": sha256_file(input_path),
        "case_count": len(cases),
        "started_at_utc": datetime.now(UTC).isoformat(),
        "dry_run": False,
        "variant_name": variant.get("name", criterion),
    }
    (out_dir / "run_config.json").write_text(json.dumps(run_config, indent=1), encoding="utf-8")

    records = []
    counts: dict[str, int] = {}
    for case in cases:
        t0 = time.perf_counter()
        prompt, response = case["prompt"], case["response"]
        prompt_b, response_b = bound_pair(prompt, response, max_context)
        conv_user, user_found = (None, None)
        if context_mode in ("conv", "query_doc"):
            conv_user_raw, user_found = last_user_turn(prompt)
            # bound the conv user turn with the same prompt budget for comparability
            conv_user_b = bounded_text(conv_user_raw, max(1, max_context * 2 // 5), "conv_user")
            conv_user = conv_user_b.text
        chat = runner.build_chat(criterion, prompt_b, response_b, context_mode, think, conv_user)
        gen = runner.generate(chat, max_new)
        latency_ms = (time.perf_counter() - t0) * 1000.0
        risk = parse_score(gen["text"])
        status = "ok" if risk is not None else "no_score_token"
        rec = {
            "id": case["id"],
            "criterion": criterion,
            "think": think,
            "context_mode": context_mode,
            "formal_proof_status": "UNRESOLVED",
            "model_decision_type": "probabilistic_guardian_score",
            "latency_ms": round(latency_ms, 3),
            "input_chars": {"prompt": len(prompt), "response": len(response)},
            "bounded_input_chars": {"prompt": prompt_b.kept_chars, "response": response_b.kept_chars},
            "input_truncation": {"applied": prompt_b.truncated or response_b.truncated,
                                 "reason": [r for r in (prompt_b.reason, response_b.reason) if r],
                                 "strategy": "head_tail_per_field"},
            "conv_user_found": user_found,
            "input_token_count": gen["input_token_count"],
            "status": status,
            "raw_model_output": gen["text"],
            "risk_token": risk,
            "probabilistic_score": gen["probabilistic_score"],
            "score_method": gen["score_method"],
        }
        records.append(rec)
        counts[status] = counts.get(status, 0) + 1
    with (out_dir / "records.jsonl").open("w", encoding="utf-8") as f:
        for rec in records:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
    summary = {"output_dir": str(out_dir), "records": len(records), "status_counts": counts,
               "input_sha256": run_config["input_sha256"],
               "finished_at_utc": datetime.now(UTC).isoformat()}
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=1), encoding="utf-8")
    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--input", required=True)
    ap.add_argument("--model-path", required=True)
    ap.add_argument("--variants", required=True,
                    help="JSON file: list of {name, criterion, think, context_mode, max_context_chars, max_new_tokens, output_dir}")
    args = ap.parse_args()

    variants = json.loads(Path(args.variants).read_text(encoding="utf-8"))
    cases = read_cases(Path(args.input))
    runner = GraniteLocalRunner(Path(args.model_path))
    results = []
    for v in variants:
        v.setdefault("model_path", args.model_path)
        print(f"[variant {v.get('name')}] criterion={v['criterion']} think={v.get('think', False)} "
              f"mode={v.get('context_mode', 'doc')} ctx={v.get('max_context_chars', 12000)}", flush=True)
        s = run_variant(runner, cases, v, Path(args.input))
        print(f"[variant {v.get('name')}] -> {json.dumps(s)}", flush=True)
        results.append(s)
    print(json.dumps({"variants": results}, ensure_ascii=False, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
