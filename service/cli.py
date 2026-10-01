#!/usr/bin/env python3
"""Guardian batch CLI (directive §13, Stage A).

Runs a frozen config over an input CSV/parquet in the OFFICIAL format
(id,prompt,response[,label,explanation]) and writes:
  * predictions.csv   — official (id,label); UNKNOWN maps to the frozen
                        csv_unknown_label of the config (documented);
  * results.jsonl     — full §13 payloads per case;
  * audit.jsonl       — one line per decision.

Examples:
  python -m service.cli --input valid.parquet --config structural-v02 \
      --outdir outputs/service_smoke
  python -m service.cli --input cases.csv --config v6-judges \
      --outdir outputs/service_v6
"""
from __future__ import annotations

import argparse
import csv
import json
import sys
import time
from pathlib import Path

REPO = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO / "experiments/searh_23/three_architectures"))
sys.path.insert(0, str(REPO / "service"))


def load_input(path: Path) -> list:
    if path.suffix == ".parquet":
        import pandas as pd
        df = pd.read_parquet(path)
        return [{"case_id": r["id"], "prompt": r["prompt"],
                 "response": r["response"]} for _, r in df.iterrows()]
    with open(path, encoding="utf-8") as fh:
        return [{"case_id": r["id"], "prompt": r["prompt"],
                 "response": r["response"]} for r in csv.DictReader(fh)]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--config", default="structural-v02")
    ap.add_argument("--outdir", required=True)
    ap.add_argument("--limit", type=int, default=0,
                    help="only the first N cases (0 = all)")
    args = ap.parse_args()

    from runtime import GuardianServiceRuntime
    outdir = Path(args.outdir)
    outdir.mkdir(parents=True, exist_ok=True)
    rt = GuardianServiceRuntime(args.config,
                                audit_path=outdir / "audit.jsonl")

    cases = load_input(Path(args.input))
    if args.limit:
        cases = cases[:args.limit]
    print(f"[cli] input={args.input} cases={len(cases)} "
          f"config={rt.config_id}")

    rows, results = [], []
    t0 = time.time()
    for c in cases:
        payload = rt.check(c)
        results.append(payload)
        label = 1 if payload["decision"] == "ERROR" else \
            rt.config.get("csv_unknown_label", 0)
        rows.append({"id": c["case_id"], "label": label})

    with open(outdir / "predictions.csv", "w", newline="",
              encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=["id", "label"])
        w.writeheader()
        w.writerows(rows)
    with open(outdir / "results.jsonl", "w", encoding="utf-8") as fh:
        for p in results:
            fh.write(json.dumps(p, ensure_ascii=False, default=str) + "\n")

    n_err = sum(1 for p in results if p["decision"] == "ERROR")
    n_unk = sum(1 for p in results if p["decision"] == "UNKNOWN")
    print(f"[cli] done in {time.time()-t0:.1f}s: ERROR={n_err} "
          f"UNKNOWN={n_unk} NO_ERROR={len(results)-n_err-n_unk}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
