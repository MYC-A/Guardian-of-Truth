"""Post-hoc, conservative source-role disjointness audit for staged trees.

An action span that intersects a prerequisite span cannot certify their
different semantic roles. This catches the two observed V2 bad anchors, but
disjoint spans alone do not prove that the action quote is semantically right.
"""
from __future__ import annotations

import argparse
import json

from build_policy_atoms_v1 import ROOT
from policy_model_ab_v1 import sha


OUT = ROOT / "outputs/searh_23/staged_source_role_gate_v1"


def disjoint(left: dict, right: dict) -> bool:
    return left["end"] <= right["start"] or right["end"] <= left["start"]


def audit(source_name: str) -> dict:
    source = ROOT / "outputs/searh_23" / source_name / "score.json"
    prior = json.loads(source.read_text(encoding="utf-8"))
    rows = []
    for row in prior["rows"]:
        tree = row.get("tree")
        action = tree.get("action_span") if isinstance(tree, dict) else None
        children = tree.get("condition", {}).get("children", []) if isinstance(tree, dict) else []
        collisions = [child["source_quote"] for child in children
                      if action is not None and not disjoint(action, child["source_span"])]
        rows.append({"id": row["id"], "prior_exact": row["exact"],
                     "source_role_disjoint": not collisions,
                     "colliding_condition_quotes": collisions,
                     "gated_exact": bool(row["exact"] and not collisions),
                     "global_verdict": "UNKNOWN"})
    result = {"source": source_name, "source_score_sha256": sha(prior),
              "rows": rows, "prior_exact": sum(row["prior_exact"] for row in rows),
              "gated_exact": sum(row["gated_exact"] for row in rows),
              "total": len(rows), "note": "post-hoc gate; cannot certify semantic source roles"}
    OUT.mkdir(parents=True, exist_ok=True)
    (OUT / (source_name + ".json")).write_text(
        json.dumps(result, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
    return {key: value for key, value in result.items() if key != "rows"}


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("source", choices=("staged_policy_tree_v1", "staged_policy_tree_v2"))
    print(json.dumps(audit(parser.parse_args().source)))
