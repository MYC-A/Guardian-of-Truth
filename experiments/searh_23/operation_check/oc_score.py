"""Scorer for the operation-check research. Reads frozen gold + raw arm
outputs and computes the S11 metric families:

  event discovery (role P/R, span-only recall, check->operation promotion)
  tool grounding   (top-1/top-3, pair accuracy, type confusion, wrong tool)
  condition binding (correct / extra / missing edges)
  relation         (accuracy on gold endpoint pairs; per-arm conditional)
  calibration      (TRUE / wrong / UNKNOWN counts)
  rename robustness (same metrics on the renamed suite, deltas)
  cost             (calls, tokens, wall time from _usage.json)

Gold conventions for pair labels: tool in governed_tools ->
ROLE_TO_PAIR[event.role]; otherwise UNRELATED. Anaphoric gold edges accept
the operation endpoint matching either operation_span or ref_span.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import FROZEN_DIR, OUTPUTS_DIR, l1, all_occurrences, l1_occurrences, iou

ROLE_TO_PAIR = {
    "OPERATION_EFFECT": "REALIZES_OPERATION",
    "PRECONDITION_CHECK": "CHECKS_PRECONDITION",
    "STATE_OBSERVATION": "OBSERVES_STATE",
    "COMMUNICATION": "COMMUNICATES",
}


# ------------------------------------------------------------------ matching

def span_ranges(policy: str, span: str) -> list[tuple[int, int]]:
    if not isinstance(span, str) or not span or span not in policy:
        return l1_occurrences(policy, span) if isinstance(span, str) else []
    return all_occurrences(policy, span)


def best_iou(policy: str, a: str, b: str) -> float:
    ra, rb = span_ranges(policy, a), span_ranges(policy, b)
    if not ra or not rb:
        return 0.0
    return max(iou(x, y) for x in ra for y in rb)


def spans_equivalent(policy: str, a: str, b: str) -> bool:
    if not isinstance(a, str) or not isinstance(b, str):
        return False
    if l1(a) == l1(b) and l1(a):
        return True
    return best_iou(policy, a, b) >= 0.5


def match_events(policy: str, predicted: list[dict], gold_events: list[dict]):
    """One-to-one matching: L1 equality first, then IoU >= 0.5 greedy."""
    matches = []  # (pred_idx, gold_idx, method)
    used_pred, used_gold = set(), set()
    for i, p in enumerate(predicted):
        for j, g in enumerate(gold_events):
            if i in used_pred or j in used_gold:
                continue
            if isinstance(p.get("span"), str) and l1(p["span"]) == l1(g["source_span"]):
                matches.append((i, j, "l1"))
                used_pred.add(i)
                used_gold.add(j)
    for i, p in enumerate(predicted):
        if i in used_pred:
            continue
        best_j, best_v = None, 0.0
        for j, g in enumerate(gold_events):
            if j in used_gold:
                continue
            v = best_iou(policy, p.get("span", ""), g["source_span"])
            if v >= 0.5 and v > best_v:
                best_j, best_v = j, v
        if best_j is not None:
            matches.append((i, best_j, "iou"))
            used_pred.add(i)
            used_gold.add(best_j)
    return matches, used_pred, used_gold


# ------------------------------------------------------------------ arm kinds

def load_arm(arm: str, which: str) -> dict[str, dict]:
    d = OUTPUTS_DIR / (arm + ("_renamed" if which == "renamed" else ""))
    out = {}
    if not d.is_dir():
        return out
    for f in d.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        out[data["case_id"]] = data
    return out


def score_events(arm_data, gold_map, suite):
    per_role = {}
    totals = {"gold_events": 0, "pred_events": 0, "matched": 0,
              "matched_role_correct": 0, "span_only_recall": 0,
              "unknown_predictions": 0, "check_promoted": 0,
              "gold_checks_found": 0}
    roles = ["OPERATION_EFFECT", "PRECONDITION_CHECK", "STATE_OBSERVATION",
             "COMMUNICATION", "OTHER"]
    for r in roles:
        per_role[r] = {"gold": 0, "matched": 0, "role_correct": 0, "predicted": 0}
    case_diag = {}
    for case in suite:
        cid = case["case_id"]
        g = gold_map.get(cid)
        a = arm_data.get(cid)
        if g is None or a is None:
            case_diag[cid] = {"error": "missing arm output"}
            continue
        policy = case["policy"]
        gold_events = g["candidate_events"]
        if "events" not in a:
            case_diag[cid] = {"error": "no events field"}
            continue
        predicted = a["events"]
        matches, used_pred, used_gold = match_events(policy, predicted, gold_events)
        diag = {"matched": len(matches), "gold": len(gold_events),
                "predicted": len(predicted), "per_event": []}
        totals["gold_events"] += len(gold_events)
        totals["pred_events"] += len(predicted)
        totals["matched"] += len(matches)
        totals["span_only_recall"] += len(matches)
        for j, gev in enumerate(gold_events):
            per_role[gev["role"]]["gold"] += 1
            if gev["role"] in {"PRECONDITION_CHECK", "STATE_OBSERVATION"}:
                totals["gold_checks_found"] += 1
        for i, pev in enumerate(predicted):
            if pev.get("role") == "UNKNOWN":
                totals["unknown_predictions"] += 1
        for i, j, method in matches:
            gev = gold_events[j]
            pev = predicted[i]
            role_ok = pev.get("role") == gev["role"]
            per_role[gev["role"]]["matched"] += 1
            if role_ok:
                per_role[gev["role"]]["role_correct"] += 1
                totals["matched_role_correct"] += 1
            else:
                if gev["role"] in {"PRECONDITION_CHECK", "STATE_OBSERVATION"} and \
                        pev.get("role") == "OPERATION_EFFECT":
                    totals["check_promoted"] += 1
            diag["per_event"].append({
                "gold_span": gev["source_span"], "gold_role": gev["role"],
                "pred_span": pev.get("span"), "pred_role": pev.get("role"),
                "method": method, "role_ok": role_ok})
        for i, pev in enumerate(predicted):
            per_role[pev.get("role", "UNKNOWN")]["predicted"] += 1
        case_diag[cid] = diag
    metrics = {"per_role": per_role, **totals}
    # derive P/R
    deriv = {}
    for r in roles:
        gold_n = per_role[r]["gold"]
        pred_n = per_role[r]["predicted"]
        m = per_role[r]["matched"]
        rc = per_role[r]["role_correct"]
        deriv[r] = {
            "recall_span": round(m / gold_n, 4) if gold_n else None,
            "recall_role": round(rc / gold_n, 4) if gold_n else None,
            "precision_role": round(rc / pred_n, 4) if pred_n else None,
        }
    metrics["pr"] = deriv
    metrics["case_diag"] = case_diag
    return metrics


def score_grounding(arm_data, gold_map, suite, which_key):
    """Ranking metrics for E/F/G on gold spans (E: embed_rank, F: rerank_rank,
    G: rank by NLI max_e) + G pair-label accuracy + type confusion."""
    out = {}
    for rank_key, arm_name in (("embed_rank", "E_embed"),
                               ("rerank_rank", "F_cross"),
                               ("nli", "G_nli")):
        stats = {"pairs": 0, "top1": 0, "top3": 0, "unknown_top": 0,
                 "check_to_mutate": 0, "check_events": 0,
                 "wrong_op_tool": 0, "op_events": 0}
        pair_stats = None
        if rank_key == "nli":
            pair_stats = {"pairs": 0, "correct": 0, "unknown": 0,
                          "unrelated_correct": 0, "unrelated_total": 0}
        for case in suite:
            cid = case["case_id"]
            g = gold_map.get(cid)
            a = arm_data.get(cid)
            if not g or not a:
                continue
            tool_types = g.get("tool_types", {})
            for rec in a.get("gold_span_grounding", []):
                span = rec["span"]
                gev = next((e for e in g["candidate_events"]
                            if spans_equivalent(case["policy"], e["source_span"], span)),
                           None)
                if gev is None:
                    continue
                governed = set(gev["governed_tools"])
                if rank_key == "nli":
                    nli = rec.get("nli", {})
                    ranked = sorted(nli.items(),
                                    key=lambda kv: -kv[1].get("max_e", 0.0))
                    ranking = [[name, per.get("max_e")] for name, per in ranked]
                    for tool, per in nli.items():
                        expected = ROLE_TO_PAIR.get(gev["role"], "UNRELATED") \
                            if tool in governed else "UNRELATED"
                        pair_stats["pairs"] += 1
                        if per.get("label") == expected:
                            pair_stats["correct"] += 1
                        if expected == "UNRELATED":
                            pair_stats["unrelated_total"] += 1
                            if per.get("label") == "UNRELATED":
                                pair_stats["unrelated_correct"] += 1
                        if per.get("label") == "UNKNOWN":
                            pair_stats["unknown"] += 1
                else:
                    ranking = rec.get(rank_key, [])
                stats["pairs"] += 1
                if not ranking:
                    stats["unknown_top"] += 1
                    continue
                top = [row[0] for row in ranking[:3]]
                if ranking and ranking[0][0] in governed:
                    stats["top1"] += 1
                if any(t in governed for t in top):
                    stats["top3"] += 1
                if gev["role"] in {"PRECONDITION_CHECK", "STATE_OBSERVATION"}:
                    stats["check_events"] += 1
                    if ranking and tool_types.get(ranking[0][0]) == "mutate":
                        stats["check_to_mutate"] += 1
                if gev["role"] == "OPERATION_EFFECT":
                    stats["op_events"] += 1
                    if ranking and ranking[0][0] not in governed:
                        stats["wrong_op_tool"] += 1
        block = {k: v for k, v in stats.items()}
        if pair_stats:
            block["pair_accuracy"] = round(pair_stats["correct"] / pair_stats["pairs"], 4) \
                if pair_stats["pairs"] else None
            block["pair_unrelated_accuracy"] = round(
                pair_stats["unrelated_correct"] / pair_stats["unrelated_total"], 4) \
                if pair_stats["unrelated_total"] else None
            block["pair_unknown"] = pair_stats["unknown"]
            block["pair_total"] = pair_stats["pairs"]
        out[arm_name] = block
    return out


def score_pairs(arm_data, gold_map, suite):
    """A2/I2 narrow pair classification metrics."""
    stats = {"pairs": 0, "correct": 0, "unknown": 0, "unrelated_total": 0,
             "unrelated_correct": 0, "positive_correct": 0, "positive_total": 0,
             "false_positive": 0, "per_label": {}}
    for case in suite:
        cid = case["case_id"]
        g, a = gold_map.get(cid), arm_data.get(cid)
        if not g or not a:
            continue
        for rec in a.get("pairs", []):
            gev = next((e for e in g["candidate_events"]
                        if spans_equivalent(case["policy"], e["source_span"], rec["span"])),
                       None)
            if gev is None:
                continue
            governed = set(gev["governed_tools"])
            expected = ROLE_TO_PAIR.get(gev["role"], "UNRELATED") \
                if rec["tool"] in governed else "UNRELATED"
            stats["pairs"] += 1
            label = rec.get("label")
            stats["per_label"].setdefault(label, {"n": 0, "correct": 0})
            stats["per_label"][label]["n"] += 1
            if label == expected:
                stats["correct"] += 1
                stats["per_label"][label]["correct"] += 1
            if expected == "UNRELATED":
                stats["unrelated_total"] += 1
                if label == "UNRELATED":
                    stats["unrelated_correct"] += 1
                elif label in ROLE_TO_PAIR.values():
                    stats["false_positive"] += 1
            else:
                stats["positive_total"] += 1
                if label == expected:
                    stats["positive_correct"] += 1
            if label == "UNKNOWN":
                stats["unknown"] += 1
    stats["accuracy"] = round(stats["correct"] / stats["pairs"], 4) if stats["pairs"] else None
    stats["positive_accuracy"] = round(stats["positive_correct"] / stats["positive_total"], 4) \
        if stats["positive_total"] else None
    stats["unrelated_accuracy"] = round(stats["unrelated_correct"] / stats["unrelated_total"], 4) \
        if stats["unrelated_total"] else None
    return stats


def score_edges(arm_data, gold_map, suite):
    stats = {"gold_edges": 0, "correct": 0, "extra": 0, "missing": 0,
             "relation_correct_given_endpoints": 0, "endpoint_matched": 0,
             "per_case": {}}
    for case in suite:
        cid = case["case_id"]
        g, a = gold_map.get(cid), arm_data.get(cid)
        if not g or not a:
            continue
        policy = case["policy"]
        gold_edges = g["condition_edges"]
        pred_edges = a.get("edges", [])
        used = set()
        cc = {"gold": len(gold_edges), "pred": len(pred_edges), "correct": 0}
        for pe in pred_edges:
            matched = None
            for k, ge in enumerate(gold_edges):
                if k in used:
                    continue
                cond_ok = spans_equivalent(policy, pe.get("condition_span", ""),
                                           ge["condition_span"])
                op_ok = spans_equivalent(policy, pe.get("operation_span", ""),
                                         ge["operation_span"]) or \
                    ("ref_span" in ge and spans_equivalent(
                        policy, pe.get("operation_span", ""), ge["ref_span"]))
                # anaphoric condition refs: gold ref_span disambiguates too
                cond_ok = cond_ok or ("ref_span" in ge and spans_equivalent(
                    policy, pe.get("condition_span", ""), ge["ref_span"]))
                if cond_ok and op_ok:
                    matched = (k, ge)
                    break
            if matched:
                used.add(matched[0])
                stats["correct"] += 1
                cc["correct"] += 1
                stats["endpoint_matched"] += 1
                if pe.get("relation") == matched[1]["relation"]:
                    stats["relation_correct_given_endpoints"] += 1
            else:
                stats["extra"] += 1
        stats["gold_edges"] += len(gold_edges)
        stats["missing"] += len(gold_edges) - len(used)
        stats["per_case"][cid] = cc
    return stats


def score_relation(arm_data, gold_map, suite):
    stats = {"gold_pairs": 0, "gold_correct": 0, "negative_pairs": 0,
             "negative_correct": 0, "unknown": 0, "per_case": {}}
    for case in suite:
        cid = case["case_id"]
        g, a = gold_map.get(cid), arm_data.get(cid)
        if not g or not a:
            continue
        cc = {}
        for ans in a.get("answers", []):
            kind = ans.get("kind")
            ok = ans.get("predicted") == ans.get("gold_relation")
            if kind == "gold":
                stats["gold_pairs"] += 1
                stats["gold_correct"] += int(ok)
            else:
                stats["negative_pairs"] += 1
                stats["negative_correct"] += int(ok)
            if ans.get("predicted") == "UNKNOWN":
                stats["unknown"] += 1
            cc.setdefault(kind, []).append({"ok": ok, "pred": ans.get("predicted"),
                                            "gold": ans.get("gold_relation")})
        stats["per_case"][cid] = cc
    stats["gold_accuracy"] = round(stats["gold_correct"] / stats["gold_pairs"], 4) \
        if stats["gold_pairs"] else None
    stats["negative_accuracy"] = round(stats["negative_correct"] / stats["negative_pairs"], 4) \
        if stats["negative_pairs"] else None
    return stats


def tool_grounding_of_matched_events(arm_data, gold_map, suite):
    """For e2e arms: among matched OPERATION_EFFECT events, is any governed
    tool correct?"""
    stats = {"matched_ops": 0, "tool_correct": 0, "matched_checks": 0,
             "check_tool_mutate": 0}
    for case in suite:
        cid = case["case_id"]
        g, a = gold_map.get(cid), arm_data.get(cid)
        if not g or not a or "events" not in a:
            continue
        policy = case["policy"]
        matches, _, _ = match_events(policy, a["events"], g["candidate_events"])
        tool_types = g.get("tool_types", {})
        for i, j, _m in matches:
            gev, pev = g["candidate_events"][j], a["events"][i]
            tools = pev.get("governed_tools", [])
            if gev["role"] == "OPERATION_EFFECT":
                stats["matched_ops"] += 1
                if any(t in gev["governed_tools"] for t in tools):
                    stats["tool_correct"] += 1
            if gev["role"] in {"PRECONDITION_CHECK", "STATE_OBSERVATION"}:
                stats["matched_checks"] += 1
                if any(tool_types.get(t) == "mutate" for t in tools):
                    stats["check_tool_mutate"] += 1
    return stats


def load_gold(which: str):
    name = "gold.json" if which == "original" else "gold_renamed.json"
    return {g["case_id"]: g for g in json.loads((FROZEN_DIR / name).read_text(encoding="utf-8"))}


def load_suite(which: str):
    name = "frozen_cases.json" if which == "original" else "frozen_cases_renamed.json"
    return json.loads((FROZEN_DIR / name).read_text(encoding="utf-8"))


def usage_of(arm: str, which: str):
    p = OUTPUTS_DIR / (arm + ("_renamed" if which == "renamed" else "")) / "_usage.json"
    if p.is_file():
        return json.loads(p.read_text(encoding="utf-8"))
    return {}


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    gold_map = load_gold(which)
    suite = load_suite(which)
    score = {"suite": which, "arms": {}}

    e2e_arms = ["A_e2e", "I_e2e", "H_hybrid", "Hplus_hybrid"]
    struct_arms = ["B_dependency", "C_amr", "D_srl"]

    for arm in struct_arms + e2e_arms:
        data = load_arm(arm, which)
        if not data:
            continue
        # structural arms: role field is role_hypothesis
        norm = {}
        for cid, rec in data.items():
            events = []
            for ev in rec.get("events", []):
                e = dict(ev)
                e["role"] = ev.get("role_hypothesis", ev.get("role", "UNKNOWN"))
                events.append(e)
            norm[cid] = {**rec, "events": events}
        block = {"event_discovery": score_events(norm, gold_map, suite),
                 "edges": score_edges(norm, gold_map, suite)}
        if arm in e2e_arms:
            block["matched_tool_grounding"] = tool_grounding_of_matched_events(
                norm, gold_map, suite)
        if arm == "C_amr":
            aligned = sum(1 for rec in data.values()
                          for ev in rec.get("events", []) if ev.get("span"))
            total = sum(len(rec.get("events", [])) for rec in data.values())
            block["amr_alignment_coverage"] = round(aligned / total, 4) if total else None
        block["usage"] = usage_of(arm, which)
        score["arms"][arm] = block

    efg = load_arm("EFG_grounding", which)
    if efg:
        score["arms"]["grounding_components"] = {
            "ranking": score_grounding(efg, gold_map, suite, which),
            "tool_type_probe": tool_type_probe_metrics(efg, gold_map),
        }

    for arm in ("A2_pairs", "I2_pairs"):
        data = load_arm(arm, which)
        if data:
            score["arms"][arm] = {"pairs": score_pairs(data, gold_map, suite),
                                  "usage": usage_of(arm, which)}

    for arm in ("relation", "relation_strong"):
        data = load_arm(arm, which)
        if data:
            score["arms"][arm] = {"relation_only": score_relation(data, gold_map, suite),
                                  "usage": usage_of(arm, which)}

    out = OUTPUTS_DIR / ("score.json" if which == "original" else "score_renamed.json")
    out.write_text(json.dumps(score, ensure_ascii=False, indent=1), encoding="utf-8")
    print("wrote", out)
    # compact summary
    for arm, block in score["arms"].items():
        if "event_discovery" in block:
            m = block["event_discovery"]
            print(f"{arm}: matched {m['matched']}/{m['gold_events']} "
                  f"role-correct {m['matched_role_correct']} "
                  f"unknown {m['unknown_predictions']} "
                  f"check->op {m['check_promoted']}")
        if "edges" in block and isinstance(block.get("edges"), dict) and \
                block["edges"].get("gold_edges"):
            e = block["edges"]
            print(f"  edges: {e['correct']}/{e['gold_edges']} correct, "
                  f"extra {e['extra']}, missing {e['missing']}")


def tool_type_probe_metrics(efg, gold_map):
    """Can NLI recover the designer tool type from description alone?"""
    stats = {"tools": 0, "correct": 0, "per_type": {}}
    for cid, rec in efg.items():
        g = gold_map.get(cid)
        if not g:
            continue
        for tool, per in rec.get("tool_type_probe", {}).items():
            gold_type = g.get("tool_types", {}).get(tool)
            if gold_type is None:
                continue
            stats["tools"] += 1
            stats["per_type"].setdefault(gold_type, {"n": 0, "correct": 0})
            stats["per_type"][gold_type]["n"] += 1
            if per.get("top") == gold_type:
                stats["correct"] += 1
                stats["per_type"][gold_type]["correct"] += 1
    stats["accuracy"] = round(stats["correct"] / stats["tools"], 4) if stats["tools"] else None
    return stats


if __name__ == "__main__":
    main()
