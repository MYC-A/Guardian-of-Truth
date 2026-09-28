"""EVENT_CANON_v1 - rebuild Track B clustering from stored pair decisions.

Motivated by a discipline fix (not by test results): UNKNOWN-labelled pairs
must not merge (brief §14). ec_cluster.LABEL_SCORE[UNKNOWN] lowered to 0.4
(below the merge threshold). This script re-derives `assign` + `nodes` from
the stored `pair_src` of each TRACKB run; no new model calls.

Usage: python3 ec_recluster.py SRC_DIR DST_DIR [method]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_cluster import build_clusters, pair_score
from ec_track_b import cluster_to_nodes


def main():
    src = Path(sys.argv[1])
    dst = Path(sys.argv[2])
    method = sys.argv[3] if len(sys.argv) > 3 else "veto"
    dst.mkdir(parents=True, exist_ok=True)
    for p in sorted(src.glob("*.json")):
        data = json.loads(p.read_text(encoding="utf-8"))
        assign = build_clusters(data["pair_src"], method)
        nodes = cluster_to_nodes(None, data["mentions"], assign)
        out = dict(data)
        out["assign"] = assign
        out["nodes"] = nodes
        out["reclustered"] = {"method": method,
                              "note": "UNKNOWN pairs never merge (discipline fix)"}
        dst.joinpath(p.name).write_text(json.dumps(out, ensure_ascii=False,
                                                   indent=1), encoding="utf-8")
        print(f"[{p.stem}] {len(data['mentions'])} -> {len(nodes)} nodes")
    print("reclustered:", dst)


if __name__ == "__main__":
    main()
