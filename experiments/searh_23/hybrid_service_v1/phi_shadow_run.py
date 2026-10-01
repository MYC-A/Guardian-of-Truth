"""Gold-blind bounded formal frontend on the fresh cases.

Reuses the repository's ORIGINAL formal_translation prompt and signed Horn
solver. Translation remains a model hypothesis; an exact citation certifies
only provenance. No solver relation is promoted to a Guardian verdict here.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]
sys.path[:0] = [str(ROOT / "src"),
                str(ROOT / "experiments/searh_23/three_architectures")]

from guardian_truth.formal_reasoning import evaluate_formalization, FORMAL_SCHEMA  # noqa: E402
from guardian_truth.formal_translation import (  # noqa: E402
    FORMAL_INSTRUCTION, build_formal_messages)
from llm import DEFAULT_MISTRAL_MODEL, chat, extract_json  # noqa: E402
from structural_v02 import parse_case_v02  # noqa: E402
from candidate_bank import BANK  # noqa: E402

DATA = HERE / "dataset/fresh_v1"
RESULTS = Path("/workspace/guardian/results/hybrid_phi_shadow")
QUERY_INSTRUCTION = (
    "The target is an assertion to test, NOT a fact. For a tool action the "
    "query must represent whether that action is permitted now with these "
    "arguments, not whether its call text exists. For a factual answer the "
    "query is the asserted world fact, not that the assistant uttered it. "
    "Do not add the query as a fact from the target source. No absence-as-false. "
    "If the source cannot be represented in this fragment, return UNSUPPORTED."
)


def formal_messages(target, evidence):
    messages = build_formal_messages(target, evidence)
    messages[0]["content"] += "\n" + QUERY_INSTRUCTION + "\nJSON SCHEMA:\n" + json.dumps(
        FORMAL_SCHEMA, sort_keys=True)
    return messages


def _sha(blob: bytes) -> str:
    return hashlib.sha256(blob).hexdigest()


def _write(path: Path, value):
    temp = path.with_suffix(path.suffix + ".tmp")
    temp.write_text(json.dumps(value, ensure_ascii=False, sort_keys=True) + "\n",
                    encoding="utf-8")
    os.replace(temp, path)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _evidence(ctx):
    # The complete original prompt is preserved as one source. Extracted
    # policy is supplied separately but does not replace the original.
    return [{"id": "prompt", "text": ctx.prompt_raw},
            {"id": "target", "text": ctx.response_raw}]


def run(split: str, *, max_cases=None, max_calls=90,
        max_tokens=400000, max_minutes=120, model=None, case_ids=None,
        output_root=RESULTS):
    model = model or DEFAULT_MISTRAL_MODEL
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    source = DATA / f"{split}_input.jsonl"
    digest = _sha(source.read_bytes())
    if digest != manifest["splits"][split]["input_sha256"]:
        raise ValueError("frozen input hash mismatch")
    rows = [json.loads(line) for line in source.read_text(encoding="utf-8").splitlines()]
    if case_ids is not None:
        if max_cases is not None:
            raise ValueError("case IDs and max_cases are mutually exclusive")
        by_id = {r["id"]: r for r in rows}
        if not case_ids or len(set(case_ids)) != len(case_ids) or any(
                cid not in by_id for cid in case_ids):
            raise ValueError("invalid frozen case selection")
        rows = [by_id[cid] for cid in case_ids]
    elif max_cases is not None:
        rows = rows[:max_cases]
    bank_path = BANK / f"{split}.jsonl"
    bank_manifest = json.loads((BANK / "manifest.json").read_text(encoding="utf-8"))
    bank_sha = _sha(bank_path.read_bytes())
    if bank_sha != bank_manifest["splits"][split]["sha256"]:
        raise ValueError("candidate bank hash mismatch")
    candidates = {r["id"]: r for r in map(json.loads,
        bank_path.read_text(encoding="utf-8").splitlines())}
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    if subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip():
        raise ValueError("formal run requires clean, pinned checkout")
    identity = {"schema": "phi-shadow/3", "split": split,
                "input_sha256": digest, "case_ids": [r["id"] for r in rows],
                "commit": commit, "model": model,
                "candidate_bank_sha256": bank_sha,
                "prompt_sha256": _sha((FORMAL_INSTRUCTION + QUERY_INSTRUCTION +
                    json.dumps(FORMAL_SCHEMA, sort_keys=True)).encode("utf-8")),
                "backend": "guardian_truth.formal_reasoning.signed_horn"}
    run_id = _sha(json.dumps(identity, sort_keys=True).encode("utf-8"))[:20]
    folder = output_root / run_id
    folder.mkdir(parents=True, exist_ok=True)
    config_file = folder / "run_config.json"
    if config_file.exists():
        if json.loads(config_file.read_text(encoding="utf-8")) != identity:
            raise ValueError("run identity collision")
    else:
        _write(config_file, identity)
    journal = folder / "results.jsonl"
    prior = {}
    if journal.exists():
        for line in journal.read_text(encoding="utf-8").splitlines():
            record = json.loads(line)
            if record["run_id"] != run_id or record["id"] in prior:
                raise ValueError("journal identity or duplicate failure")
            prior[record["id"]] = record
    began = time.monotonic()
    calls = sum(r["usage"]["calls"] for r in prior.values())
    tokens = sum(r["usage"]["tokens"] for r in prior.values())

    def status(state, reason=""):
        _write(folder / "status.json", {"state": state, "reason": reason,
            "run_id": run_id, "pid": os.getpid(), "completed": len(prior),
            "total": len(rows), "calls": calls, "tokens": tokens,
            "last_progress_at": _utc()})

    _write(folder / "launch_receipt.json", {"run_id": run_id,
        "pid": os.getpid(), "started_at": _utc(), "config": identity,
        "budgets": {"max_calls": max_calls, "max_tokens": max_tokens,
                    "max_minutes": max_minutes}})
    status("RUNNING")
    try:
        for row in rows:
            if row["id"] in prior:
                continue
            if (calls >= max_calls or tokens >= max_tokens or
                    (time.monotonic() - began) / 60 >= max_minutes):
                status("BUDGET_STOP", "call/token/time budget")
                return folder
            ctx = parse_case_v02(row["id"], row["prompt"], row["response"])
            evidence = _evidence(ctx)
            messages = formal_messages(candidates[row["id"]]["claim"], evidence)
            t0 = time.monotonic()
            answer = chat(model, messages,
                          max_tokens=4000, temperature=0,
                          json_mode=True, transport_retries=1,
                          caller="hybrid/phi-shadow")
            calls += 1
            usage = answer.get("usage") or {}
            tokens += int(usage.get("total_tokens") or 0)
            parsed = extract_json(answer.get("content"))
            raw = json.dumps(parsed, ensure_ascii=False) if parsed is not None else ""
            try:
                result = evaluate_formalization(raw, evidence)
                relation, reason = result.relation, result.reason
                proof = [{"literal": {"atom_id": step.literal.atom_id,
                                      "polarity": step.literal.polarity},
                          "rule_id": step.rule_id,
                          "sources": [{"source_id": s.source_id,
                                       "quote": s.quote} for s in step.sources]}
                         for step in result.proof]
                outcome = "VALID"
            except Exception as exc:  # noqa: BLE001
                relation, reason, proof = "INSUFFICIENT", getattr(
                    exc, "category", type(exc).__name__), []
                outcome = "INVALID"
            record = {"run_id": run_id, "id": row["id"], "status": outcome,
                      "source_sha256": _sha((row["prompt"] + "\x00" +
                                             row["response"]).encode("utf-8")),
                      "relation": relation, "reason": reason,
                      "scope": "relative_to_supplied_formalization",
                      "proof": proof, "translation": parsed,
                      "cached": bool(answer.get("cached")),
                      "transport_failed": bool(answer.get("error")),
                      "error_type": answer.get("error_type"),
                      "http_status": answer.get("http_status"),
                      "response_model": answer.get("model"),
                      "raw_content": (answer.get("content") or "")[:24000],
                      "usage": {"calls": 1,
                                "tokens": int(usage.get("total_tokens") or 0),
                                "prompt_tokens": int(usage.get("prompt_tokens") or 0),
                                "completion_tokens": int(usage.get("completion_tokens") or 0)},
                      "elapsed_s": round(time.monotonic() - t0, 3)}
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(record, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            prior[row["id"]] = record
            status("RUNNING")
        _write(folder / "summary.json", {"run_id": run_id, "state": "SUCCEEDED",
            "n": len(rows), "valid": sum(r["status"] == "VALID" for r in prior.values()),
            "relations": {name: sum(r["relation"] == name for r in prior.values())
                          for name in ("FOLLOWS", "CONTRADICTS", "INSUFFICIENT")},
            "calls": calls, "tokens": tokens, "finished_at": _utc()})
        status("SUCCEEDED")
        return folder
    except BaseException as exc:
        status("FAILED", f"{type(exc).__name__}:{str(exc)[:160]}")
        raise


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--split", choices=("dev", "sealed"), required=True)
    parser.add_argument("--max-cases", type=int)
    parser.add_argument("--model", help="Registry ID or explicit provider/model")
    parser.add_argument("--case-ids-file", type=Path,
                        help="Frozen JSON array of IDs; never contains labels")
    parser.add_argument("--output-root", type=Path, default=RESULTS)
    parser.add_argument("--max-calls", type=int, default=90)
    parser.add_argument("--max-tokens", type=int, default=400000)
    parser.add_argument("--max-minutes", type=float, default=120)
    args = parser.parse_args()
    if min(args.max_calls, args.max_tokens, args.max_minutes) <= 0:
        parser.error("budgets must be positive")
    ids = None if args.case_ids_file is None else json.loads(
        args.case_ids_file.read_text(encoding="utf-8"))
    folder = run(args.split, max_cases=args.max_cases,
        max_calls=args.max_calls, max_tokens=args.max_tokens,
        max_minutes=args.max_minutes, model=args.model, case_ids=ids,
        output_root=args.output_root)
    print(json.dumps({"directory": str(folder),
        "status": json.loads((folder / "status.json").read_text())}))
