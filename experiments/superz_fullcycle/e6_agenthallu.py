#!/usr/bin/env python3
"""E6 — external validation of A0 judges on AgentHallu DEV (488 trajectories).

AgentHallu DEV is an EXTERNAL benchmark (not used to develop any component of
this repo). Input: benchmarks/agenthallu_v1/dev/input.csv (label-free),
gold joined post-hoc from gold_binary.csv. This measures judge transfer to an
unseen external distribution (agent-trajectory hallucination/error detection).

Runs one provider per invocation so that independent rate pools can run in
parallel jobs. Append-only journal with per-case resume; disk cache shared per
provider. Compact summary per provider.
"""
from __future__ import annotations

import argparse
import csv
import hashlib
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(REPO))

from keyless_client import PROVIDERS, KeylessError, complete, extract_json_object
from a0_judge import A0_SYSTEM, messages_for

DEV_INPUT = REPO / "benchmarks" / "agenthallu_v1" / "dev" / "input.csv"
DEV_GOLD = REPO / "benchmarks" / "agenthallu_v1" / "dev" / "gold_binary.csv"
OUT_ROOT = REPO / "outputs" / "superz_fullcycle" / "e6_agenthallu"

MAX_INPUT_CHARS = 600_000  # context guard for long trajectories


def read_dev() -> tuple[list[dict], dict[str, int]]:
    csv.field_size_limit(64 * 1024 * 1024)
    with open(DEV_INPUT, newline="", encoding="utf-8") as f:
        rows = [r for r in csv.DictReader(f) if r.get("id")]
    gold = {}
    with open(DEV_GOLD, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            if r.get("id"):
                gold[r["id"]] = int(float(r["label"]))
    return rows, gold


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--provider", required=True)
    ap.add_argument("--limit", type=int, default=0, help="0 = all")
    args = ap.parse_args()

    cases, gold = read_dev()
    if args.limit:
        cases = cases[:args.limit]
    out_dir = OUT_ROOT / args.provider
    out_dir.mkdir(parents=True, exist_ok=True)
    journal = out_dir / "records.jsonl"
    cache = out_dir / "cache"

    done = set()
    if journal.is_file():
        with open(journal, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "OK":
                    done.add(rec["id"])
    print(f"[{args.provider}] {len(cases)} cases, {len(done)} done", flush=True)

    t0 = time.monotonic()
    n_fail = 0
    for case in cases:
        if case["id"] in done:
            continue
        msgs = messages_for(case)
        # context guard: truncate the middle of huge prompts (keep head+tail)
        user = msgs[1]["content"]
        if len(user) > MAX_INPUT_CHARS:
            head = MAX_INPUT_CHARS // 2
            tail = MAX_INPUT_CHARS - head
            user = user[:head] + "\n[...truncated by e6 context guard...]\n" + user[-tail:]
            msgs[1]["content"] = user
        rec = {"id": case["id"], "provider": args.provider,
               "requested_model": PROVIDERS[args.provider]["model"],
               "attempted_at_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())}
        ok = False
        for _ in range(3):
            try:
                res = complete(args.provider, msgs, max_tokens=400, temperature=0.0,
                               cache_dir=cache)
                parsed = extract_json_object(res["content"])
                label = int(parsed.get("label", 0))
                if label not in (0, 1):
                    raise KeylessError("label not 0/1")
                score = float(parsed.get("score", label))
                rec.update({"status": "OK", "label": label, "score": score,
                            "responded_model": res["model"], "latency": res["latency"],
                            "input_chars": len(user)})
                ok = True
                break
            except KeylessError as e:
                rec["last_error"] = str(e)[:200]
                time.sleep(3)
        if not ok:
            rec["status"] = "FAILED"
            n_fail += 1
        with open(journal, "a", encoding="utf-8") as f:
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        if (len(done) + sum(1 for _ in open(journal))) % 25 == 0 or not ok:
            print(f"[{args.provider}] {case['id']} -> {rec.get('status')} label={rec.get('label')}", flush=True)

    # evaluate
    preds = {}
    if journal.is_file():
        with open(journal, encoding="utf-8") as f:
            for line in f:
                try:
                    rec = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if rec.get("status") == "OK":
                    preds[rec["id"]] = int(rec["label"])
    tp = fp = fn = tn = 0
    for cid, g in gold.items():
        if cid not in preds:
            continue
        p = preds[cid]
        if p == 1 and g == 1:
            tp += 1
        elif p == 1 and g == 0:
            fp += 1
        elif p == 0 and g == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec_ = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec_ / (prec + rec_) if prec + rec_ else 0.0
    summary = {
        "provider": args.provider,
        "benchmark": "agenthallu_v1 DEV",
        "n_gold": len(gold), "n_scored": len(preds),
        "n_failed_records": n_fail,
        "metrics": {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                    "precision": round(prec, 4), "recall": round(rec_, 4), "F1": round(f1, 4)},
        "wall_seconds": round(time.monotonic() - t0),
        "records_sha256": hashlib.sha256(journal.read_bytes()).hexdigest() if journal.is_file() else None,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2),
                                          encoding="utf-8")
    print(json.dumps(summary, ensure_ascii=False, indent=2), flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
