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
    """Relation DETECTION on the unordered pair space, per the brief:
    'есть ли вообще смысловая связь между A и B' - a pair {a,b} is positive
    iff a gold edge connects a and b in EITHER direction. Direction is a
    CLASSIFICATION problem, not a detection problem.
    Also reports per-direction diagnostics (direction blindness).
    """
    gold = load_gold(which)
    pairs = load_pairs(which, arm_dir)
    tp = fp = fn = tn = 0
    dir_blind = 0  # positives where only ONE direction answered RELATED
    per_case_fp = {}
    for gcase in gold:
        edges = gold_edge_map(gcase)
        rev_edges = {(b, a) for (a, b) in edges}
        rows = pairs.get(gcase["case_id"], [])
        rowmap = {(r["from_span"], r["to_span"]): r for r in rows}
        universe = [(u["from"], u["to"]) for u in gcase["pair_universe"]]
        seen_unordered = set()
        case_fp = []
        for (a, b) in universe:
            key = frozenset((a, b))
            if key in seen_unordered:
                continue
            seen_unordered.add(key)
            dec_ab = (rowmap.get((a, b)) or {}).get(decision_field, "UNKNOWN")
            dec_ba = (rowmap.get((b, a)) or {}).get(decision_field, "UNKNOWN")
            pred_pos = (dec_ab == "RELATED") or (dec_ba == "RELATED")
            gold_pos = ((a, b) in edges) or ((b, a) in edges)
            if gold_pos and (dec_ab == "RELATED") != (dec_ba == "RELATED"):
                dir_blind += 1
            if pred_pos:
                if gold_pos:
                    tp += 1
                else:
                    fp += 1
                    case_fp.append(tuple(sorted((a, b))))
            else:
                if gold_pos:
                    fn += 1
                else:
                    tn += 1
        if case_fp:
            per_case_fp[gcase["case_id"]] = case_fp
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    n_unordered = tp + fp + fn + tn
    return {
        "tp": tp, "fp": fp, "fn": fn, "tn": tn,
        "unordered_pairs": n_unordered, "positives": tp + fn,
        "precision": round(prec, 4), "recall": round(rec, 4),
        "f1": round(f1, 4),
        "false_edge_rate": round(fp / (tp + fp), 4) if tp + fp else None,
        "direction_blind_positives": dir_blind,
        "per_case_fp": {k: v for k, v in per_case_fp.items()},
    }


def combo_detection(which, specs):
    """Post-hoc detector combinations over the unordered pair space
    (symmetric detection semantics, same as detection_metrics)."""
    gold = load_gold(which)
    ce = load_pairs(which, "DET_local")
    nli = load_pairs(which, "DET_local")
    mist = load_pairs(which, "det_mistral")
    cod = load_pairs(which, "det_codestral")
    result = {}
    for name, spec in specs.items():
        k, fields = spec
        tp = fp = fn = 0
        dir_blind = 0
        for gcase in gold:
            edges = gold_edge_map(gcase)

            def local_map(pairs):
                return {(r["from_span"], r["to_span"]): r for r in pairs.get(gcase["case_id"], [])}

            m_ce, m_nli = local_map(ce), local_map(nli)
            m_mi, m_co = local_map(mist), local_map(cod)

            def combo_dec(a, b):
                rows = [m_ce.get((a, b)), m_nli.get((a, b)),
                        m_mi.get((a, b)), m_co.get((a, b))]
                votes = [row.get(field) for row, field in zip(rows, fields)
                         if row is not None and field is not None]
                rel = sum(1 for v in votes if v == "RELATED")
                if rel >= k and votes:
                    return "RELATED"
                if votes and all(v == "NOT_RELATED" for v in votes):
                    return "NOT_RELATED"
                return "UNKNOWN"

            seen = set()
            for (a, b) in [(u["from"], u["to"]) for u in gcase["pair_universe"]]:
                key = frozenset((a, b))
                if key in seen:
                    continue
                seen.add(key)
                dec_ab = combo_dec(a, b)
                dec_ba = combo_dec(b, a)
                pred_pos = (dec_ab == "RELATED") or (dec_ba == "RELATED")
                gold_pos = ((a, b) in edges) or ((b, a) in edges)
                if gold_pos and (dec_ab == "RELATED") != (dec_ba == "RELATED"):
                    dir_blind += 1
                if pred_pos:
                    tp += gold_pos
                    fp += (not gold_pos)
                else:
                    fn += gold_pos
        prec = tp / (tp + fp) if tp + fp else 0.0
        rec = tp / (tp + fn) if tp + fn else 0.0
        result[name] = {
            "tp": tp, "fp": fp, "fn": fn,
            "precision": round(prec, 4), "recall": round(rec, 4),
            "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
            "direction_blind_positives": dir_blind,
        }
    return result


