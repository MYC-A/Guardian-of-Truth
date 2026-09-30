#!/usr/bin/env python3
"""V level 0 — structural baseline (directive §9).

Runs the deterministic parser + confirmed structural checks over the input
file and writes IMMEDIATELY:
  * predictions.csv          (official format: id,label — same ids, order,
                              row count as input; confirmed structural hit
                              -> 1, everything else -> 0 as STRUCTURAL
                              BASELINE, not a certificate of absence)
  * predictions.structural.csv (immutable baseline copy)
  * audit.jsonl              (per-case structural status, suspicions with
                              neutral status, parse warnings, hashes)
  * stage_metadata.json      (input path, sha256, rows, timestamp, stage)

The model stage later refines the non-confirmed rows in predictions.csv and
MUST NOT overwrite confirmed structural 1s with votes.
"""
from __future__ import annotations

import argparse
import json
import shutil
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from common import (append_audit, case_audit_record, load_cases_csv,
                    load_cases_parquet, parse_case, sha256_text,
                    structural_label, write_predictions)

STAGE = "V0_structural_baseline"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True,
                    help="input CSV (id,prompt,response) or parquet")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--name", default="ta_v0",
                    help="run name (files: <name>_predictions.csv etc.)")
    args = ap.parse_args()

    inp = Path(args.input)
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)

    cases = (load_cases_parquet(inp) if inp.suffix == ".parquet"
             else load_cases_csv(inp))
    print(f"[V0] input={inp} rows={len(cases)}")

    rows = []
    t0 = time.time()
    for i, c in enumerate(cases):
        ctx = parse_case(c["id"], c["prompt"], c["response"])
        label = structural_label(ctx)
        rows.append({"id": c["id"], "label": label})
        append_audit(outdir / "audit.jsonl",
                     case_audit_record(ctx, STAGE, extra={
                         "structural_label": label}))
        if (i + 1) % 50 == 0 or i + 1 == len(cases):
            # atomic re-write of current predictions after each batch
            write_predictions(outdir / f"{args.name}_predictions.csv", rows)
            print(f"[V0] {i + 1}/{len(cases)} "
                  f"(structural 1s: {sum(r['label'] for r in rows)})")

    pred_path = outdir / f"{args.name}_predictions.csv"
    write_predictions(pred_path, rows)
    base_path = outdir / f"{args.name}_predictions.structural.csv"
    shutil.copyfile(pred_path, base_path)

    n_hits = sum(r["label"] for r in rows)
    meta = {
        "stage": STAGE,
        "input": str(inp),
        "input_sha256": sha256_text(inp.read_bytes().decode("utf-8",
                                                            "replace")
                                    if inp.suffix != ".parquet"
                                    else str(inp.stat().st_size)),
        "rows": len(rows),
        "structural_hits": n_hits,
        "baseline_note": ("zeros are the structural BASELINE, not a "
                          "certificate of error absence; confirmed hits are "
                          "mechanical catalog/schema violations of the "
                          "TARGET response only"),
        "elapsed_s": round(time.time() - t0, 2),
        "timestamp": time.time(),
        "predictions_csv": pred_path.name,
        "structural_copy": base_path.name,
    }
    (outdir / "stage_metadata.json").write_text(json.dumps(meta, indent=2))
    print(f"[V0] done: {n_hits}/{len(rows)} confirmed structural hits; "
          f"files in {outdir}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
