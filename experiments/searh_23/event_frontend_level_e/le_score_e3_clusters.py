"""Evaluation-only E3 false-merge decomposition across output roots."""
from __future__ import annotations

import json
from collections import Counter
from itertools import combinations
from pathlib import Path

HERE = Path(__file__).parent


def score_root(root: Path, cases: dict) -> dict:
    rows = {}
    for folder in sorted(root.glob("TRACKB_*")):
        if not folder.is_dir():
            continue
        total = Counter()
        by_case = {}
        for cid, case in cases.items():
            path = folder / f"{cid}.json"
            if not path.exists():
                continue
            data = json.loads(path.read_text(encoding="utf-8"))
            alignment = json.loads((root / "ALIGNMENT" / f"{cid}.json").read_text(encoding="utf-8"))["alignments"]
            labels = {f"P{r['i']:02d}": r["label"] for r in alignment}
            by_cid = {e["cid"]: e for e in case["canonical_events"]}
            count = Counter()
            present = set()
            for node in data["nodes"]:
                members = node["members"]
                present.update(members)
                for a, b in combinations(members, 2):
                    la, lb = labels[a], labels[b]
                    if la == lb and la != "NON_EVENT":
                        count["correct_merge_pairs"] += 1
                    elif la == "NON_EVENT" or lb == "NON_EVENT":
                        count["junk_false_merge_pairs"] += 1
                    else:
                        count["event_false_merge_pairs"] += 1
                        ra, rb = by_cid[la]["role"], by_cid[lb]["role"]
                        count[f"role_pair::{min(ra,rb)}::{max(ra,rb)}"] += 1
            count["real_mentions_dropped"] = sum(r["label"] != "NON_EVENT" and f"P{r['i']:02d}" not in present
                                                 for r in alignment)
            count["junk_mentions_retained"] = sum(r["label"] == "NON_EVENT" and f"P{r['i']:02d}" in present
                                                  for r in alignment)
            count["nodes"] = len(data["nodes"])
            total.update(count)
            by_case[cid] = dict(count)
        if by_case:
            rows[folder.name] = {"total": dict(total), "cases": by_case}
    return rows


def main():
    cases = {c["case_id"]: c for c in json.loads((HERE / "frozen" / "frozen_cases.json").read_text(encoding="utf-8"))}
    result = {}
    for name in ("outputs", "outputs_fixed", "outputs_rescue", "outputs_clustering"):
        root = HERE / name
        if root.exists() and (root / "ALIGNMENT").exists():
            result[name] = score_root(root, cases)
    (HERE / "cluster_error_decomposition.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    for root, arms in result.items():
        for arm, x in arms.items():
            t = x["total"]
            print(root, arm, "event_false_merge", t.get("event_false_merge_pairs", 0),
                  "junk_false_merge", t.get("junk_false_merge_pairs", 0),
                  "real_dropped", t.get("real_mentions_dropped", 0))


if __name__ == "__main__":
    main()