def combo_band(which):
    """POST-HOC combo designed after opening the original results:
    RELATED iff (ce score >= 0.35, i.e. ce decision RELATED or UNKNOWN band)
    AND mistral says RELATED. Motivation: mistral detection has high recall
    but massive false-edge rate; the cross-encoder score is precise; their
    agreement should keep recall while cutting false edges. Must be validated
    on the untouched mini set before any integration claim."""
    gold = load_gold(which)
    ce = load_pairs(which, "DET_local")
    mist = load_pairs(which, "det_mistral")
    tp = fp = fn = 0
    for gcase in gold:
        edges = gold_edge_map(gcase)
        m_ce = {(r["from_span"], r["to_span"]): r for r in ce.get(gcase["case_id"], [])}
        m_mi = {(r["from_span"], r["to_span"]): r for r in mist.get(gcase["case_id"], [])}
        seen = set()
        for (a, b) in [(u["from"], u["to"]) for u in gcase["pair_universe"]]:
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)

            def pos(a, b):
                ce_row = m_ce.get((a, b)) or {}
                ce_ok = ce_row.get("ce_decision") in ("RELATED", "UNKNOWN")
                mi_ok = (m_mi.get((a, b)) or {}).get("decision") == "RELATED"
                return ce_ok and mi_ok

            pred_pos = pos(a, b) or pos(b, a)
            gold_pos = ((a, b) in edges) or ((b, a) in edges)
            if pred_pos:
                tp += gold_pos
                fp += (not gold_pos)
            else:
                fn += gold_pos
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {"posthoc_ce_band_and_mistral": {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(prec, 4), "recall": round(rec, 4),
        "f1": round(2 * prec * rec / (prec + rec), 4) if prec + rec else 0.0,
    }}


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
    reversed_related = 0
    per_relation = {}
    RELATED_TYPES = {"PRECONDITION", "STATE_GATE", "ORDER_BEFORE", "ORDER_AFTER",
                     "RESPONSE", "EXCEPTION", "EVEN_IF"}
    for gcase in gold:
        rowmap = {(r["from_span"], r["to_span"]): r
                  for r in pairs.get(gcase["case_id"], [])}
        for e in gcase["edges"]:
            row = rowmap.get((e["from_span"], e["to_span"]))
            rev_row = rowmap.get((e["to_span"], e["from_span"]))
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
            if rev_row is not None and (rev_row.get("relation") in RELATED_TYPES):
                reversed_related += 1
    return {
        "scored_pairs": total,
        "exact": round(exact / total, 4) if total else None,
        "acceptable": round(acceptable / total, 4) if total else None,
        "set_any_acceptable": round(set_any / total, 4) if total else None,
        "direction_errors": direction_errors,
        "reversed_pair_related": reversed_related,
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
        matches = []  # (pred_event, gold_event)
        for pe in sorted(pred_events, key=lambda p: -len(p.get("span", ""))):
            best = None
            for ge in gcase["candidate_events"]:
                if ge["source_span"] in used:
                    continue
                if span_match(pe.get("span", ""), ge["source_span"]):
                    best = ge
                    break
            if best is not None:
                matches.append((pe, best))
                used.add(best["source_span"])
        ev_matched += len(used)
        role_correct += sum(1 for pe, ge in matches
                            if pe.get("role") == ge["role"])
        # edges: map predicted endpoints to gold events through matched preds
        gold_edges = gold_edge_map(gcase)
        pred_edges = []
        match_by_id = {id(pe): ge for pe, ge in matches}
        for e in graph.get("edges", []) or []:
            fs, ts = e.get("from_span", ""), e.get("to_span", "")
            fpe = next((pe for pe in pred_events if span_match(fs, pe.get("span", ""))), None)
            tpe = next((pe for pe in pred_events if span_match(ts, pe.get("span", ""))), None)
            if fpe is None or tpe is None or fpe is tpe:
                extra += 1
                continue
            fge, tge = match_by_id.get(id(fpe)), match_by_id.get(id(tpe))
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
    """Composed graph over unordered pairs:
      - a pair becomes an edge iff the DETECTOR answers RELATED in either
        direction (symmetric detection);
      - direction and type are resolved by the CLASSIFIER: the direction whose
        classification is a related type wins; if both directions classify as
        related types, BOTH directed edges are emitted (direction confusion
        becomes visible as extra/direction-error edges);
      - optional retriever top-k gating restricts candidate pairs.
    """
    gold = load_gold(which)
    det = load_pairs(which, det_arm)
    cls = load_pairs(which, cls_arm)
    ret = None
    if retriever_arm:
        ret_dir = OUTPUTS / (retriever_arm + suffix_for(which))
        ret = {f.stem: json.loads(f.read_text(encoding="utf-8"))["queries"]
               for f in ret_dir.glob("*.json") if not f.name.startswith("_")}
    RELATED_TYPES = {"PRECONDITION", "STATE_GATE", "ORDER_BEFORE", "ORDER_AFTER",
                     "RESPONSE", "EXCEPTION", "EVEN_IF"}
    tp = fp = fn = type_correct = direction_err = type_err = 0
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
                allowed |= {(c["to_span"], q["from_span"]) for c in ranked}

        def pair_allowed(a, b):
            return allowed is None or (a, b) in allowed

        seen = set()
        emitted = []
        for (a, b) in [(u["from"], u["to"]) for u in gcase["pair_universe"]]:
            key = frozenset((a, b))
            if key in seen:
                continue
            seen.add(key)
            dec_ab = (dmap.get((a, b)) or {}).get(det_field, "UNKNOWN")
            dec_ba = (dmap.get((b, a)) or {}).get(det_field, "UNKNOWN")
            if dec_ab != "RELATED" and dec_ba != "RELATED":
                continue
            for (x, y, dec) in ((a, b, dec_ab), (b, a, dec_ba)):
                if dec != "RELATED" or not pair_allowed(x, y):
                    continue
                rel = (cmap.get((x, y)) or {}).get("relation", "UNKNOWN")
                emitted.append((x, y, rel))
        matched_keys = set()
        for (x, y, rel) in emitted:
            ge = edges.get((x, y))
            if ge is not None:
                matched_keys.add((x, y))
                tp += 1
                acc = ge.get("acceptable", [ge["relation"]])
                if rel in acc:
                    type_correct += 1
                else:
                    type_err += 1
                    if (ge["relation"] == "ORDER_BEFORE" and rel == "ORDER_AFTER") or \
                       (ge["relation"] == "ORDER_AFTER" and rel == "ORDER_BEFORE"):
                        direction_err += 1
            else:
                if edges.get((y, x)) is not None:
                    direction_err += 1
                    matched_keys.add((y, x))
                else:
                    fp += 1
        fn += len(edges) - len(matched_keys)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "edges_emitted": tp + fp, "edges_correct": tp, "edges_extra": fp,
        "edges_missing": fn, "direction_errors": direction_err,
        "type_errors": type_err,
        "edge_precision": round(prec, 4),
        "edge_recall": round(rec, 4),
        "typed_correct": type_correct,
        "typed_accuracy_given_edge": round(type_correct / tp, 4) if tp else None,
    }


