"""Unchanged deterministic splitter on a separately frozen source set."""
from __future__ import annotations

import json

from build_policy_atoms_v1 import ROOT
from deterministic_policy_splitter_v1 import split_policy
from policy_model_ab_v1 import sha


SOURCE = ROOT / "experiments/searh_23/deterministic_segmentation_transfer_v1/frozen.json"
OUT = ROOT / "outputs/searh_23/deterministic_policy_splitter_transfer_v1"


def score() -> dict:
    protocol = json.loads(SOURCE.read_text(encoding="utf-8"))
    rows = []
    for task in protocol["tasks"]:
        cuts, segments = split_policy(task["policy"])
        rows.append({"id": task["id"], "expected_cut_offsets": task["expected_cut_offsets"],
                     "actual_cut_offsets": cuts, "exact": cuts == task["expected_cut_offsets"],
                     "segments": segments, "global_verdict": "UNKNOWN"})
    result = {"source_protocol_sha256": sha(protocol), "rows": rows,
              "exact": sum(row["exact"] for row in rows), "total": len(rows),
              "note": "unchanged splitter; post-implementation annotated original clauses"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / "score.json").write_text(json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    print(json.dumps(score()))
