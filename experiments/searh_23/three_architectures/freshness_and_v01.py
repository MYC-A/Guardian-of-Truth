#!/usr/bin/env python3
"""Freshness audit follow-up + manifest v2 + V0.1 diagnostic re-run.

1. Annotates fam_aquarium as domain_seen (grandfathered dev-only).
2. Re-issues dataset/manifest_v2.json with the freshness audit (manifest v1
   left untouched for history).
3. Re-runs the (now V0.1) structural channel on public46 as a DIAGNOSTIC
   into outputs/public46_v01/ — the burned regression set; historical
   outputs/public46_v0/ stays untouched.
"""
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
import common as tc          # noqa: E402  (V0.1 rules inside)
import dataset_builder as db  # noqa: E402


def main():
    # ---------------- 1. annotate fam_aquarium ----------------
    fa = HERE / "families" / "fam_aquarium.json"
    spec = json.load(open(fa))
    spec["domain_seen"] = True
    spec["domain_seen_in"] = [
        "system_research_v2/probe_task1.py: calib.aquarium "
        "(tank drain gated on logged salinity check + overheating exception)",
        "event_frontend_level_e/frozen: 'public aquarium' domain cases "
        "(e_aquarium)",
    ]
    spec["notes"] = (spec.get("notes", "") +
                     " | FRESHNESS AUDIT 2026-10-01: domain 'aquarium' was "
                     "used by previous suites (calib.aquarium in "
                     "system_research_v2 probe_task1; 'public aquarium' in "
                     "event_frontend_level_e). Policy text, tools and "
                     "governed actions differ from both, but this family is "
                     "NOT counted as fresh: grandfathered dev-split "
                     "regression material, excluded from fresh-family "
                     "counts, never allowed in the sealed split.")
    with open(fa, "w", encoding="utf-8") as f:
        json.dump(spec, f, ensure_ascii=False, indent=1)
    print("annotated fam_aquarium.json (domain_seen=true, dev-only)")

    # ---------------- 2. validate all families under new rules ----------
    for name in ["fam_aquarium", "fam_ski_lift", "fam_rare_books",
                 "fam_campground"]:
        s = json.load(open(HERE / "families" / f"{name}.json"))
        errs = db.validate_family(s)
        print(f"validate {name}: {'OK' if not errs else errs}")

    # ---------------- 3. manifest v2 ------------------------------------
    m1 = json.load(open(HERE / "dataset" / "manifest.json"))
    m2 = dict(m1)
    m2["manifest_version"] = 2
    m2["reissued_at_utc"] = "2026-10-01T00:00:00Z"
    m2["reissue_reason"] = (
        "freshness audit: domain 'aquarium' (fam_aquarium) was used by "
        "previous suites (calib.aquarium@system_research_v2, 'public "
        "aquarium'@event_frontend_level_e); it is reclassified as "
        "domain_seen dev-only regression material and excluded from "
        "fresh-family counts. No case content changed; splits unchanged; "
        "v1 manifest preserved.")
    m2["freshness_audit"] = {
        "fresh_families": ["fam_ski_lift (dev)", "fam_rare_books (sealed)",
                           "fam_campground (sealed)"],
        "domain_seen_families": ["fam_aquarium (dev only, grandfathered)"],
        "fresh_family_count": 3,
        "n_families_total": 4,
        "used_domains_updated": "dataset_builder.USED_DOMAINS now includes "
                                "calib/probe domains and all Level E domains",
    }
    with open(HERE / "dataset" / "manifest_v2.json", "w",
              encoding="utf-8") as f:
        json.dump(m2, f, ensure_ascii=False, indent=1)
    print("wrote dataset/manifest_v2.json (v1 preserved)")

    # ---------------- 4. V0.1 diagnostic on public46 --------------------
    out = HERE / "outputs" / "public46_v01"
    out.mkdir(parents=True, exist_ok=True)
    rows, audit = [], []
    reason_counts = {}
    for row in tc.load_cases_csv(HERE / "data" / "public46.csv"):
        ctx = tc.parse_case(row["id"], row["prompt"], row["response"])
        label = tc.structural_label(ctx)
        rows.append({"id": row["id"], "label": label})
        for h in ctx.structural_hits:
            reason_counts[h.reason] = reason_counts.get(h.reason, 0) + 1
        audit.append(tc.case_audit_record(ctx, stage="V0.1_structural"))
    tc.write_predictions(out / "ta_v01_predictions.csv", rows)
    with open(out / "audit.jsonl", "w", encoding="utf-8") as f:
        for a in audit:
            f.write(json.dumps(a, ensure_ascii=False) + "\n")

    gold = {}
    for r in __import__("csv").DictReader(
            open(HERE / "data" / "public46_gold.csv")):
        gold[r["id"]] = int(r["label"])
    pred = {r["id"]: r["label"] for r in rows}
    tp = sum(1 for c in gold if gold[c] == 1 and pred[c] == 1)
    fp = sum(1 for c in gold if gold[c] == 0 and pred[c] == 1)
    fn = sum(1 for c in gold if gold[c] == 1 and pred[c] == 0)
    tn = sum(1 for c in gold if gold[c] == 0 and pred[c] == 0)
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    print(f"V0.1 diagnostic on public46: TP{tp} FP{fp} FN{fn} TN{tn} "
          f"P={p:.4f} R={r:.4f} F1={f1:.4f}")
    print(f"hit reasons: {reason_counts}")
    pos_ids = [rr["id"] for rr in rows if rr["label"] == 1]
    print(f"positive ids ({len(pos_ids)}):")
    for i in pos_ids:
        print("   ", i)


if __name__ == "__main__":
    main()
