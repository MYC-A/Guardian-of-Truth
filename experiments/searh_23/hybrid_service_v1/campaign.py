"""Resource-bounded, resumable service-arm campaign with immutable inputs.

Gold is never read by this runner. Each completed case/config pair is journaled
atomically before progress advances; stale/changed hashes create a new run ID.
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
sys.path.insert(0, str(ROOT / "service"))
from runtime import GuardianServiceRuntime, load_config  # noqa: E402

DATA = HERE / "dataset" / "fresh_v1"
DEFAULT_ROOT = Path("/workspace/guardian/results/hybrid_campaigns")
ARMS = ("g0-direct", "g1-ge", "g2-gp-surface",
        "g3-ge-gp-surface", "gplain-evidence")


def _sha(value: bytes) -> str:
    return hashlib.sha256(value).hexdigest()


def _json_bytes(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True,
                      separators=(",", ":")).encode("utf-8")


def _write_atomic(path: Path, value):
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(_json_bytes(value) + b"\n")
    os.replace(tmp, path)


def _utc():
    return datetime.now(timezone.utc).isoformat()


def _load_cases(split: str):
    manifest = json.loads((DATA / "manifest.json").read_text(encoding="utf-8"))
    file = DATA / f"{split}_input.jsonl"
    fingerprint = _sha(file.read_bytes())
    if fingerprint != manifest["splits"][split]["input_sha256"]:
        raise ValueError("frozen input hash mismatch")
    rows = [json.loads(line) for line in file.read_text(encoding="utf-8").splitlines()]
    if len(rows) != manifest["splits"][split]["n"]:
        raise ValueError("frozen input count mismatch")
    return rows, fingerprint


def _completed(journal: Path, run_id: str):
    out = {}
    if not journal.exists():
        return out
    for number, line in enumerate(journal.read_text(encoding="utf-8").splitlines(), 1):
        try:
            rec = json.loads(line)
        except json.JSONDecodeError as exc:
            raise ValueError(f"journal line {number} corrupt") from exc
        if rec.get("run_id") != run_id:
            raise ValueError("journal run ID mismatch")
        key = (rec.get("config_id"), rec.get("case_id"))
        if key in out:
            raise ValueError(f"duplicate journal key {key}")
        if rec.get("status") == "COMPLETED":
            out[key] = rec
    return out


def run(split: str, arms: tuple[str, ...], *, max_calls: int,
        max_tokens: int, max_minutes: float, output_root: Path,
        max_cases: int | None = None):
    cases, input_sha = _load_cases(split)
    if max_cases is not None:
        cases = cases[:max_cases]
    configs = {arm: load_config(arm) for arm in arms}
    config_shas = {arm: _sha(_json_bytes(configs[arm])) for arm in arms}
    commit = subprocess.check_output(
        ["git", "-C", str(ROOT), "rev-parse", "HEAD"], text=True).strip()
    dirty = subprocess.check_output(
        ["git", "-C", str(ROOT), "status", "--porcelain"], text=True).strip()
    if dirty:
        raise ValueError("campaign requires a clean, pinned checkout")
    identity = {"schema": "hybrid-campaign/1", "split": split,
                "input_sha256": input_sha, "commit": commit,
                "config_sha256": config_shas,
                "case_ids": [case["id"] for case in cases]}
    run_id = _sha(_json_bytes(identity))[:20]
    directory = output_root / run_id
    directory.mkdir(parents=True, exist_ok=True)
    config_file = directory / "run_config.json"
    if config_file.exists():
        if json.loads(config_file.read_text(encoding="utf-8")) != identity:
            raise ValueError("existing run configuration differs")
    else:
        _write_atomic(config_file, identity)
    journal = directory / "results.jsonl"
    completed = _completed(journal, run_id)
    planned = [(arm, case) for arm in arms for case in cases]
    start = time.monotonic()
    calls = sum(int((r.get("usage") or {}).get("calls") or 0)
                for r in completed.values())
    tokens = sum(int((r.get("usage") or {}).get("tokens") or 0)
                 for r in completed.values())
    status_path = directory / "status.json"
    receipt = {"run_id": run_id, "pid": os.getpid(), "started_at": _utc(),
               "split": split, "commit": commit, "input_sha256": input_sha,
               "config_sha256": config_shas, "planned": len(planned),
               "budgets": {"max_calls": max_calls, "max_tokens": max_tokens,
                           "max_minutes": max_minutes}}
    _write_atomic(directory / "launch_receipt.json", receipt)
    runtimes = {arm: GuardianServiceRuntime(arm,
                audit_path=directory / f"audit_{arm}.jsonl") for arm in arms}

    def write_status(state, reason=""):
        _write_atomic(status_path, {
            "run_id": run_id, "state": state, "reason": reason,
            "completed": len(completed), "total": len(planned),
            "calls": calls, "tokens": tokens,
            "invalid_or_unknown": sum(
                r.get("decision") == "UNKNOWN" for r in completed.values()),
            "last_progress_at": _utc(), "pid": os.getpid()})

    write_status("RUNNING")
    try:
        for arm, case in planned:
            key = (arm, case["id"])
            if key in completed:
                continue
            if calls >= max_calls or tokens >= max_tokens or (
                    time.monotonic() - start) / 60 >= max_minutes:
                write_status("BUDGET_STOP", "call/token/time budget exhausted")
                return directory
            began = time.monotonic()
            try:
                result = runtimes[arm].check({"case_id": case["id"],
                                              "prompt": case["prompt"],
                                              "response": case["response"]})
                rec = {"run_id": run_id, "config_id": arm,
                       "config_sha256": config_shas[arm],
                       "case_id": case["id"], "status": "COMPLETED",
                       "decision": result["decision"],
                       "result": result, "usage": result.get("usage") or {},
                       "elapsed_s": round(time.monotonic() - began, 3),
                       "completed_at": _utc()}
            except Exception as exc:  # noqa: BLE001
                rec = {"run_id": run_id, "config_id": arm,
                       "config_sha256": config_shas[arm],
                       "case_id": case["id"], "status": "FAILED",
                       "error": f"{type(exc).__name__}:{str(exc)[:200]}",
                       "elapsed_s": round(time.monotonic() - began, 3),
                       "completed_at": _utc()}
            with journal.open("a", encoding="utf-8") as handle:
                handle.write(json.dumps(rec, ensure_ascii=False) + "\n")
                handle.flush()
                os.fsync(handle.fileno())
            if rec["status"] == "COMPLETED":
                completed[key] = rec
                calls += int(rec["usage"].get("calls") or 0)
                tokens += int(rec["usage"].get("tokens") or 0)
            else:
                write_status("PARTIAL", rec["error"])
                return directory
            write_status("RUNNING")
        if len(completed) != len(planned):
            write_status("PARTIAL", "not all planned pairs completed")
            return directory
        summary = {"run_id": run_id, "state": "SUCCEEDED", "split": split,
                   "completed": len(completed), "total": len(planned),
                   "calls": calls, "tokens": tokens,
                   "decisions": {label: sum(r["decision"] == label
                       for r in completed.values()) for label in
                       ("ERROR", "NO_ERROR", "UNKNOWN")},
                   "finished_at": _utc()}
        _write_atomic(directory / "summary.json", summary)
        write_status("SUCCEEDED")
        return directory
    except BaseException as exc:
        write_status("FAILED", f"{type(exc).__name__}:{str(exc)[:200]}")
        raise


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--split", choices=("dev", "sealed"), required=True)
    p.add_argument("--arms", nargs="+", choices=ARMS, required=True)
    p.add_argument("--max-calls", type=int, default=1000)
    p.add_argument("--max-tokens", type=int, default=2_000_000)
    p.add_argument("--max-minutes", type=float, default=180)
    p.add_argument("--max-cases", type=int)
    p.add_argument("--output-root", type=Path, default=DEFAULT_ROOT)
    args = p.parse_args()
    if args.max_calls <= 0 or args.max_tokens <= 0 or args.max_minutes <= 0:
        p.error("budgets must be positive")
    directory = run(args.split, tuple(args.arms),
                    max_calls=args.max_calls, max_tokens=args.max_tokens,
                    max_minutes=args.max_minutes,
                    output_root=args.output_root,
                    max_cases=args.max_cases)
    status = json.loads((directory / "status.json").read_text(encoding="utf-8"))
    print(json.dumps({"directory": str(directory), "status": status},
                     ensure_ascii=False), flush=True)
    return 0 if status["state"] == "SUCCEEDED" else 2


if __name__ == "__main__":
    raise SystemExit(main())
