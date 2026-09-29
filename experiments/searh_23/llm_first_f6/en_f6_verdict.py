"""F6 ARM H + ARM I — multiple interpretations and verdict-aware
escalation.

ARM H (directive section 12): interpretations = the two independent
extractor parses (mistral / codestral), each carried through the FULL
frozen chain (rawsan / rawsan2). Measures:
  - how many policies have >1 interpretation (any node-set divergence);
  - how many divergences change the licensed EDGE SET (the graph);
  - the edge-set delta mapped to gold-cid endpoint pairs.

ARM I (directive section 13): the verdict proxy. The Guardian verdict
is computed from the licensed policy graph; two interpretations are
VERDICT-EQUIVALENT when their licensed edge sets (mapped to gold-cid
endpoint pairs) are equal, and VERDICT-CRITICAL when they differ.
The cascade: extraction -> interpretations -> downstream evaluation ->
verdict agreement? YES -> stop. NO -> escalate (judge / second model /
UNKNOWN).

Honest scope note: F6 has no execution traces, so the 'final Guardian
verdict' is proxied by the licensed edge set; a trace-level verdict
experiment goes to F7.

Run: python3 en_f6_verdict.py
"""
from __future__ import annotations

import json
from collections import Counter
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
STACK = HERE / "outputs" / "stack"
OUT = HERE / "outputs" / "score"
OUT.mkdir(parents=True, exist_ok=True)


def load_cases():
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / "level_f6_cases.json").read_text())}


def label_of(case, node):
    """Dominant gold cid overlap label for a stack node."""
    best = Counter()
    start = node.get("start")
    end = node.get("end", start + len(node.get("span", "")) if start
                   is not None else 0)
    if start is None:
        return None
    for m in case["mentions"]:
        if not m.get("cid") or m["type"] in ("ENTITY", "ARTIFACT"):
            continue
        inter = max(0, min(end, m["end"]) - max(start, m["start"]))
        if inter > 0:
            best[m["cid"]] += inter
    if not best:
        return None
    top = max(best.values())
    winners = [c for c, v in best.items() if v == top]
    return winners[0] if len(winners) == 1 else "MIXED"


def edge_set(case, data):
    """Licensed edges as gold-cid endpoint pairs (directed, honoring the
    edge 'direction' field exactly like w1_score.score_case)."""
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}
    edges = set()
    for e in data.get("edges", []):
        u, v = nodes.get(e["u"]), nodes.get(e["v"])
        if u is None or v is None:
            continue
        direction = e.get("direction", "A_TO_B")
        if direction == "B_TO_A":
            u, v = v, u
        lu, lv = label_of(case, u), label_of(case, v)
        if not lu or not lv or "MIXED" in (lu, lv):
            continue
        edges.add((lu, lv))
    return edges


def main():
    cases = load_cases()
    rows = []
    tot = Counter()
    for cid, case in cases.items():
        fa = STACK / "f6_rawsan" / f"{cid}.json"
        fb = STACK / "f6_rawsan2" / f"{cid}.json"
        if not (fa.exists() and fb.exists()):
            continue
        da = json.loads(fa.read_text(encoding="utf-8"))
        db = json.loads(fb.read_text(encoding="utf-8"))
        na = {(label_of(case, n), n["span"]) for n in da.get("nodes", [])}
        nb = {(label_of(case, n), n["span"]) for n in db.get("nodes", [])}
        la, lb = edge_set(case, da), edge_set(case, db)
        same_nodes = {n["span"] for n in da.get("nodes", [])} == \
            {n["span"] for n in db.get("nodes", [])}
        verdict_eq = la == lb
        gold = {(e["from_cid"], e["to_cid"]) for e in
                case["normative_edges"]}
        # union-correctness: edges either parse gets right
        correct_a = len(la & gold)
        correct_b = len(lb & gold)
        tot["cases"] += 1
        tot["multi_interp"] += int(na != nb)
        tot["node_same"] += int(same_nodes)
        tot["verdict_eq"] += int(verdict_eq)
        tot["verdict_critical"] += int(not verdict_eq)
        tot["edges_a"] += len(la)
        tot["edges_b"] += len(lb)
        tot["correct_a"] += correct_a
        tot["correct_b"] += correct_b
        tot["correct_union"] += len((la | lb) & gold)
        tot["gold"] += len(gold)
        rows.append({"case_id": cid, "node_divergence": na != nb,
                     "same_node_spans": same_nodes,
                     "verdict_equivalent": verdict_eq,
                     "edges_a": sorted(la), "edges_b": sorted(lb),
                     "gold": sorted(gold),
                     "correct_a": correct_a, "correct_b": correct_b,
                     "correct_union": len((la | lb) & gold)})
    out = {"n_cases": tot["cases"],
           "interpretations_differ (node sets)": tot["multi_interp"],
           "node_spans_identical": tot["node_same"],
           "verdict_equivalent": tot["verdict_eq"],
           "verdict_critical": tot["verdict_critical"],
           "edge_recall_a": round(tot["correct_a"] /
                                  max(1, tot["gold"]), 3),
           "edge_recall_b": round(tot["correct_b"] /
                                  max(1, tot["gold"]), 3),
           "edge_recall_union": round(tot["correct_union"] /
                                      max(1, tot["gold"]), 3),
           "per_case": rows}
    (OUT / "verdict.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "per_case"},
                     indent=1))
    for r in rows:
        if not r["verdict_equivalent"]:
            print(f"  VERDICT-CRITICAL {r['case_id']}: "
                  f"A={r['edges_a']} B={r['edges_b']} gold={r['gold']}")


if __name__ == "__main__":
    main()
