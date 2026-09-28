"""Assemble exploratory rescue + eventness + existing F/veto canonicalizer.

Old candidate eventness decisions are transferred by exact source span and
offset; each new command was accepted by the narrow imperative judge. No
gold alignment is read. Unknown remains a singleton/uncertain mention.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
EC = HERE.parent / "event_canon_v1"
sys.path.insert(0, str(EC))
from ec_common import load_suite
from ec_track_b import predicted_mentions, cluster_to_nodes
from ec_cluster import build_clusters

SOURCE = HERE / "outputs"
TARGET = HERE / "outputs_rescue"
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE", "UNKNOWN"}


def key(p):
    return p["span"], p["span_start"], p["span_end"]


def main():
    for case in load_suite("original"):
        cid = case["case_id"]
        original = json.loads((SOURCE / "FRONTEND" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        rescue = json.loads((TARGET / "FRONTEND" / f"{cid}.json").read_text(encoding="utf-8"))["events"]
        status = {key(p): json.loads((SOURCE / "E3_EVENTNESS" / f"{cid}__P{i:02d}.json").read_text(encoding="utf-8"))["label"]
                  for i, p in enumerate(original)}
        mentions = predicted_mentions(case, TARGET / "FRONTEND")
        keep = set()
        for i, p in enumerate(rescue):
            lab = "EVENT" if p.get("dep") == "rescue_imperative" else status[key(p)]
            if lab in EVENTLIKE:
                keep.add(f"P{i:02d}")
        base = json.loads((TARGET / "TRACKB_F_pol_veto" / f"{cid}.json").read_text(encoding="utf-8"))
        subset = [m for m in mentions if m["mid"] in keep]
        pairs = [r for r in base["pair_src"] if r["a"] in keep and r["b"] in keep]
        assign = build_clusters(pairs, "veto")
        nodes = cluster_to_nodes(case, subset, assign)
        dest = TARGET / "TRACKB_RESCUE_GATE"
        dest.mkdir(parents=True, exist_ok=True)
        (dest / f"{cid}.json").write_text(json.dumps({"case_id": cid, "mentions": subset,
            "assign": assign, "nodes": nodes, "pair_src": pairs,
            "retained": sorted(keep)}, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(cid, len(rescue), len(subset), len(nodes))


if __name__ == "__main__":
    main()
