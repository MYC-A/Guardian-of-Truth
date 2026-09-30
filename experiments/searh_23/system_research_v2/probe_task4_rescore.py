#!/usr/bin/env python3
"""Diagnostic rescore of probe_task4.json with the CORRECTED gold for
q_dispatch_vs_check (defect confirmed 2026-09-30, see HISTORY_AUDIT.md).

Original frozen outputs are NOT overwritten: this writes
outputs/probe_task4_rescore/summary.json alongside them.

Defect: gold answer was "A" ("checking is the required evidence") while the
policy requires the inspection to have PASSED; the correct reading is "B"
("only a passed inspection result satisfies it"). All 4 probed models
answered B and were scored incorrect by the frozen gold.
"""
import json
from pathlib import Path

HERE = Path(__file__).resolve().parent
SRC = HERE / "outputs" / "probe_task4.json"
DST = HERE / "outputs" / "probe_task4_rescore"
QID = "q_dispatch_vs_check"
OLD_GOLD, NEW_GOLD = "A", "B"


def main() -> None:
    data = json.loads(SRC.read_text())
    DST.mkdir(parents=True, exist_ok=True)
    out = {
        "rescore_reason": (
            "q_dispatch_vs_check gold defect: check-ACT counted instead of "
            "check-RESULT; corrected per HISTORY_AUDIT.md; original "
            "probe_task4.json preserved untouched"
        ),
        "question_id": QID,
        "original_gold": OLD_GOLD,
        "corrected_gold": NEW_GOLD,
        "models": {},
    }
    for model, payload in data.items():
        agg = dict(payload["aggregate"])
        flipped = []
        per_q = []
        for rec in payload["per_q"]:
            rec = dict(rec)
            if rec["id"] == QID:
                was = rec["correct"]
                rec["gold"] = NEW_GOLD
                rec["correct"] = rec["choice"] == NEW_GOLD
                rec["rescored"] = True
                flipped.append(
                    {"choice": rec["choice"], "was_correct": was,
                     "now_correct": rec["correct"]}
                )
                if rec["correct"] and not was:
                    agg["correct"] += 1
                elif was and not rec["correct"]:
                    agg["correct"] -= 1
            per_q.append(rec)
        out["models"][model] = {
            "original_aggregate": payload["aggregate"],
            "rescored_aggregate": agg,
            "q_dispatch_vs_check": flipped[0] if flipped else None,
        }
        (DST / f"{model.replace(':', '_')}_per_q.json").write_text(
            json.dumps(per_q, indent=2)
        )
    (DST / "summary.json").write_text(json.dumps(out, indent=2))
    print(json.dumps(out["models"], indent=2))
    print(f"\nwritten: {DST}/summary.json (original untouched: {SRC})")


if __name__ == "__main__":
    main()
