"""W1 loss-budget diagnostic (deterministic, local, no LLM calls).

Directive §38: after each downstream run, count how many gold edges are lost
to each failure category and where extra edges come from. This tool replays
the saved DOWN_<ARM>_<EV> outputs against gold and attributes every loss to
a category by inspecting the saved per-edge detail (verify reasons, judge
notes) plus node alignment.

Categories (gold-edge loss):
  MISSING_MENTION      - no candidate node aligned to the gold cid at all
  NODE_CONTAMINATED    - aligned node exists but is MIXED / junk-bearing
  NO_CE_PAIR           - both nodes clean but CE band < 0.35 (pair never proposed)
  CERT_FAIL_<reason>   - certificate deterministically rejected (saved detail)
  JUDGE_FAIL           - verifier q3 no / q1q2 not verbatim
  REVERSE_DIRECTION    - licensed with wrong direction
  WRONG_ENDPOINT       - licensed between wrong cids (unsupported pair)

Extra-edge sources: junk endpoint / contaminated / unsupported licensed /
reverse / duplicate / unknown direction.

Run (server or local): python3 w1_diag.py [ARM_EV ...]   (default: all)
Env: LF_SUITE=main|f2
"""
from __future__ import annotations

import json
import os
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
OUT = IE / "outputs"
CE_BAND = 0.35


def load_gold() -> dict[str, dict]:
    fname = ("level_f2_cases.json" if os.environ.get("LF_SUITE") == "f2"
             else "level_f_cases.json")
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}


def node_label(case: dict, node: dict) -> str | None:
    """Same clean/junk semantics as lf_score_trackB."""
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


def node_defects(case: dict, node: dict, policy: str) -> list[str]:
    """Deterministic node-quality defects (independent of gold labels)."""
    defects = []
    for span in node.get("member_spans", []) or [node.get("span", "")]:
        if span and span not in policy:
            defects.append("ungrounded_member_span")
            break
    spans = [s for s in node.get("member_spans", []) or
             [node.get("span", "")] if s]
    for s in spans:
        if re.match(r"^(only when|only after|after|before|when|if|unless|"
                    r"until|provided that)\b", s.strip(), re.I):
            defects.append("leading_connective_in_span")
            break
    for s in spans:
        if len(re.findall(r"\b(and|or|then)\b", s)) >= 1 and \
                s.count(" ") >= 8:
            defects.append("possible_conjunction_span")
            break
    if node.get("type") == "STATE_OR_FACET":
        defects.append("state_node")
    return defects


