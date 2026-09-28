"""Build an isolated output root for the unchanged downstream relation code.

Frontend fixes change resolver labels and may add secondary candidates. This
control reuses F pair decisions only when the exact candidate spans/offsets
match the original run; otherwise it refuses to build the comparison.
"""
from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
sys.path.insert(0, str(EC))
from ec_common import load_suite
from ec_track_b import predicted_mentions, cluster_to_nodes
from ec_cluster import build_clusters

SOURCE = HERE / "outputs"
TARGET = HERE / "outputs_fixed"
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE", "UNKNOWN"}


def main():
    summary = {"candidates": 0, "role_changes_original_vs_fixed": 0,
               "renamed_role_changes": 0, "rescued": 0}
    for case in load_suite("original"):
        cid = case["case_id"]
        original = json.loads((SOURCE / "FRONTEND" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        fixed = json.loads((SOURCE / "FRONTEND_fixed_rescue" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        renamed = json.loads((SOURCE / "FRONTEND_fixed_rescue_renamed" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        if [(x["span"], x["span_start"], x["span_end"]) for x in original] != [
            (x["span"], x["span_start"], x["span_end"]) for x in fixed]:
            raise ValueError(f"candidate inventory changed in {cid}; must realign and rerun identity")
        if [(x["span"], x["span_start"], x["span_end"]) for x in fixed] != [
            (x["span"], x["span_start"], x["span_end"]) for x in renamed]:
            raise ValueError(f"rename altered candidate inventory in {cid}")
        summary["candidates"] += len(fixed)
        summary["role_changes_original_vs_fixed"] += sum(a["role"] != b["role"] for a, b in zip(original, fixed))
        summary["renamed_role_changes"] += sum(a["role"] != b["role"] for a, b in zip(fixed, renamed))
        summary["rescued"] += sum(bool(x.get("pos_rescue")) for x in fixed)
        for directory, name in (("FRONTEND_fixed_rescue", "FRONTEND"), ("ALIGNMENT", "ALIGNMENT")):
            dest = TARGET / name
            dest.mkdir(parents=True, exist_ok=True)
            shutil.copy2(SOURCE / directory / f"{cid}.json", dest / f"{cid}.json")
        mentions = predicted_mentions(case, TARGET / "FRONTEND")
        base = json.loads((SOURCE / "TRACKB_F_pol_veto" / f"{cid}.json").read_text(encoding="utf-8"))
        pair_src = base["pair_src"]
        elabs = {f"P{i:02d}": json.loads((SOURCE / "E3_EVENTNESS" / f"{cid}__P{i:02d}.json").read_text(encoding="utf-8"))["label"]
                 for i in range(len(mentions))}
        for name in ("FIXED_ONLY", "FIXED_CANON_F", "FIXED_EVENTNESS_CANON_F"):
            subset = [m for m in mentions if name != "FIXED_EVENTNESS_CANON_F" or elabs[m["mid"]] in EVENTLIKE]
            mids = {m["mid"] for m in subset}
            pairs = [r for r in pair_src if r["a"] in mids and r["b"] in mids]
            assign = ({m["mid"]: f"singleton_{m['mid']}" for m in subset}
                      if name == "FIXED_ONLY" else build_clusters(pairs, "veto"))
            nodes = cluster_to_nodes(case, subset, assign)
            dest = TARGET / f"TRACKB_{name}"
            dest.mkdir(parents=True, exist_ok=True)
            (dest / f"{cid}.json").write_text(json.dumps({"case_id": cid, "mentions": subset,
                        "assign": assign, "nodes": nodes, "pair_src": pairs},
                        ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    (TARGET / "frontend_comparison.json").write_text(json.dumps(summary, indent=2) + "\n", encoding="utf-8")
    print(json.dumps(summary, indent=2))


if __name__ == "__main__":
    main()
