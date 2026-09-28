"""EVENT_CANON_v1 - Track B gold alignment (annotated BEFORE any
canonicalization inference on predicted mentions).

Auto-suggestion: char overlap between predicted span and gold mention span;
a predicted event maps to the canonical event of the earliest-starting gold
mention it covers (>=50% of the gold mention, or >=60% of the prediction);
ties on start resolved by longer gold span. Manual overrides below encode
annotator review (gerund references without gold mention spans, participial
fragments, multi-event clauses).
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import load_suite, out_dir

# ---- annotator overrides (review of auto suggestions) ----
# label: canonical cid | "NON_EVENT"
OVERRIDES = {
    "val_icecream": {"2": "E2"},           # "before churning" -> gerund ref to churn
    "test_cardetailing": {"1": "E3"},      # "before polishing" -> gerund ref to polish
    "val_hydroponic": {"8": "NON_EVENT"},  # "harvest weight" entity NP
    "test_vaccineclinic": {"1": "NON_EVENT"},   # "cooler temperature" entity NP
    "test_vaccineclinic_cf": {"1": "NON_EVENT"},
    "val_petgrooming": {"6": "NON_EVENT"},      # "vaccination status..." entity NP
    "test_hotairballoon": {"7": "NON_EVENT"},   # "before boarding" - real event not modeled in gold
}


def suggest(case, pred_events):
    ms = case["mentions"]
    out = []
    for i, p in enumerate(pred_events):
        ps, pe = p["span_start"], p["span_end"]
        hits = []
        for g in ms:
            ov = max(0, min(pe, g["end"]) - max(ps, g["start"]))
            if ov <= 0:
                continue
            ratio_g = ov / max(1, g["end"] - g["start"])
            ratio_p = ov / max(1, pe - ps)
            hits.append((g, ov, ratio_g, ratio_p))
        # NP predictions map only when covering a gold EVENT-NP mention
        # (>=60% of the gold span); clause predictions additionally map
        # when fully contained in a gold mention (>=85%, partial clauses
        # produced by the frontend's advcl-stripping).
        if p.get("is_np"):
            eligible = [h for h in hits if h[2] >= 0.6]
        else:
            eligible = [h for h in hits if h[2] >= 0.6 or h[3] >= 0.85]
        if eligible:
            primary = sorted(eligible,
                             key=lambda h: (h[0]["start"],
                                            -(h[0]["end"] - h[0]["start"])))[0]
            covers = sorted({h[0]["cid"] for h in eligible})
            out.append({"i": i, "span": p["span"],
                        "label": primary[0]["cid"], "covers": covers,
                        "primary_gold": primary[0]["span"]})
        else:
            out.append({"i": i, "span": p["span"], "label": "NON_EVENT",
                        "covers": [], "primary_gold": None})
    return out


def main():
    suite = load_suite("original")
    align_dir = out_dir("ALIGNMENT")
    summary = {"cases": 0, "pred_events": 0, "mapped": 0, "non_event": 0,
               "multi_cover": 0, "overrides_applied": 0}
    uncertain = []
    for case in suite:
        cid_ = case["case_id"]
        fpath = out_dir("FRONTEND") / f"{cid_}.json"
        pred = json.loads(fpath.read_text(encoding="utf-8"))["events"]
        rows = suggest(case, pred)
        ov = OVERRIDES.get(cid_, {})
        for r in rows:
            key = str(r["i"])
            if key in ov:
                new = ov[key]
                if new == "NON_EVENT":
                    r.update({"label": "NON_EVENT", "covers": [],
                              "primary_gold": None, "overridden": True})
                else:
                    r.update({"label": new, "overridden": True})
                summary["overrides_applied"] += 1
            if len(r["covers"]) > 1:
                summary["multi_cover"] += 1
                uncertain.append((cid_, r["span"], r["covers"]))
        # every gold canonical event covered by at least one prediction?
        covered = {c for r in rows for c in ([r["label"]] if r["label"] != "NON_EVENT" else [])} | \
                  {c for r in rows for c in r["covers"]}
        missing = [e["cid"] for e in case["canonical_events"]
                   if e["cid"] not in covered]
        align_dir.joinpath(f"{cid_}.json").write_text(
            json.dumps({"case_id": cid_, "alignments": rows,
                        "gold_cids_missing_from_predictions": missing},
                       ensure_ascii=False, indent=1), encoding="utf-8")
        summary["cases"] += 1
        summary["pred_events"] += len(rows)
        summary["mapped"] += sum(1 for r in rows if r["label"] != "NON_EVENT")
        summary["non_event"] += sum(1 for r in rows
                                    if r["label"] == "NON_EVENT")
        if missing:
            uncertain.append((cid_, "GOLD-CID-MISSING", missing))
    out_dir("SCORE").mkdir(parents=True, exist_ok=True)
    out_dir("SCORE").joinpath("alignment_summary.json").write_text(
        json.dumps({**summary, "uncertain": uncertain}, indent=1,
                   ensure_ascii=False), encoding="utf-8")
    print(json.dumps(summary, indent=1))
    print("\nUNCERTAIN / MULTI-COVER / MISSING:")
    for u in uncertain:
        print(" ", u)


if __name__ == "__main__":
    main()