def diagnose_case(case: dict, data: dict) -> dict:
    gold = {(e["from_cid"], e["to_cid"]): e for e in case["normative_edges"]}
    nodes = {n["node_id"]: n for n in data.get("nodes", [])}
    # which gold cids have a clean aligned node?
    cid_nodes: dict[str, list] = defaultdict(list)
    for n in nodes.values():
        lab = node_label(case, n)
        if lab and lab not in ("MIXED", "NON_EVENT"):
            cid_nodes[lab].append(n["node_id"])
    licensed = {}
    for edge in data.get("edges", []):
        u, v = nodes.get(edge["u"]), nodes.get(edge["v"])
        if u is None or v is None:
            continue
        lu, lv = node_label(case, u), node_label(case, v)
        direction = edge.get("direction", "A_TO_B")
        if direction == "B_TO_A":
            a, b, la, lb = v, u, lv, lu
        else:
            a, b, la, lb = u, v, lu, lv
        licensed[(la, lb)] = edge
    loss = Counter()
    loss_detail = []
    for (x, y), ge in sorted(gold.items()):
        if (x, y) in licensed:
            # licensed but maybe wrong relation type (typed recall loss)
            if edge := licensed[(x, y)]:
                if edge.get("relation") not in ge.get("acceptable", []):
                    loss["WRONG_RELATION_TYPE"] += 1
            continue
        # find where it died
        nx, ny = cid_nodes.get(x, []), cid_nodes.get(y, [])
        if not nx or not ny:
            loss["MISSING_MENTION" if not nx and not ny else
                 "MISSING_ONE_ENDPOINT"] += 1
            loss_detail.append({"edge": [x, y],
                                "reason": "no clean aligned node",
                                "x_nodes": nx, "y_nodes": ny})
            continue
        # both endpoints exist as clean nodes: find the saved pair record
        found = None
        for edge in data.get("edges", []):
            u, v = nodes.get(edge["u"]), nodes.get(edge["v"])
            if u is None or v is None:
                continue
            su = set(u.get("member_spans", []) or [u.get("span")])
            sv = set(v.get("member_spans", []) or [v.get("span")])
            gx = {m["span"] for m in case["mentions"] if m.get("cid") == x}
            gy = {m["span"] for m in case["mentions"] if m.get("cid") == y}
            if (su & gx and sv & gy) or (sv & gx and su & gy):
                found = edge
                break
        if found is None:
            # never proposed: CE band or pair never formed
            loss["NO_CE_PAIR"] += 1
            loss_detail.append({"edge": [x, y], "reason":
                                "pair not in accepted edges (CE or dropped)",
                                "ce_available": None})
            continue
        det = found.get("detail", {})
        note = det.get("note") or det.get("verify", {}).get("reason") or \
            det.get("certificate", {}).get("relation_text")
        if det.get("note") == "verifier_q3_no":
            loss["JUDGE_Q3_NO"] += 1
        elif det.get("note") == "verifier_q1q2_not_in_evidence":
            loss["JUDGE_Q1Q2_FAIL"] += 1
        elif det.get("verify", {}).get("verdict") == "UNSUPPORTED":
            loss[f"CERT_FAIL_{det.get('verify', {}).get('reason', '?')}"] += 1
        elif det.get("verify", {}).get("verdict") == "UNKNOWN":
            loss["CERT_UNKNOWN"] += 1
        else:
            loss["LICENSED_BUT_NOT_SCORED?"] += 1
        loss_detail.append({"edge": [x, y], "reason": str(note)[:120]})
    # extra edges
    extra = Counter()
    extra_detail = []
    for i, edge in enumerate(data.get("edges", [])):
        u, v = nodes.get(edge["u"]), nodes.get(edge["v"])
        if u is None or v is None:
            extra["missing_node_ref"] += 1
            continue
        lu, lv = node_label(case, u), node_label(case, v)
        direction = edge.get("direction", "A_TO_B")
        if direction == "B_TO_A":
            la, lb = lv, lu
        elif direction == "A_TO_B":
            la, lb = lu, lv
        else:
            extra["unknown_direction"] += 1
            extra_detail.append({"i": i, "why": "unknown_direction"})
            continue
        if la in (None, "JUNK", "MIXED", "NON_EVENT") or \
                lb in (None, "JUNK", "MIXED", "NON_EVENT"):
            # attribute to endpoint defect
            why = []
            for nn, lab in ((u, lu), (v, lv)):
                if lab in (None, "JUNK", "MIXED", "NON_EVENT"):
                    why.append((nn["node_id"],
                                node_defects(case, nn, case["policy"])))
            extra["junk_endpoint"] += 1
            extra_detail.append({"i": i, "why": "junk_endpoint", "detail": why})
        elif (la, lb) in gold or (lb, la) in gold:
            if (la, lb) in gold:
                extra["duplicate_or_typed"] += 1
            else:
                extra["reverse_direction"] += 1
                extra_detail.append({"i": i, "why": "reverse_direction",
                                     "pair": [la, lb]})
        elif la == lb:
            extra["self_loop"] += 1
        else:
            extra["unsupported_licensed"] += 1
            extra_detail.append({"i": i, "why": "unsupported_licensed",
                                 "pair": [la, lb]})
    # node quality summary
    nq = Counter()
    for n in nodes.values():
        lab = node_label(case, n)
        nq[f"node_label_{lab}"] += 1
        for d in node_defects(case, n, case["policy"]):
            nq[d] += 1
    return {"loss": dict(loss), "loss_detail": loss_detail,
            "extra": dict(extra), "extra_detail": extra_detail[:12],
            "node_quality": dict(nq),
            "gold_edges": len(gold), "licensed": len(data.get("edges", []))}


def main() -> None:
    arms = sys.argv[1:] or ["DOWN_LLM_SG_E3", "DOWN_LLM_SG_E1",
                            "DOWN_FULL_GOLD_E3"]
    gold = load_gold()
    suite = os.environ.get("LF_SUITE", "main")
    print(f"=== W1 loss budget (suite={suite}) ===")
    for arm in arms:
        d = OUT / arm
        if not d.exists():
            print(f"{arm}: MISSING")
            continue
        tot_loss, tot_extra, tot_nq = Counter(), Counter(), Counter()
        licensed = 0
        for cid, case in gold.items():
            f = d / f"{cid}.json"
            if not f.exists():
                continue
            r = diagnose_case(case, json.loads(f.read_text(encoding="utf-8")))
            tot_loss.update(r["loss"])
            tot_extra.update(r["extra"])
            tot_nq.update(r["node_quality"])
            licensed += r["licensed"]
        print(f"\n--- {arm} (licensed edges: {licensed}) ---")
        print("  GOLD-EDGE LOSS:", dict(tot_loss.most_common()))
        print("  EXTRA SOURCES:", dict(tot_extra.most_common()))
        print("  NODE QUALITY:", dict(tot_nq.most_common()))


if __name__ == "__main__":
    main()
