"""W1 strict scorer for W1_DOWN_* outputs (same strict semantics as
lf_score_trackB: duplicate no recall, reverse not correct, contaminated no
credit, wrong endpoint no partial credit; direction must be effective).

Run: python3 w1_score.py [W1_DOWN_ARM ...]   (LF_SUITE=main|f2)
"""
from __future__ import annotations

import json
import os
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
OUT = HERE / "outputs"


def load_gold() -> dict[str, dict]:
    fname = ("level_f2_cases.json" if os.environ.get("LF_SUITE") == "f2"
             else "level_f_cases.json")
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}


def node_label(case: dict, node: dict) -> str | None:
    by_span: dict[str, list] = defaultdict(list)
    for m in case["mentions"]:
        by_span.setdefault(m["span"].strip(), []).append(m)
    labels = set()
    matched_any = False
    for span in node.get("member_spans", []) or [node.get("span", "")]:
        for m in by_span.get((span or "").strip(), []):
            matched_any = True
            if m.get("cid"):
                labels.add(m["cid"])
            else:
                labels.add("NON_EVENT")
    if not matched_any:
        return None
    if len(labels) == 1:
        return next(iter(labels))
    return "MIXED" if len(labels) > 1 else None


def score_case(case: dict, data: dict) -> dict:
    gold = {(e["from_cid"], e["to_cid"]): set(e["acceptable"])
            for e in case["normative_edges"]}
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}
    hits, typed_hits = set(), set()
    count = Counter()
    errors = []
    for i, edge in enumerate(data.get("edges", [])):
        u, v = nodes.get(edge["u"]), nodes.get(edge["v"])
        if u is None or v is None:
            count["extra_strict"] += 1
            errors.append({"index": i, "reason": "missing_node"})
            continue
        lu, lv = node_label(case, u), node_label(case, v)
        direction = edge.get("direction", "A_TO_B")
        if direction == "B_TO_A":
            a, b, la, lb = v, u, lv, lu
        elif direction == "A_TO_B":
            a, b, la, lb = u, v, lu, lv
        else:
            count["extra_strict"] += 1
            errors.append({"index": i, "reason": "unknown_direction"})
            continue
        reason = None
        if la in (None, "JUNK", "MIXED", "NON_EVENT") or \
                lb in (None, "JUNK", "MIXED", "NON_EVENT"):
            count["contaminated_endpoint_edges"] += 1
            reason = "contaminated_or_junk_endpoint"
        else:
            if (la, lb) in gold:
                if (la, lb) in hits:
                    count["duplicate_supported_edges"] += 1
                    reason = "duplicate_gold_edge"
                else:
                    hits.add((la, lb))
                    count["correct_unique"] += 1
                if edge.get("relation") in gold[(la, lb)]:
                    typed_hits.add((la, lb))
            elif (lb, la) in gold:
                count["reverse_edges"] += 1
                reason = "wrong_direction"
            else:
                reason = "unsupported_edge"
        if reason:
            count["extra_strict"] += 1
            errors.append({"index": i, "from": la, "to": lb,
                           "reason": reason,
                           "u_span": edge.get("u_span"),
                           "v_span": edge.get("v_span"),
                           "relation": edge.get("relation"),
                           "direction": direction})
    count["accepted"] = len(data.get("edges", []))
    count["gold_edges"] = len(gold)
    count["missing_directed"] = len(set(gold) - hits)
    count["typed_unique"] = len(typed_hits)
    count["nodes"] = len(nodes)
    count["exact_graph"] = int(len(hits) == len(gold)
                               and count["extra_strict"] == 0)
    count["exact_typed_graph"] = int(count["exact_graph"]
                                     and len(typed_hits) == len(gold))
    return {"counts": dict(count), "errors": errors,
            "missing": [list(x) for x in sorted(set(gold) - hits)]}


def main() -> None:
    gold = load_gold()
    arms = sys.argv[1:] or [d.name for d in sorted(OUT.glob("W1_DOWN_*"))]
    report = {}
    for arm in arms:
        d = OUT / arm
        if not d.exists():
            print(arm, "MISSING")
            continue
        total = Counter()
        per_case = {}
        for cid, case in gold.items():
            f = d / f"{cid}.json"
            if not f.exists():
                continue
            row = score_case(case, json.loads(f.read_text(encoding="utf-8")))
            per_case[cid] = row
            total.update(row["counts"])
        if not per_case:
            continue
        correct = total["correct_unique"]
        extra = total["extra_strict"]
        missing = total["missing_directed"]
        p = correct / (correct + extra) if correct + extra else 0.0
        r = correct / (correct + missing) if correct + missing else 0.0
        report[arm] = {
            "cases": len(per_case), "P": round(p, 3), "R": round(r, 3),
            "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
            "correct": correct, "extra": extra, "missing": missing,
            "typed": total["typed_unique"],
            "exact_graphs": sum(v["counts"]["exact_graph"]
                                for v in per_case.values()),
            "exact_typed": sum(v["counts"]["exact_typed_graph"]
                               for v in per_case.values()),
            "contaminated": total.get("contaminated_endpoint_edges", 0),
            "reverse": total.get("reverse_edges", 0),
            "duplicate": total.get("duplicate_supported_edges", 0),
            "nodes": total.get("nodes", 0), "per_case": per_case}
        print(f"{arm:24s} P={p:.3f} R={r:.3f} correct={correct} "
              f"extra={extra} missing={missing} typed={total['typed_unique']} "
              f"exact={report[arm]['exact_graphs']}/{len(per_case)} "
              f"nodes={total.get('nodes', 0)}")
    (OUT / f"w1_score_{os.environ.get('LF_SUITE', 'main')}.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")


if __name__ == "__main__":
    main()
