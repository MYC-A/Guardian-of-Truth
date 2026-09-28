"""Evaluation audit: unique, directed, uncontaminated canonical graph edges.

The historical scorer accepts a gold edge if ANY member pair hits it. That
can credit a node mixing two different events, count duplicates as recall,
and let reverse edges cover missing gold. Keep that historical score for
comparability; report this stricter audit separately, without changing any
inference code or selecting a mechanism against this score.
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent


def score_case(data: dict, alignment: dict, case: dict) -> dict:
    gold = {(e["from_cid"], e["to_cid"]): set(e["acceptable"]) for e in case["edges"]}
    hits, typed_hits = set(), set()
    count = Counter()
    errors = []

    def labels(members):
        return {alignment[m] for m in members}

    for i, edge in enumerate(data["edges"]):
        left, right = labels(edge["u_members"]), labels(edge["v_members"])
        reason = None
        if len(left) != 1 or len(right) != 1 or "NON_EVENT" in left | right:
            count["contaminated_endpoint_edges"] += 1
            reason = "contaminated_or_junk_endpoint"
        else:
            a, b = next(iter(left)), next(iter(right))
            if (a, b) in gold:
                if (a, b) in hits:
                    count["duplicate_supported_edges"] += 1
                    reason = "duplicate_gold_edge"
                else:
                    hits.add((a, b))
                    count["correct_unique"] += 1
                if edge.get("relation") in gold[(a, b)]:
                    typed_hits.add((a, b))
            elif (b, a) in gold:
                count["reverse_edges"] += 1
                reason = "wrong_direction"
            else:
                reason = "unsupported_edge"
        if reason:
            count["extra_strict"] += 1
            errors.append({"index": i, "from_labels": sorted(left),
                           "to_labels": sorted(right), "reason": reason})
    count["accepted"] = len(data["edges"])
    count["gold_edges"] = len(gold)
    count["missing_directed"] = len(set(gold) - hits)
    count["typed_unique"] = len(typed_hits)
    count["exact_graph"] = int(len(hits) == len(gold) and count["extra_strict"] == 0)
    count["exact_typed_graph"] = int(count["exact_graph"] and len(typed_hits) == len(gold))
    return {"counts": dict(count), "errors": errors,
            "missing": [list(x) for x in sorted(set(gold) - hits)]}


def run():
    cases = {c["case_id"]: c for c in json.loads((HERE / "frozen/frozen_cases.json").read_text(encoding="utf-8"))}
    result = {}
    for rootname in ("outputs", "outputs_fixed", "outputs_gold", "outputs_rescue", "outputs_clustering"):
        root = HERE / rootname
        arms = {}
        for folder in sorted(root.glob("DOWNSTREAM_*")):
            total, rows = Counter(), {}
            for cid, case in cases.items():
                path = folder / f"{cid}.json"
                if not path.exists():
                    continue
                alignpath = root / "ALIGNMENT" / f"{cid}.json"
                alignment = {f"P{r['i']:02d}": r["label"] for r in json.loads(alignpath.read_text(encoding="utf-8"))["alignments"]}
                row = score_case(json.loads(path.read_text(encoding="utf-8")), alignment, case)
                rows[cid] = row
                total.update(row["counts"])
            if not rows:
                continue
            precision = total["correct_unique"] / max(1, total["accepted"])
            recall = total["correct_unique"] / max(1, total["gold_edges"])
            arms[folder.name] = {"n_cases": len(rows), "complete": len(rows) == len(cases),
                                 "total": dict(total), "precision": precision, "recall": recall,
                                 "f1": 2*precision*recall/(precision+recall) if precision+recall else 0,
                                 "cases": rows}
            print(rootname, folder.name, len(rows), "P", round(precision, 3), "R", round(recall, 3),
                  "extra", total["extra_strict"], "missing", total["missing_directed"], "exact", total["exact_graph"])
        result[rootname] = arms
    (HERE / "strict_graph_audit.json").write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    run()
