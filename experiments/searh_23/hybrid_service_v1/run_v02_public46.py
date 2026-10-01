#!/usr/bin/env python3
"""V0.2 diagnostic re-run on public46 (burned set) — directive §5.1.

public46 is a HISTORICAL REGRESSION set (PUBLIC_SEEN, burned). This run is
DIAGNOSTIC ONLY: it shows how the corrected policy-clause parsing changes
the confirmed-hit set versus frozen V0.1. No winner is declared, nothing
is tuned here; the holdout validates the channel.

Outputs (outdir):
  * v02_predictions.csv       — official format (id,label)
  * v02_diagnostic.json       — per-reason counts, V0.1 vs V0.2 diff,
                                case-level lists of gained/lost hits
  * audit.jsonl               — per-case structural audit (v0.2 channel)
"""
from __future__ import annotations

import json
import sys
import time
from collections import Counter
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parent / "three_architectures"))

from common import (append_audit, case_audit_record,  # noqa: E402
                    load_cases_parquet, parse_case,
                    structural_label, write_predictions)
from structural_v02 import parse_case_v02  # noqa: E402

STAGE = "V02_structural_diagnostic_public46"


def main() -> int:
    repo = HERE.parents[2]
    parquet = repo / "valid.parquet"
    outdir = HERE / "outputs" / "public46_v02"
    outdir.mkdir(parents=True, exist_ok=True)

    cases = load_cases_parquet(parquet)
    print(f"[V0.2] input={parquet} rows={len(cases)}")

    rows, audit_rows = [], []
    v01_labels, v02_labels = {}, {}
    v02_reasons = {}
    t0 = time.time()
    for c in cases:
        # frozen V0.1 (untouched historical baseline)
        ctx1 = parse_case(c["id"], c["prompt"], c["response"])
        v01_labels[c["id"]] = structural_label(ctx1)
        v01_reasons = [h.reason for h in ctx1.structural_hits]

        # corrected v0.2 channel
        ctx2 = parse_case_v02(c["id"], c["prompt"], c["response"])
        label2 = 1 if ctx2.structural_hits else 0
        v02_labels[c["id"]] = label2
        v02_reasons[c["id"]] = [h.reason for h in ctx2.structural_hits]

        rows.append({"id": c["id"], "label": label2})
        audit_rows.append({
            "id": c["id"],
            "v01_label": v01_labels[c["id"]],
            "v01_reasons": v01_reasons,
            "v02_label": label2,
            "v02_reasons": v02_reasons[c["id"]],
            "v02_suspicions": [s.kind for s in ctx2.suspicions],
        })
        append_audit(outdir / "audit.jsonl",
                     case_audit_record(ctx2, STAGE, extra={
                         "structural_label": label2}))

    write_predictions(outdir / "v02_predictions.csv", rows)

    gained = [a["id"] for a in audit_rows
              if a["v02_label"] > a["v01_label"]]
    lost = [a["id"] for a in audit_rows if a["v02_label"] < a["v01_label"]]
    reason_counter = Counter(
        r for rs in v02_reasons.values() for r in rs)
    susp_counter = Counter(
        k for a in audit_rows for k in a["v02_suspicions"])

    diag = {
        "stage": STAGE,
        "input": str(parquet),
        "rows": len(cases),
        "v01_confirmed": sum(v01_labels.values()),
        "v02_confirmed": sum(v02_labels.values()),
        "v02_reason_counts": dict(reason_counter),
        "v02_suspicion_counts": dict(susp_counter),
        "gained_vs_v01": gained,
        "lost_vs_v01": lost,
        "per_case_changes": [
            a for a in audit_rows
            if a["v01_label"] != a["v02_label"]
            or a["v01_reasons"] != a["v02_reasons"]],
        "wall_s": round(time.time() - t0, 2),
        "note": ("public46 = burned historical regression; diagnostic "
                 "only, no winner declared, nothing tuned"),
    }
    (outdir / "v02_diagnostic.json").write_text(
        json.dumps(diag, indent=2, ensure_ascii=False))
    print(f"[V0.2] confirmed: v01={diag['v01_confirmed']} "
          f"v02={diag['v02_confirmed']}; gained={gained} lost={lost}")
    print(f"[V0.2] reasons: {dict(reason_counter)}")
    print(f"[V0.2] suspicions: {dict(susp_counter)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
