"""Pinned native checker pass on an identical, gold-blind candidate bank.

Runs one local checkpoint per process so a 24 GiB GPU never holds two heavy
models simultaneously. Scores are native support/risk, not service verdicts.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

from candidate_bank import BANK
from factcg_native import native_score
from smoke_native_adapters import GUARDIAN_JUDGE_NOTHINK

ROOT = Path(__file__).resolve().parents[3]
RESULTS = Path("/workspace/guardian/results/hybrid_specialists")
REVISIONS = {
    "factcg": "0430e3509dbd28d2dff7a117c0eae25359ff3e80",
    "minicheck": "96eafd01cee2d16cf81aaa2fb226b14f422a37b3",
    "granite": "/workspace/guardian/models/granite-guardian-4.1-8b",
}


def _sha(blob):
    return hashlib.sha256(blob).hexdigest()


def _write(path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True),
                   encoding="utf-8")
    os.replace(tmp, path)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def load_checker(name):
    import torch
    from transformers import (AutoConfig, AutoModelForCausalLM,
                              AutoModelForSeq2SeqLM,
                              AutoModelForSequenceClassification,
                              AutoTokenizer)

    device = torch.device("cuda" if torch.cuda.is_available() else "cpu")
    if name == "factcg":
        repo = "yaxili96/FactCG-DeBERTa-v3-Large"
        revision = REVISIONS[name]
        config = AutoConfig.from_pretrained(repo, revision=revision,
                                           num_labels=2,
                                           finetuning_task="text-classification")
        config.problem_type = "single_label_classification"
        tok = AutoTokenizer.from_pretrained(repo, revision=revision,
                                            use_fast=True)
        model = AutoModelForSequenceClassification.from_pretrained(
            repo, config=config, revision=revision,
            ignore_mismatched_sizes=False).to(device).eval()

        def score(doc, claim):
            return {"support_score": native_score(model, tok, doc, claim,
                                                   device), "native_output": None}

    elif name == "minicheck":
        repo = "lytang/MiniCheck-Flan-T5-Large"
        revision = REVISIONS[name]
        tok = AutoTokenizer.from_pretrained(repo, revision=revision)
        model = AutoModelForSeq2SeqLM.from_pretrained(
            repo, revision=revision).to(device).eval()

        def score(doc, claim):
            text = "predict: " + tok.eos_token.join([doc, claim])
            enc = tok([text], max_length=2048, truncation=True,
                      padding=True, return_tensors="pt").to(device)
            dec = torch.zeros((1, 1), dtype=torch.long).to(device)
            with torch.inference_mode():
                logits = model(input_ids=enc["input_ids"],
                               attention_mask=enc["attention_mask"],
                               decoder_input_ids=dec).logits.squeeze(1)
            probability = torch.softmax(logits[:, [3, 209]], dim=-1)[0, 1]
            return {"support_score": float(probability.item()),
                    "native_output": None}

    elif name == "granite":
        path = REVISIONS[name]
        tok = AutoTokenizer.from_pretrained(path, local_files_only=True)
        model = AutoModelForCausalLM.from_pretrained(
            path, local_files_only=True, torch_dtype="auto",
            device_map="auto").eval()

        def score(doc, claim):
            criterion = ("The current assistant statement or proposed action "
                         "is erroneous if it is unsupported by or contradicts "
                         "the provided document, including its policy, history, "
                         "tool catalog and observations. Assess this specific "
                         "claim about the latest move.")
            schema = ("Return yes if the statement violates the criterion; "
                      "otherwise no.")
            block = (f"{GUARDIAN_JUDGE_NOTHINK}\n\n### Criteria: {criterion}"
                     f"\n\n### Scoring Schema: {schema}")
            chat = tok.apply_chat_template(
                [{"role": "assistant", "content": claim},
                 {"role": "user", "content": block}], tokenize=False,
                add_generation_prompt=True,
                documents=[{"doc_id": "source", "text": doc}])
            enc = tok(chat, add_special_tokens=False,
                      return_tensors="pt").to(model.device)
            with torch.inference_mode():
                generated = model.generate(**enc, do_sample=False,
                                           max_new_tokens=16,
                                           pad_token_id=tok.eos_token_id)
            raw = tok.decode(generated[0][enc["input_ids"].shape[1]:],
                             skip_special_tokens=False)
            match = re.search(r"<score>\s*(yes|no)\s*</score>", raw, re.I)
            if not match:
                return {"support_score": None, "native_output": raw[:120]}
            return {"support_score": 0.0 if match.group(1).lower() == "yes"
                    else 1.0, "native_output": raw[:120]}

    else:
        raise ValueError(name)
    return score, device


def run(model_name, split, max_cases=None, max_minutes=90):
    import torch

    source = BANK / f"{split}.jsonl"
    manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
    if _sha(source.read_bytes()) != manifest["splits"][split]["sha256"]:
        raise ValueError("candidate bank hash mismatch")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if max_cases is not None:
        rows = rows[:max_cases]
    if max_minutes <= 0:
        raise ValueError("max_minutes must be positive")
    if any(len(row["document"].split()) > 500 for row in rows):
        raise ValueError("candidate document exceeds native MiniCheck short-document scope")
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()
    if dirty:
        raise ValueError("specialist run requires clean, pinned checkout")
    spec = {"schema": "specialist-run/1", "model": model_name,
            "revision": REVISIONS[model_name], "split": split,
            "bank_sha256": manifest["splits"][split]["sha256"],
            "case_ids": [row["id"] for row in rows], "commit": commit,
            "threshold": 0.5}
    run_id = _sha(json.dumps(spec, sort_keys=True).encode("utf-8"))[:20]
    out = RESULTS / run_id
    out.mkdir(parents=True, exist_ok=True)
    _write(out / "run_config.json", spec)
    journal = out / "scores.jsonl"
    previous = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            rec = json.loads(line)
            if rec["run_id"] != run_id:
                raise ValueError("journal identity mismatch")
            if rec["id"] in previous:
                raise ValueError("duplicate score")
            previous[rec["id"]] = rec

    def status(state, reason=""):
        _write(out / "status.json", {"run_id": run_id, "state": state,
              "reason": reason, "completed": len(previous), "total": len(rows),
              "pid": os.getpid(), "last_progress_at": _utc()})

    status("RUNNING")
    if len(previous) == len(rows):
        status("SUCCEEDED")
        return out
    began = time.monotonic()
    try:
        score_fn, device = load_checker(model_name)
        for row in rows:
            if row["id"] in previous:
                continue
            if (time.monotonic() - began) / 60 >= max_minutes:
                status("BUDGET_STOP", "wall_time_limit")
                return out
            t0 = time.monotonic()
            try:
                result = score_fn(row["document"], row["claim"])
                rec_status = "VALID" if result["support_score"] is not None else "INVALID"
                error = None
            except Exception as exc:  # noqa: BLE001
                result = {"support_score": None, "native_output": None}
                rec_status, error = "INVALID", f"{type(exc).__name__}:{str(exc)[:160]}"
            rec = {"run_id": run_id, "id": row["id"],
                   "claim_kind": row["claim_kind"],
                   "status": rec_status, "error": error, **result,
                   "elapsed_s": round(time.monotonic() - t0, 3)}
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            previous[row["id"]] = rec
            status("RUNNING")
        summary = {"run_id": run_id, "model": model_name, "split": split,
                   "n": len(rows), "valid": sum(r["status"] == "VALID"
                                               for r in previous.values()),
                   "elapsed_s": round(time.monotonic() - began, 2),
                   "peak_vram_gb": round(torch.cuda.max_memory_allocated() / 2**30, 2)
                   if torch.cuda.is_available() else None,
                   "device": str(device), "finished_at": _utc()}
        _write(out / "summary.json", summary)
        status("SUCCEEDED")
        return out
    except BaseException as exc:
        status("FAILED", f"{type(exc).__name__}:{str(exc)[:160]}")
        raise


if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--model", choices=tuple(REVISIONS), required=True)
    p.add_argument("--split", choices=("dev", "sealed"), required=True)
    p.add_argument("--max-cases", type=int)
    p.add_argument("--max-minutes", type=float, default=90)
    args = p.parse_args()
    directory = run(args.model, args.split, args.max_cases, args.max_minutes)
    print(json.dumps({"directory": str(directory),
                      "status": json.loads((directory / "status.json").read_text()),
                      "summary": json.loads((directory / "summary.json").read_text())
                      if (directory / "summary.json").exists() else None},
                     ensure_ascii=False), flush=True)
