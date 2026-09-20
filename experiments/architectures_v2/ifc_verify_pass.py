#!/usr/bin/env python3
"""IFC verification pass — s3 as post-hoc check over existing s2 records (postfix: ifc).

Reads s2 records.jsonl (anchored suspicions), asks an INDEPENDENT verifier model
to confirm/refute each anchored suspicion against the original context, then
derives the verified prediction: label=1 iff >=1 CONFIRMED suspicion.

Paired design: same producer suspicions, only verification differs -> isolates
the verifier's contribution. Resumable, append-only, gold-blind.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from datetime import UTC, datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from ifc_suspicions import LLM, extract_json, VERIFY_SYSTEM, context_block


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True, help="CSV/parquet with id,prompt,response (full context)")
    ap.add_argument("--s2-records", required=True, help="s2 records.jsonl")
    ap.add_argument("--output-dir", required=True)
    ap.add_argument("--verifier", default="pollinations")
    ap.add_argument("--max-rows", type=int, default=0)
    ap.add_argument("--max-input-chars", type=int, default=300000)
    ap.add_argument("--timeout", type=int, default=240)
    args = ap.parse_args()

    in_path = Path(args.input)
    if in_path.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(in_path)[["id", "prompt", "response"]]
    else:
        import csv
        csv.field_size_limit(min(2 ** 31 - 1, 2 ** 30))
        rows = list(csv.DictReader(open(in_path, encoding="utf-8")))
        df = pd.DataFrame(rows)[["id", "prompt", "response"]]
    contexts = {r["id"]: r for r in df.to_dict("records")}

    s2_records = [json.loads(l) for l in open(args.s2_records, encoding="utf-8") if l.strip()]
    if args.max_rows:
        s2_records = s2_records[: args.max_rows]

    out_dir = Path(args.output_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    rec_path = out_dir / "records.jsonl"
    done = {}
    if rec_path.exists():
        for line in open(rec_path, encoding="utf-8"):
            try:
                rec = json.loads(line)
                done[rec["id"]] = not rec.get("error")
            except Exception:  # noqa: BLE001
                pass

    verifier = LLM(args.verifier, timeout=args.timeout)
    manifest = {
        "line": "independent-fullcycle-20260920", "postfix": "ifc",
        "hypothesis": "Independent cross-model verification of anchored suspicions removes FP while preserving TP (A3-analog, paired with s2)",
        "verifier": args.verifier, "s2_records": os.path.abspath(args.s2_records),
        "git_sha": os.popen("git rev-parse HEAD").read().strip(),
        "dataset_sha256_16": hashlib.sha256(in_path.read_bytes()).hexdigest()[:16],
        "n_cases": len(s2_records), "started_utc": datetime.now(UTC).isoformat(),
    }
    t0 = time.time()
    with open(rec_path, "a", encoding="utf-8") as fh:
        for i, s2 in enumerate(s2_records):
            cid = s2["id"]
            if done.get(cid):
                continue
            case = contexts.get(cid)
            rec = {"id": cid, "ts": datetime.now(UTC).isoformat()}
            if case is None:
                rec.update({"error": "context not found"})
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n"); fh.flush(); continue
            ctx = context_block(case["prompt"], case["response"], args.max_input_chars)
            anchored = [s for s in s2.get("suspicions", []) if (s.get("_gate") or {}).get("status") == "ANCHORED"]
            verdicts, confirmed = [], 0
            for s in anchored:
                try:
                    v = verifier.chat(
                        [{"role": "system", "content": VERIFY_SYSTEM},
                         {"role": "user", "content": f"{ctx}\n\n=== SUSPICION TO VERIFY ===\n{json.dumps(s, ensure_ascii=False)}"}],
                        max_tokens=512)
                    vj = extract_json(v["content"]) or {}
                    verdict = vj.get("verdict", "UNCERTAIN")
                    if verdict == "CONFIRMED":
                        confirmed += 1
                    verdicts.append({"verdict": verdict, "reason": str(vj.get("reason"))[:300],
                                     "model": v["actual_model"], "latency_s": v["latency_s"]})
                except Exception as e:  # noqa: BLE001
                    verdicts.append({"verdict": "ERROR", "reason": str(e)[:200]})
            rec.update({
                "prediction": 1 if confirmed > 0 else 0,
                "s2_prediction": s2.get("prediction"),
                "n_anchored": len(anchored),
                "n_confirmed": confirmed,
                "n_uncertain": sum(1 for v in verdicts if v["verdict"] == "UNCERTAIN"),
                "verdicts": verdicts,
                "error": None if all(v["verdict"] != "ERROR" for v in verdicts) else "some verifications failed",
            })
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
            fh.flush()
            print(f"[{i+1}/{len(s2_records)}] {cid} s2={s2.get('prediction')} -> verified={rec['prediction']} "
                  f"(anch={len(anchored)} conf={confirmed})", flush=True)

    manifest["finished_utc"] = datetime.now(UTC).isoformat()
    manifest["wall_seconds"] = round(time.time() - t0, 1)
    manifest["verifier_calls"] = verifier.calls
    manifest["verifier_tokens"] = {"prompt": verifier.prompt_tokens, "completion": verifier.completion_tokens}
    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=1), encoding="utf-8")
    print("MANIFEST:", json.dumps(manifest)[:400])
    return 0


if __name__ == "__main__":
    sys.exit(main())
