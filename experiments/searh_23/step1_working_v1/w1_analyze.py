"""W1 deep analysis: node alignment vs gold mentions + per-edge verdicts.

For every W1_DOWN output node:
  - exact match to a gold mention span (by string) -> gold cid
  - else: containment relations (node span contains gold mention / vice versa)
    -> PARTIAL_OVERLONG / PARTIAL_SUBSPAN
  - else: in-policy but no gold overlap -> SPURIOUS
  - else: not in policy -> UNGROUNDED

For every gold edge: where it died in the pair_log (stage + reason).

Run: python3 w1_analyze.py [ARM]   (LF_SUITE=main|f2)
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


def analyze_case(case: dict, data: dict) -> dict:
    gold_mentions = case["mentions"]
    by_span: dict[str, list] = defaultdict(list)
    for m in gold_mentions:
        by_span.setdefault(m["span"].strip(), []).append(m)
    policy = case["policy"]
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}

    def classify(span: str) -> tuple[str, str | None]:
        s = (span or "").strip()
        if not s:
            return ("EMPTY", None)
        if s in by_span:
            ms = by_span[s]
            cids = {m.get("cid") for m in ms}
            if len(cids) == 1 and None not in cids:
                return ("EXACT", next(iter(cids)))
            return ("EXACT_NON_EVENT", None)
        if s not in policy and s.lower() not in policy.lower():
            return ("UNGROUNDED", None)
        # containment vs gold mentions
        contains = [m for m in gold_mentions if m["span"].strip() in s
                    and m["span"].strip() != s]
        inside = [m for m in gold_mentions if s in m["span"].strip()
                  and m["span"].strip() != s]
        if contains:
            cids = {m.get("cid") for m in contains if m.get("cid")}
            return ("OVERLONG(" + ",".join(sorted(filter(None, cids))) + ")",
                    None)
        if inside:
            cids = {m.get("cid") for m in inside if m.get("cid")}
            return ("SUBSPAN(" + ",".join(sorted(filter(None, cids))) + ")",
                    None)
        return ("SPURIOUS", None)

    node_rows = []
    for n in data.get("nodes", []):
        spans = n.get("member_spans") or [n.get("span", "")]
        cat, cid = classify(n.get("span", ""))
        # also classify each member
        member_cats = [classify(s)[0] for s in spans if s]
        node_rows.append({
            "node_id": n["node_id"], "span": n.get("span"),
            "type": n.get("type"), "cat": cat, "cid": cid,
            "member_cats": member_cats,
            "members": n.get("members", []),
            "member_spans": spans})
    # per gold-cid coverage
    covered = {}
    for m in gold_mentions:
        if not m.get("cid"):
            continue
        hit = [r for r in node_rows if r["cat"] == "EXACT"
               and r["cid"] == m["cid"]]
        covered.setdefault(m["cid"], bool(hit))
        covered[m["cid"]] = covered[m["cid"]] or bool(hit)
    # gold edges: find pair records
    gold = {(e["from_cid"], e["to_cid"]): e for e in
            case["normative_edges"]}
    id2cid = {r["node_id"]: r["cid"] for r in node_rows}
    edge_status = {}
    for (x, y), ge in sorted(gold.items()):
        st = {"edge": (x, y), "acceptable": ge.get("acceptable")}
        for edge in data.get("edges", []):
            lu = id2cid.get(edge["u"])
            lv = id2cid.get(edge["v"])
            d = edge.get("direction", "A_TO_B")
            if d == "B_TO_A":
                a, b = lv, lu
            elif d == "A_TO_B":
                a, b = lu, lv
            else:
                a, b = lu, lv
            if (a, b) == (x, y):
                st["licensed"] = True
                st["relation"] = edge.get("relation")
                st["ok_type"] = edge.get("relation") in ge.get(
                    "acceptable", [])
                break
        if not st.get("licensed"):
            # find pair_log records mentioning these cids
            recs = []
            for pr in data.get("pairs", []):
                cu = id2cid.get(pr.get("u"))
                cv = id2cid.get(pr.get("v"))
                if x in (cu, cv) and y in (cu, cv):
                    recs.append({"stage": pr.get("stage"),
                                 "verify": pr.get("verify"),
                                 "reason": pr.get("verify_reason"),
                                 "judge": pr.get("judge_note"),
                                 "ce": pr.get("ce")})
            st["licensed"] = False
            st["pair_records"] = recs
            # endpoints missing?
            st["x_node"] = bool(covered.get(x))
            st["y_node"] = bool(covered.get(y))
        edge_status[f"{x}->{y}"] = st
    return {"node_rows": node_rows, "covered": covered,
            "edges": edge_status}


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "W1_DOWN_LLM_SG"
    gold = load_gold()
    d = OUT / arm
    if not d.exists():
        print(arm, "MISSING")
        return
    cats = Counter()
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        r = analyze_case(case, json.loads(f.read_text(encoding="utf-8")))
        print(f"\n===== {cid} =====")
        print("GOLD MENTIONS:")
        for m in case["mentions"]:
            print(f"   [{m.get('cid') or 'NON_EVENT'}] {m.get('type','')}: "
                  f"{m['span']!r}")
        print("NODES:")
        for nr in r["node_rows"]:
            cats[nr["cat"].split("(")[0]] += 1
            print(f"   {nr['node_id']} [{nr['cat']}] type={nr['type']} "
                  f"span={nr['span']!r}")
        print("COVERAGE:", {k: v for k, v in r["covered"].items()})
        print("EDGES:")
        for k, st in r["edges"].items():
            if st.get("licensed"):
                print(f"   {k}: LICENSED rel={st.get('relation')} "
                      f"ok_type={st.get('ok_type')} (gold acceptable: "
                      f"{st.get('acceptable')})")
            else:
                print(f"   {k}: NOT licensed. x_node={st.get('x_node')} "
                      f"y_node={st.get('y_node')}")
                for pr in st.get("pair_records", [])[:3]:
                    print(f"       pair: stage={pr.get('stage')} "
                          f"verify={pr.get('verify')} reason={pr.get('reason')} "
                          f"judge={pr.get('judge')} ce={pr.get('ce')}")
    print("\n==== NODE CATEGORY TOTALS ====")
    print(dict(cats.most_common()))


if __name__ == "__main__":
    main()