def dirfix_pipeline_metrics(which, cls_arm="cls_mistral", dir_arm="dir_mistral"):
    """POST-HOC pipeline: edges = ce-band+mistral detected unordered pairs;
    direction resolved by the DIR arm (which event happens first), fallback to
    role/text-position; type from the CLS arm on the resolved direction.
    Exactly ONE directed edge per detected pair."""
    gold = load_gold(which)
    ce = load_pairs(which, "DET_local")
    mist = load_pairs(which, "det_mistral")
    cls = load_pairs(which, cls_arm)
    dird = OUTPUTS / (dir_arm + suffix_for(which))
    dir_pairs = {}
    for f in dird.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        dir_pairs[data["case_id"]] = {(r["a_span"], r["b_span"]): r for r in data.get("pairs", [])}
    tp = fp = fn = type_correct = direction_err = type_err = 0
    from rel_common import load_suite as _ls
    cases = {c["case_id"]: c for c in _ls(which)}
    for gcase in gold:
        edges = gold_edge_map(gcase)
        cid = gcase["case_id"]
        case = cases.get(cid)
        if case is None:
            continue
        m_ce = {(r["from_span"], r["to_span"]): r for r in ce.get(cid, [])}
        m_mi = {(r["from_span"], r["to_span"]): r for r in mist.get(cid, [])}
        cmap = {(r["from_span"], r["to_span"]): r for r in cls.get(cid, [])}
        dmap = dir_pairs.get(cid, {})
        ev_by_span = {e["source_span"]: e for e in case["events"]}
        policy = case["policy"]

        spans = [e["source_span"] for e in case["events"] if e["role"] != "OTHER"]
        emitted = []
        seen = set()
        for i, a in enumerate(spans):
            for b in spans[i + 1:]:
                key = frozenset((a, b))
                if key in seen:
                    continue
                seen.add(key)
                ce_ab = (m_ce.get((a, b)) or {}).get("ce_decision") in ("RELATED", "UNKNOWN")
                mi_ab = (m_mi.get((a, b)) or {}).get("decision") == "RELATED"
                ce_ba = (m_ce.get((b, a)) or {}).get("ce_decision") in ("RELATED", "UNKNOWN")
                mi_ba = (m_mi.get((b, a)) or {}).get("decision") == "RELATED"
                if not ((ce_ab and mi_ab) or (ce_ba and mi_ba)):
                    continue
                # direction: DIR arm answer (stored per (a,b) presentation)
                d = dmap.get((a, b)) or dmap.get((b, a))
                first = d.get("first") if d else None
                if first == "A":
                    x, y = a, b
                elif first == "B":
                    x, y = b, a
                else:
                    # fallback: role prior, then text position
                    ra, rb = ev_by_span[a]["role"], ev_by_span[b]["role"]
                    ANT = {"PRECONDITION_CHECK", "STATE_OBSERVATION"}
                    if ra in ANT and rb not in ANT:
                        x, y = a, b
                    elif rb in ANT and ra not in ANT:
                        x, y = b, a
                    elif policy.find(a) <= policy.find(b):
                        x, y = a, b
                    else:
                        x, y = b, a
                rel = (cmap.get((x, y)) or {}).get("relation", "UNKNOWN")
                emitted.append((x, y, rel))
        matched_keys = set()
        for (x, y, rel) in emitted:
            ge = edges.get((x, y))
            if ge is not None:
                matched_keys.add((x, y))
                tp += 1
                acc = ge.get("acceptable", [ge["relation"]])
                if rel in acc:
                    type_correct += 1
                else:
                    type_err += 1
                    if (ge["relation"] == "ORDER_BEFORE" and rel == "ORDER_AFTER") or \
                       (ge["relation"] == "ORDER_AFTER" and rel == "ORDER_BEFORE"):
                        direction_err += 1
            else:
                if edges.get((y, x)) is not None:
                    direction_err += 1
                    matched_keys.add((y, x))
                else:
                    fp += 1
        fn += len(edges) - len(matched_keys)
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    return {
        "edges_emitted": tp + fp, "edges_correct": tp, "edges_extra": fp,
        "edges_missing": fn, "direction_errors": direction_err,
        "type_errors": type_err,
        "edge_precision": round(prec, 4), "edge_recall": round(rec, 4),
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
    # post-hoc combo (designed after opening original results; to be validated
    # on the untouched mini set): ce uncertain-band + mistral agreement
    try:
        det_arms.update(combo_band(which))
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
        except Exception:
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
        pipe["ce_det_mistral_cls"] = pipeline_metrics(
            which, "DET_local", "cls_mistral", det_field="ce_decision")
        pipe["ce_det_mistral_cls_top3"] = pipeline_metrics(
            which, "DET_local", "cls_mistral", "R_retriever", 3, det_field="ce_decision")
    except Exception:
        pass
    try:
        pipe["posthoc_band_det_dir_cls"] = dirfix_pipeline_metrics(which)
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
