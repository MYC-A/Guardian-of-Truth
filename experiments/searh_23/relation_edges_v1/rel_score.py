"""Score all relation-edges arms against the frozen gold.

Metric families (per suite):
  RETRIEVER   R1/R2/R3/R4: top-1 parent accuracy, recall@3, recall@5
              (per from-event with >= 1 gold parent; span-exact matching)
  DETECTION   DET-ce / DET-nli / DET-mistral / DET-codestral and post-hoc
              combos on the fixed ordered pair universe: TP/FP/FN edges,
              precision, recall, F1, UNKNOWN rate, false-edge rate.
              Gold labels are DIRECTIONAL: pair (a,b) is positive iff a gold
              edge a->b exists; the reversed pair of an edge is negative.
  CLASSIFICATION  CLS-mistral / CLS-codestral on gold-positive pairs only
              (correct endpoints, independent of detector selection):
              exact / acceptable / set-any accuracy, per-relation breakdown,
              direction errors (ORDER_BEFORE vs ORDER_AFTER).
  GROUP       GRP arms: logic accuracy on gold groups (AND/OR).
  E2E         single-call full graph baseline: event recall/precision/role,
              edge correct/extra/missing/direction/type, graph exact match.
  PIPELINE    composed retriever->detector->classifier graphs (mistral and
              codestral stacks, with and without retriever top-3 gating).
  MINIMAL PAIRS  per-pair diagnostics for MP1/MP2/MP3/MP4/MP6.

Run:  python3 rel_score.py [original|renamed|mini|mini_renamed|all]
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rel_common import FROZEN, OUTPUTS, suffix_for, load_suite

GOLD = Path(__file__).parent / "frozen"


def load_gold(which):
    return json.loads((GOLD / f"gold{suffix_for(which)}.json").read_text(encoding="utf-8"))


def span_match(pred: str, gold: str) -> bool:
    if not pred or not gold:
        return False
    p, g = pred.strip().lower(), gold.strip().lower()
    return p == g or p in g or g in p


def gold_edge_map(gcase):
    """(from_span, to_span) -> edge dict (exact gold spans)."""
    return {(e["from_span"], e["to_span"]): e for e in gcase["edges"]}


def gold_parents(gcase):
    """from_span -> set of gold parent to_spans."""
    parents = {}
    for e in gcase["edges"]:
        parents.setdefault(e["from_span"], set()).add(e["to_span"])
    return parents


# ---------------------------------------------------------------- retriever

def retriever_metrics(which, arm="R_retriever"):
    out = {}
    gold = load_gold(which)
    outdir = OUTPUTS / (arm + suffix_for(which))
    for key in ("r1", "r2", "r3", "r4"):
        top1_hits, n_queries, rec3_sum, rec5_sum = 0, 0, 0.0, 0.0
        edge_top3, edge_top5, n_edges = 0, 0, 0
        for gcase in gold:
            f = outdir / f"{gcase['case_id']}.json"
            if not f.is_file():
                continue
            rows = json.loads(f.read_text(encoding="utf-8"))["queries"]
            parents = gold_parents(gcase)
            for q in rows:
                gps = parents.get(q["from_span"])
                if not gps:
                    continue
                ranked = sorted(q["candidates"], key=lambda c: c[f"rank_{key}"])
                top = [c["to_span"] for c in ranked]
                n_queries += 1
                if top and top[0] in gps:
                    top1_hits += 1
                rec3_sum += len(set(top[:3]) & gps) / len(gps)
                rec5_sum += len(set(top[:5]) & gps) / len(gps)
                for gp in gps:
                    n_edges += 1
                    if gp in set(top[:3]):
                        edge_top3 += 1
                    if gp in set(top[:5]):
                        edge_top5 += 1
        out[key] = {
            "top1": round(top1_hits / n_queries, 4) if n_queries else None,
            "recall@3_query": round(rec3_sum / n_queries, 4) if n_queries else None,
            "recall@5_query": round(rec5_sum / n_queries, 4) if n_queries else None,
            "recall@3_edge": round(edge_top3 / n_edges, 4) if n_edges else None,
            "recall@5_edge": round(edge_top5 / n_edges, 4) if n_edges else None,
            "n_queries": n_queries, "n_edges": n_edges,
        }
    return out


# ---------------------------------------------------------------- detection

def load_pairs(which, arm_dir):
    """(case_id -> list of pair rows) from an arm output dir."""
    outdir = OUTPUTS / (arm_dir + suffix_for(which))
    pairs = {}
    for f in sorted(outdir.glob("*.json")):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        pairs[data["case_id"]] = data.get("pairs", [])
    return pairs


def detection_metrics(which, arm_dir, decision_field="decision"):
    gold = load_gold(which)
    pairs = load_pairs(which, arm_dir)
    tp = fp = fn = tn = unk = n = 0
    fnu = 0
    per_case_fp = {}
    for gcase in gold:
        edges = gold_edge_map(gcase)
        rows = pairs.get(gcase["case_id"], [])
        rowmap = {(r["from_span"], r["to_span"]): r for r in rows}
        universe = [(u["from"], u["to"]) for u in gcase["pair_universe"]]
        case_fp = []
        for (a, b) in universe:
            n += 1
            row = rowmap.get((a, b))
            dec = (row or {}).get(decision_field, "UNKNOWN")
            if dec == "UNKNOWN":
                unk += 1
            pos = (a, b) in edges
            if dec == "RELATED":
                if pos:
                    tp += 1
                else:
                    fp += 1
                    case_fp.append((a, b))
            else:
                if pos:
                    if dec == "NOT_RELATED":
                        fn += 1
                    else:
                        fnu += 1
                else:
                    tn += 1
        if case_fp:
            per_case_fp[gcase["case_id"]] = case_fp
    prec = tp / (tp + fp) if tp + fp else 0.0
    pos_total = tp + fn + fnu
    rec = tp / pos_total if pos_total else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {
        "tp": tp, "fp": fp, "fn_not_related": fn, "fn_unknown": fnu,
        "tn": tn, "pairs": n, "positives": pos_total,
        "precision": round(prec, 4), "recall": round(rec, 4),
        "f1": round(f1, 4), "unknown_rate": round(unk / n, 4) if n else None,
        "false_edge_rate": round(fp / (tp + fp), 4) if tp + fp else None,
        "per_case_fp": {k: v for k, v in per_case_fp.items()},
    }


def combo_detection(which, specs):
    """Post-hoc detector combinations over the pair universe."""
    gold = load_gold(which)
    ce = load_pairs(which, "DET_local")
    nli = load_pairs(which, "DET_local")
    mist = load_pairs(which, "det_mistral")
    cod = load_pairs(which, "det_codestral")
    result = {}
    for name, spec in specs.items():
        k, fields = spec
        tp = fp = fnu = fnr = n = unk = 0
        for gcase in gold:
            edges = gold_edge_map(gcase)
            def local_map(pairs):
                return {(r["from_span"], r["to_span"]): r for r in pairs.get(gcase["case_id"], [])}
            m_ce, m_nli = local_map(ce), local_map(nli)
            m_mi, m_co = local_map(mist), local_map(cod)
            for (a, b) in [(u["from"], u["to"]) for u in gcase["pair_universe"]]:
                n += 1
                rows = [m_ce.get((a, b)), m_nli.get((a, b)),
                        m_mi.get((a, b)), m_co.get((a, b))]
                votes = [row.get(field) for row, field in zip(rows, fields)
                         if row is not None and field is not None]
                rel = sum(1 for v in votes if v == "RELATED")
                if rel >= k and votes:
                    dec = "RELATED"
                elif votes and all(v == "NOT_RELATED" for v in votes):
                    dec = "NOT_RELATED"
                else:
                    dec = "UNKNOWN"
                if dec == "UNKNOWN":
                    unk += 1
                pos = (a, b) in edges
                if dec == "RELATED":
                    tp += pos
                    fp += (not pos)
                else:
                    fnr += (pos and dec == "NOT_RELATED")
                    fnu += (pos and dec == "UNKNOWN")
        prec = tp / (tp + fp) if tp + fp else 0.0
        pos_total = tp + fnr + fnu
        rec = tp / pos_total if pos_total else 0.0
        result[name] = {
            "tp": tp, "fp": fp, "fn_not_related": fnr, "fn_unknown": fnu,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "unknown_rate": round(unk / n, 4) if n else None,
        }
    return result


def consensus_rule(k, fields):
    def rule(*rows):
        votes = []
        for row, field in zip(rows, fields):
            if row is not None:
                votes.append(row.get(field, "UNKNOWN"))
        rel = sum(1 for v in votes if v == "RELATED")
        if rel >= k:
            return "RELATED"
        if rel == 0 and all(v == "NOT_RELATED" for v in votes if votes):
            return "NOT_RELATED"
        return "UNKNOWN"
    return rule


# ------------------------------------------------------------ classification

def classification_metrics(which, arm_dir):
    gold = load_gold(which)
    pairs = load_pairs(which, arm_dir)
    exact = acceptable = set_any = total = 0
    direction_errors = 0
    per_relation = {}
    for gcase in gold:
        rowmap = {(r["from_span"], r["to_span"]): r
                  for r in pairs.get(gcase["case_id"], [])}
        for e in gcase["edges"]:
            row = rowmap.get((e["from_span"], e["to_span"]))
            if row is None:
                continue
            total += 1
            acc = e.get("acceptable", [e["relation"]])
            rel = row.get("relation", "UNKNOWN")
            poss = row.get("possible_relations") or [rel]
            stats = per_relation.setdefault(e["relation"],
                                            {"total": 0, "exact": 0, "acceptable": 0})
            stats["total"] += 1
            if rel == e["relation"]:
                exact += 1
                stats["exact"] += 1
            if rel in acc:
                acceptable += 1
                stats["acceptable"] += 1
            if any(p in acc for p in poss if p):
                set_any += 1
            if (e["relation"] == "ORDER_BEFORE" and rel == "ORDER_AFTER") or \
               (e["relation"] == "ORDER_AFTER" and rel == "ORDER_BEFORE"):
                direction_errors += 1
    return {
        "scored_pairs": total,
        "exact": round(exact / total, 4) if total else None,
        "acceptable": round(acceptable / total, 4) if total else None,
        "set_any_acceptable": round(set_any / total, 4) if total else None,
        "direction_errors": direction_errors,
        "per_relation": per_relation,
    }


# --------------------------------------------------------------------- group

def group_metrics(which, arm_dir):
    gold = load_gold(which)
    outdir = OUTPUTS / (arm_dir + suffix_for(which))
    matched = total = 0
    parent_exact = 0
    for gcase in gold:
        if not gcase.get("groups"):
            continue
        f = outdir / f"{gcase['case_id']}.json"
        if not f.is_file():
            continue
        preds = json.loads(f.read_text(encoding="utf-8")).get("groups", [])
        for g in gcase["groups"]:
            total += 1
            best = None
            for p in preds:
                if span_match(p.get("target", ""), g["target"]):
                    best = p
                    break
            if best is None:
                continue
            if set(best.get("parents", [])) == set(g["members"]):
                parent_exact += 1
            if best.get("logic") == g["type"]:
                matched += 1
    return {"gold_groups": total, "logic_correct": matched,
            "parent_set_exact": parent_exact,
            "logic_accuracy": round(matched / total, 4) if total else None}


# ----------------------------------------------------------------------- e2e

def e2e_metrics(which, arm_dir):
    gold = load_gold(which)
    outdir = OUTPUTS / (arm_dir + suffix_for(which))
    ev_matched = 0
    role_correct = 0
    n_gold_ev = n_pred_ev = 0
    correct = extra = missing = direction_err = type_err = 0
    gem = 0
    n_cases = 0
    for gcase in gold:
        f = outdir / f"{gcase['case_id']}.json"
        if not f.is_file():
            continue
        n_cases += 1
        graph = json.loads(f.read_text(encoding="utf-8")).get("graph", {})
        pred_events = graph.get("events", []) or []
        n_gold_ev += len(gcase["candidate_events"])
        n_pred_ev += len(pred_events)
        # greedy one-to-one span matching (longest gold spans first)
        used = set()
        match_of = {}
        for pe in sorted(pred_events, key=lambda p: -len(p.get("span", ""))):
            best = None
            for ge in gcase["candidate_events"]:
                if ge["source_span"] in used:
                    continue
                if span_match(pe.get("span", ""), ge["source_span"]):
                    best = ge
                    break
            if best is not None:
                match_of[id(pe)] = best
                used.add(best["source_span"])
        ev_matched += len(used)
        role_correct += sum(1 for pe, ge in match_of.items()
                            if pe.get("role") == ge["role"])
        # edges: map predicted endpoints to gold events through matched preds
        gold_edges = gold_edge_map(gcase)
        pred_edges = []
        for e in graph.get("edges", []) or []:
            fs, ts = e.get("from_span", ""), e.get("to_span", "")
            fpe = next((pe for pe in pred_events if span_match(fs, pe.get("span", ""))), None)
            tpe = next((pe for pe in pred_events if span_match(ts, pe.get("span", ""))), None)
            if fpe is None or tpe is None or fpe is tpe:
                extra += 1
                continue
            fge, tge = match_of.get(id(fpe)), match_of.get(id(tpe))
            if fge is None or tge is None:
                extra += 1
                continue
            pred_edges.append((fge["source_span"], tge["source_span"],
                               e.get("relation", "")))
        matched_keys = set()
        for (fs, ts, rel) in pred_edges:
            ge = gold_edges.get((fs, ts))
            if ge is not None:
                matched_keys.add((fs, ts))
                acc = ge.get("acceptable", [ge["relation"]])
                if rel in acc:
                    correct += 1
                else:
                    type_err += 1
                    if (ge["relation"] == "ORDER_BEFORE" and rel == "ORDER_AFTER") or \
                       (ge["relation"] == "ORDER_AFTER" and rel == "ORDER_BEFORE"):
                        direction_err += 1
            else:
                rev = gold_edges.get((ts, fs))
                if rev is not None:
                    direction_err += 1
                    matched_keys.add((ts, fs))
                else:
                    extra += 1
        missing += len(gold_edges) - len(matched_keys)
        if (len(used) == len(gcase["candidate_events"]) == n_pred_ev
                and not extra and not missing and not direction_err and not type_err):
            gem += 1
    return {
        "cases": n_cases,
        "event_recall": round(ev_matched / n_gold_ev, 4) if n_gold_ev else None,
        "event_precision": round(ev_matched / n_pred_ev, 4) if n_pred_ev else None,
        "role_accuracy": round(role_correct / ev_matched, 4) if ev_matched else None,
        "edges_correct": correct, "edges_extra": extra, "edges_missing": missing,
        "direction_errors": direction_err, "type_errors": type_err,
        "n_gold_edges": sum(len(g["edges"]) for g in gold
                            if (outdir / f"{g['case_id']}.json").is_file()),
        "graph_exact_match": gem,
    }


# ------------------------------------------------------------------ pipeline

def pipeline_metrics(which, det_arm, cls_arm, retriever_arm=None, top_k=None,
                     det_field="decision"):
    """Composed graph: edges = DET-RELATED pairs (optionally within retriever
    top-k) typed by the CLS arm; groups from the GRP arm if present."""
    gold = load_gold(which)
    det = load_pairs(which, det_arm)
    cls = load_pairs(which, cls_arm)
    ret = None
    if retriever_arm:
        ret_dir = OUTPUTS / (retriever_arm + suffix_for(which))
        ret = {f.stem: json.loads(f.read_text(encoding="utf-8"))["queries"]
               for f in ret_dir.glob("*.json") if not f.name.startswith("_")}
    tp = fp = 0
    type_correct = 0
    fn = 0
    for gcase in gold:
        edges = gold_edge_map(gcase)
        dmap = {(r["from_span"], r["to_span"]): r for r in det.get(gcase["case_id"], [])}
        cmap = {(r["from_span"], r["to_span"]): r for r in cls.get(gcase["case_id"], [])}
        allowed = None
        if ret is not None and gcase["case_id"] in ret:
            allowed = set()
            for q in ret[gcase["case_id"]]:
                ranked = sorted(q["candidates"], key=lambda c: c["rank_r4"])[:top_k]
                allowed |= {(q["from_span"], c["to_span"]) for c in ranked}
        for (a, b) in [(u["from"], u["to"]) for u in gcase["pair_universe"]]:
            row = dmap.get((a, b))
            dec = (row or {}).get(det_field, "UNKNOWN")
            if dec != "RELATED":
                continue
            if allowed is not None and (a, b) not in allowed:
                continue
            if (a, b) in edges:
                tp += 1
                ge = edges[(a, b)]
                acc = ge.get("acceptable", [ge["relation"]])
                rel = (cmap.get((a, b)) or {}).get("relation", "UNKNOWN")
                if rel in acc:
                    type_correct += 1
            else:
                fp += 1
        fn += len(edges) - sum(1 for (a, b) in edges
                               if (dmap.get((a, b)) or {}).get(det_field) == "RELATED"
                               and (allowed is None or (a, b) in allowed))
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "edges_detected": tp + fp, "edges_correct": tp, "edges_extra": fp,
        "edges_missing": fn,
        "edge_precision": round(prec, 4),
        "edge_recall": round(rec, 4),
        "typed_correct": type_correct,
        "typed_accuracy_given_edge": round(type_correct / tp, 4) if tp else None,
    }


# ------------------------------------------------------------- minimal pairs

def minimal_pair_report(which, det_arm="det_mistral", cls_arm="cls_mistral"):
    gold = {g["case_id"]: g for g in load_gold(which)}
    det = load_pairs(which, det_arm)
    cls = load_pairs(which, cls_arm)
    report = {}

    def dec(case_id, a, b):
        rows = {(r["from_span"], r["to_span"]): r for r in det.get(case_id, [])}
        return (rows.get((a, b)) or {}).get("decision", "MISSING")

    def rel(case_id, a, b):
        rows = {(r["from_span"], r["to_span"]): r for r in cls.get(case_id, [])}
        return (rows.get((a, b)) or {}).get("relation", "MISSING")

    # MP1: condition binds to rent in A, register binds in B; verify must NOT bind in B
    if "climbing_bindA" in gold:
        report["MP1_binding"] = {
            "bindA_verify_to_rent": dec("climbing_bindA", "Verify the harness inspection tag",
                                        "renting climbing gear C-401"),
            "bindA_register_to_rent": dec("climbing_bindA", "Register new members",
                                          "renting climbing gear C-401"),
            "bindB_register_to_rent": dec("climbing_bindB", "Register new members",
                                          "renting climbing gear C-401"),
            "bindB_verify_to_rent": dec("climbing_bindB", "Verify the harness inspection tag",
                                        "renting climbing gear C-401"),
        }
    # MP2: direction
    if "dairy_directionA" in gold:
        report["MP2_direction"] = {
            "A_pasteurize_to_fill_dec": dec("dairy_directionA", "Pasteurize the milk",
                                            "filling the cheese molds"),
            "A_pasteurize_to_fill_rel": rel("dairy_directionA", "Pasteurize the milk",
                                            "filling the cheese molds"),
            "A_fill_to_pasteurize_dec": dec("dairy_directionA", "filling the cheese molds",
                                            "Pasteurize the milk"),
            "B_fill_to_pasteurize_dec": dec("dairy_directionB", "Fill the cheese molds",
                                            "pasteurizing the milk"),
            "B_fill_to_pasteurize_rel": rel("dairy_directionB", "Fill the cheese molds",
                                            "pasteurizing the milk"),
            "B_pasteurize_to_fill_dec": dec("dairy_directionB", "pasteurizing the milk",
                                            "Fill the cheese molds"),
        }
    # MP3: AND vs OR groups
    for cid, key in (("ferry_and", "MP3_and"), ("ferry_or", "MP3_or")):
        if cid in gold:
            g = gold[cid]["groups"][0] if gold[cid]["groups"] else {}
            report[key] = {"gold_logic": g.get("type")}
    # MP4: descriptive phrase
    if "museum_condphrase" in gold:
        report["MP4_descriptive"] = {
            "condphrase_confirm_to_unlock": dec("museum_condphrase",
                                                "The case humidity reading must be confirmed",
                                                "unlocking display cabinet M-4"),
            "condphrase_descriptive_to_unlock": dec(
                "museum_condphrase", "the humidity reading is taken twice daily",
                "unlocking display cabinet M-4"),
            "descphrase_reading_to_unlock": dec(
                "museum_descphrase", "The case humidity reading is taken twice daily",
                "Unlock display cabinet M-4"),
        }
    # MP6: clause structure
    if "brewery_clauseA" in gold:
        report["MP6_clause"] = {
            "A_gate": dec("brewery_clauseA", "the gravity reading is stable",
                          "Bottling of ale batch B-44"),
            "B_gate": dec("brewery_clauseB", "The gravity reading must be stable",
                          "bottling of ale batch B-44"),
        }
    return report


# --------------------------------------------------------------------- main

def score_suite(which):
    report = {"suite": which}

    report["retriever"] = retriever_metrics(which)

    det_arms = {}
    for arm, field in (("DET_local", "ce_decision"), ("DET_local", "nli_decision"),
                       ("det_mistral", "decision"), ("det_codestral", "decision")):
        key = f"{arm}:{field}"
        try:
            det_arms[key] = detection_metrics(which, arm, field)
        except FileNotFoundError:
            pass
    # post-hoc combos (no new inference)
    try:
        specs = {
            "consensus2of3_ce_nli_mistral": (2, ["ce_decision", "nli_decision", "decision", None]),
            "unanimous_ce_nli_mistral": (3, ["ce_decision", "nli_decision", "decision", None]),
            "consensus3of4_all": (3, ["ce_decision", "nli_decision", "decision", "decision"]),
        }
        det_arms.update(combo_detection(which, specs))
    except FileNotFoundError:
        pass
    report["detection"] = det_arms

    cls_arms = {}
    for arm in ("cls_mistral", "cls_codestral"):
        try:
            cls_arms[arm] = classification_metrics(which, arm)
        except FileNotFoundError:
            pass
    report["classification"] = cls_arms

    grp_arms = {}
    for arm in ("grp_mistral", "grp_codestral"):
        try:
            grp_arms[arm] = group_metrics(which, arm)
        except FileNotFoundError:
            pass
    report["groups"] = grp_arms

    e2e_arms = {}
    for arm in ("e2e_mistral", "e2e_codestral"):
        try:
            e2e_arms[arm] = e2e_metrics(which, arm)
        except FileNotFoundError:
            pass
    report["e2e"] = e2e_arms

    pipe = {}
    try:
        pipe["mistral_stack"] = pipeline_metrics(which, "det_mistral", "cls_mistral")
        pipe["mistral_stack_top3"] = pipeline_metrics(
            which, "det_mistral", "cls_mistral", "R_retriever", 3)
        pipe["codestral_stack"] = pipeline_metrics(which, "det_codestral", "cls_codestral")
        pipe["codestral_stack_top3"] = pipeline_metrics(
            which, "det_codestral", "cls_codestral", "R_retriever", 3)
        pipe["ce_nli_mistral_cls_stack"] = pipeline_metrics(
            which, "det_mistral", "cls_mistral")
    except FileNotFoundError:
        pass
    report["pipeline"] = pipe

    try:
        report["minimal_pairs"] = minimal_pair_report(which)
    except FileNotFoundError:
        pass

    return report


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    suites = ["original", "renamed", "mini", "mini_renamed"] if which == "all" else [which]
    for s in suites:
        report = score_suite(s)
        out = Path(__file__).parent / "outputs" / f"score_{s}.json"
        out.write_text(json.dumps(report, indent=1, ensure_ascii=False), encoding="utf-8")
        print(f"=== {s} ===")
        print(json.dumps({k: v for k, v in report.items()
                          if k in ("retriever", "detection", "classification",
                                   "groups", "e2e", "pipeline")},
                         indent=1, ensure_ascii=False)[:4000])


if __name__ == "__main__":
    main()
