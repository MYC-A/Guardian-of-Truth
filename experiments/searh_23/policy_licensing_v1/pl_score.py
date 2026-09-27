"""Comprehensive scorer for the POLICY-LICENSED RELATIONS research.

Sections:
  1  detection arms (pair-level, unordered) with per-split metrics
  2  listwise parent selection metrics (IDEA A)
  3  extractive evidence metrics (IDEA B)
  4  extractive QA metrics (IDEA C)
  5  counterfactual metrics: dataset CF pairs + inference-time CF gate (IDEA D)
  6  MP1 parent-binding accuracy
  7  IDEA F ablation: where false edges come from
  8  conformal summary (IDEA G, reads G_conformal output)
  9  global solver local-vs-global (IDEA H, reads H_solver output)
 10  pipeline assembly + ablation matrix + PRIMARY METRIC
     (policy-licensed edge precision among accepted non-UNKNOWN edges)
 11  renamed suite summary (Level B)

Run: python3 pl_score.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, load_cf_links, out_dir, ev_by_eid

CE_RELATED, CE_UNKNOWN = 0.50, 0.35
CE_BAND = 0.35
SPLITS = ("calib", "val", "test")


def _prf(tp, fp, fn):
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return round(p, 4), round(r, 4), round(f, 4)


def read_json(path: Path, default=None):
    if not path.is_file():
        return default
    return json.loads(path.read_text(encoding="utf-8"))


class CaseData:
    """All arm outputs joined for one case."""

    def __init__(self, case, suffix=""):
        self.case = case
        self.cid = case["case_id"]
        self.evmap = ev_by_eid(case)
        self.gold_pairs = {frozenset((e["from_eid"], e["to_eid"]))
                           for e in case["edges"]}
        self.gold_dir = {(e["from_eid"], e["to_eid"]) for e in case["edges"]}
        base = out_dir
        self.sig = read_json(base("PAIR_signals" + suffix) / f"{self.cid}.json")
        self.det = {}
        for arm in ("det_mistral", "det_codestral", "det_pol_mistral",
                    "det_tool_mistral"):
            d = read_json(base(arm + suffix) / f"{self.cid}.json")
            if d:
                self.det[arm] = {frozenset((r["a_eid"], r["b_eid"])): r
                                 for r in d["rows"]}
        self.ev = read_json(base(f"ev_mistral{suffix}") / f"{self.cid}.json")
        self.evj = read_json(base(f"evjudge_mistral{suffix}") / f"{self.cid}.json")
        self.qa = read_json(base(f"qa_mistral{suffix}") / f"{self.cid}.json")
        self.lw = {}
        for arm in ("listwise_mistral", "listwise_codestral"):
            d = read_json(base(arm + suffix) / f"{self.cid}.json")
            if d:
                self.lw[arm] = {r["eid"]: r for r in d["rows"]}
        self.dirp = read_json(base(f"dir_pred_base_mistral{suffix}") / f"{self.cid}.json")
        self.dirp_ev = read_json(base(f"dir_pred_evidence_mistral{suffix}") / f"{self.cid}.json")
        self.clsp = read_json(base(f"cls_pred_base_mistral{suffix}") / f"{self.cid}.json")
        self.clsp_ev = read_json(base(f"cls_pred_evidence_mistral{suffix}") / f"{self.cid}.json")
        self.grp = read_json(base(f"grp_mistral{suffix}") / f"{self.cid}.json")
        self.cfgate = read_json(base(f"cfgate_mistral{suffix}") / f"{self.cid}.json")
        self.solver = None

    # ---------- pair-level decision rules ----------
    def dec_ce(self, key):
        row = self._sig_row(key)
        if row is None:
            return "UNKNOWN"
        s = max(row["ce_both_ab"], row["ce_both_ba"])
        if s >= CE_RELATED:
            return "RELATED"
        if s >= CE_UNKNOWN:
            return "UNKNOWN"
        return "NOT_RELATED"

    def dec_llm(self, key, arm="det_mistral"):
        r = self.det.get(arm, {}).get(key)
        return (r or {}).get("decision", "UNKNOWN")

    def dec_base(self, key):
        return "RELATED" if (self.dec_ce(key) in ("RELATED", "UNKNOWN")
                             and self.dec_llm(key) == "RELATED") else "NOT_RELATED"

    def dec_ev(self, key):
        """Evidence arm decision from ev + evjudge rows."""
        if self.evj:
            for r in self.evj["rows"]:
                if frozenset((r["a_eid"], r["b_eid"])) == key:
                    d = r.get("decision")
                    if d == "LICENSED":
                        return "RELATED"
                    if d == "NOT_LICENSED":
                        return "NOT_RELATED"
                    if d == "UNSUPPORTED":
                        # no verbatim evidence -> unsupported (not licensed)
                        return "NOT_RELATED"
                    return "UNKNOWN"
        if self.ev:
            for r in self.ev["rows"]:
                if frozenset((r["a_eid"], r["b_eid"])) == key:
                    ev_text = r.get("evidence")
                    if ev_text in (None, "NO_EVIDENCE"):
                        return "NOT_RELATED"
                    return "UNKNOWN"
        return "UNKNOWN"

    def dec_qa_pair(self, key):
        """Pair decision derived from the QA arm: pair RELATED iff either
        event's QA answer maps onto the other event."""
        if not self.qa:
            return "UNKNOWN"
        a_eid, b_eid = tuple(key)
        for src, tgt in ((a_eid, b_eid), (b_eid, a_eid)):
            for r in self.qa["rows"]:
                if r["eid"] != src or not r.get("verbatim"):
                    continue
                mapped = self._map_answer_to_event(r["answer"])
                if mapped == tgt:
                    return "RELATED"
        return "UNKNOWN"

    def dec_listwise_pair(self, key, arm="listwise_mistral", mode="either"):
        """Pair decision from listwise selections.
        mode='either': RELATED if any direction selected the other.
        mode='consensus': RELATED only if BOTH directions selected each other
        (kills one-sided thematic bindings)."""
        a_eid, b_eid = tuple(key)
        hit_ab = hit_ba = None
        for src, tgt in ((a_eid, b_eid), (b_eid, a_eid)):
            row = self.lw.get(arm, {}).get(src)
            if not row:
                continue
            cands = row.get("candidates", [])
            sel_idx = [int(s) - 1 for s in row.get("selected", [])
                       if str(s).isdigit() and 1 <= int(s) <= len(cands)]
            selected = {cands[i] for i in sel_idx}
            if src == a_eid:
                hit_ab = tgt in selected
            else:
                hit_ba = tgt in selected
        if mode == "consensus":
            if hit_ab and hit_ba:
                return "RELATED"
            if hit_ab is False or hit_ba is False:
                return "NOT_RELATED"  # at least one side saw and rejected
            return "UNKNOWN"
        if hit_ab or hit_ba:
            return "RELATED"
        # explicit negative: candidate seen and not selected on at least one side
        for src, tgt in ((a_eid, b_eid), (b_eid, a_eid)):
            row = self.lw.get(arm, {}).get(src)
            if row and tgt in row.get("candidates", []) and row.get("selected") is not None:
                return "NOT_RELATED"
        return "UNKNOWN"

    def _sig_row(self, key):
        if not self.sig:
            return None
        for r in self.sig["pairs"]:
            if frozenset((r["a_eid"], r["b_eid"])) == key:
                return r
        return None

    def _map_answer_to_event(self, answer):
        """Map a verbatim QA answer to an event by char-span overlap."""
        if not answer:
            return None
        idx = self.case["policy"].find(answer)
        if idx < 0:
            return None
        end = idx + len(answer)
        best, best_ov = None, 0
        for ev in self.case["events"]:
            ov = max(0, min(end, ev["span_end"]) - max(idx, ev["span_start"]))
            if ov > best_ov:
                best, best_ov = ev["eid"], ov
        if best_ov < 0.5 * len(answer):
            return None
        return best


def detection_metrics(cd: CaseData, decider, splits):
    """decider(key) -> RELATED / NOT_RELATED / UNKNOWN per unordered pair."""
    out = {}
    for split in splits + ("ALL",):
        tp = fp = fn = unk = 0
        fp_hard = fp_easy = 0
        fn_list, fp_list = [], []
        cases = [cd] if split == "ALL" else [c for c in [cd] if cd.case["split"] == split]
        if not cases:
            continue
        for c in cases:
            for pu in c.case["pair_universe"]:
                key = frozenset((pu["a_eid"], pu["b_eid"]))
                dec = decider(c, key)
                gold = pu["gold"]
                if dec == "UNKNOWN":
                    unk += 1
                    if gold == "POSITIVE":
                        fn += 1
                        fn_list.append((c.cid, pu["a_eid"], pu["b_eid"], "unknown"))
                    continue
                if dec == "RELATED" and gold == "POSITIVE":
                    tp += 1
                elif dec == "RELATED" and gold == "NEGATIVE":
                    fp += 1
                    fp_list.append((c.cid, pu["a_eid"], pu["b_eid"],
                                    "hard" if pu["hard"] else "easy"))
                    if pu["hard"]:
                        fp_hard += 1
                    else:
                        fp_easy += 1
                elif dec != "RELATED" and gold == "POSITIVE":
                    fn += 1
                    fn_list.append((c.cid, pu["a_eid"], pu["b_eid"], "missed"))
        p, r, f = _prf(tp, fp, fn)
        out[split] = {"tp": tp, "fp": fp, "fn": fn, "unknown": unk,
                      "precision": p, "recall": r, "f1": f,
                      "fp_hard": fp_hard, "fp_easy": fp_easy,
                      "fn_detail": fn_list, "fp_detail": fp_list}
    return out


def aggregate_detection(cds, decider):
    """Aggregate over all cases per split (single pass)."""
    out = {}
    for split in SPLITS + ("ALL",):
        tp = fp = fn = unk = fp_hard = fp_easy = 0
        fn_detail, fp_detail = [], []
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        if not sel:
            continue
        for c in sel:
            for pu in c.case["pair_universe"]:
                key = frozenset((pu["a_eid"], pu["b_eid"]))
                dec = decider(c, key)
                gold = pu["gold"]
                if dec == "UNKNOWN":
                    unk += 1
                    if gold == "POSITIVE":
                        fn += 1
                        fn_detail.append((c.cid, pu["a_eid"], pu["b_eid"], "unknown"))
                    continue
                if dec == "RELATED" and gold == "POSITIVE":
                    tp += 1
                elif dec == "RELATED" and gold == "NEGATIVE":
                    fp += 1
                    fp_detail.append((c.cid, pu["a_eid"], pu["b_eid"],
                                      "hard" if pu["hard"] else "easy"))
                    if pu["hard"]:
                        fp_hard += 1
                    else:
                        fp_easy += 1
                elif dec != "RELATED" and gold == "POSITIVE":
                    fn += 1
                    fn_detail.append((c.cid, pu["a_eid"], pu["b_eid"], "missed"))
        p, r, f = _prf(tp, fp, fn)
        out[split] = {"tp": tp, "fp": fp, "fn": fn, "unknown_rate": round(unk / max(1, tp + fp + fn + unk), 4),
                      "precision": p, "recall": r, "f1": f,
                      "fp_hard": fp_hard, "fp_easy": fp_easy,
                      "fn_detail": fn_detail, "fp_detail": fp_detail}
    return out


# ---------------------------------------------------------------- section 2
def listwise_metrics(cds, arm="listwise_mistral"):
    per_split = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        exact = over = under = none_correct = none_total = mp1_ok = mp1_total = 0
        detail = []
        for c in sel:
            lw = c.lw.get(arm, {})
            for ev in c.case["events"]:
                row = lw.get(ev["eid"])
                if not row:
                    continue
                cands = row.get("candidates", [])
                sel_idx = [int(s) - 1 for s in row.get("selected", [])
                           if str(s).isdigit() and 1 <= int(s) <= len(cands)]
                selected = {cands[i] for i in sel_idx}
                gold_conns = {other["eid"] for other in c.case["events"]
                              if other["eid"] != ev["eid"]
                              and frozenset((ev["eid"], other["eid"])) in c.gold_pairs}
                if not gold_conns:
                    none_total += 1
                    if not selected:
                        none_correct += 1
                if selected == gold_conns:
                    exact += 1
                else:
                    if selected - gold_conns:
                        over += 1
                    if gold_conns - selected:
                        under += 1
                detail.append({"case": c.cid, "eid": ev["eid"],
                               "selected": sorted(selected),
                               "gold": sorted(gold_conns)})
        n = len(detail)
        per_split[split] = {"n_events": n, "exact_set": exact,
                            "exact_rate": round(exact / n, 4) if n else None,
                            "over_select": over, "under_select": under,
                            "none_correct": none_correct, "none_total": none_total,
                            "none_rate": round(none_correct / none_total, 4) if none_total else None}
        per_split[split]["detail"] = detail
    return per_split


# ---------------------------------------------------------------- section 3
def _char_overlap(a0, a1, b0, b1):
    return max(0, min(a1, b1) - max(a0, b0))


def evidence_metrics(cds):
    per_split = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        n = verbatim = halluc = no_ev = 0
        pos_verbatim = pos_no_ev = pos_total = 0
        neg_verbatim = neg_no_ev = neg_total = 0
        ious, wrong_parent, minimal = [], 0, []
        for c in sel:
            if not c.ev:
                continue
            # gold evidence spans per pair (for overlap calc)
            gold_ev_spans = {}
            for ed in c.case["edges"]:
                key = frozenset((ed["from_eid"], ed["to_eid"]))
                gold_ev_spans[key] = [(e["start"], e["end"]) for e in ed["evidence"]]
            other_gold_spans = []
            for key, spans in gold_ev_spans.items():
                other_gold_spans.extend(spans)
            for r in c.ev["rows"]:
                n += 1
                key = frozenset((r["a_eid"], r["b_eid"]))
                pu = next((p for p in c.case["pair_universe"]
                           if frozenset((p["a_eid"], p["b_eid"])) == key), None)
                gold = (pu or {}).get("gold")
                ev_text = r.get("evidence")
                if ev_text in (None, "NO_EVIDENCE"):
                    no_ev += 1
                    if gold == "POSITIVE":
                        pos_no_ev += 1
                        pos_total += 1
                    elif gold == "NEGATIVE":
                        neg_no_ev += 1
                        neg_total += 1
                    continue
                idx = c.case["policy"].find(ev_text) if isinstance(ev_text, str) else -1
                if idx < 0:
                    halluc += 1
                    continue
                verbatim += 1
                end = idx + len(ev_text)
                if gold == "POSITIVE":
                    pos_verbatim += 1
                    pos_total += 1
                    spans = gold_ev_spans.get(key, [])
                    if spans:
                        best_iou = 0.0
                        for g0, g1 in spans:
                            inter = _char_overlap(idx, end, g0, g1)
                            union = (end - idx) + (g1 - g0) - inter
                            best_iou = max(best_iou, inter / union if union else 0.0)
                        ious.append(best_iou)
                        gold_len = sum(g1 - g0 for g0, g1 in spans)
                        minimal.append((end - idx) / max(1, gold_len))
                elif gold == "NEGATIVE":
                    neg_verbatim += 1
                    neg_total += 1
                    # wrong-parent evidence: overlaps another edge's gold evidence
                    for g0, g1 in other_gold_spans:
                        if _char_overlap(idx, end, g0, g1) > 0.5 * (g1 - g0):
                            wrong_parent += 1
                            break
        per_split[split] = {
            "n_pairs": n, "verbatim_rate": round(verbatim / n, 4) if n else None,
            "hallucinated": halluc, "no_evidence": no_ev,
            "pos_verbatim": pos_verbatim, "pos_no_evidence": pos_no_ev,
            "pos_total": pos_total,
            "neg_verbatim": neg_verbatim, "neg_no_evidence": neg_no_ev,
            "neg_total": neg_total,
            "mean_evidence_iou_on_pos": round(sum(ious) / len(ious), 4) if ious else None,
            "mean_minimality_ratio": round(sum(minimal) / len(minimal), 4) if minimal else None,
            "wrong_parent_evidence_on_neg": wrong_parent,
        }
    return per_split


# ---------------------------------------------------------------- section 4
def qa_metrics(cds):
    per_split = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        n = verbatim = no_ans = 0
        target_ok = target_total = 0
        none_ok = none_total = 0
        ambiguous_map = 0
        for c in sel:
            if not c.qa:
                continue
            # gold children per event (event is the ANTECEDENT)
            children = {}
            for ed in c.case["edges"]:
                children.setdefault(ed["from_eid"], set()).add(ed["to_eid"])
            for r in c.qa["rows"]:
                n += 1
                eid = r["eid"]
                ans = r.get("answer")
                if ans in (None, "NO ANSWER"):
                    no_ans += 1
                    if eid not in children:
                        none_ok += 1
                        none_total += 1
                    continue
                if not r.get("verbatim"):
                    continue
                verbatim += 1
                mapped = c._map_answer_to_event(ans)
                if eid in children:
                    target_total += 1
                    if mapped in children[eid]:
                        target_ok += 1
                else:
                    none_total += 1
        per_split[split] = {
            "n_events": n, "verbatim_rate": round(verbatim / n, 4) if n else None,
            "no_answer_rate": round(no_ans / n, 4) if n else None,
            "target_accuracy": round(target_ok / target_total, 4) if target_total else None,
            "target_total": target_total,
            "none_correct_rate": round(none_ok / none_total, 4) if none_total else None,
        }
    return per_split


# ---------------------------------------------------------------- section 5
def cf_metrics(cds):
    links = load_cf_links()
    by_cid = {c.cid: c for c in cds}
    out = []
    for link in links:
        oc, cc = by_cid.get(link["original_case_id"]), by_cid.get(link["cf_case_id"])
        if not oc or not cc:
            continue
        sw = link["swap"]
        a, ob, nb = sw["condition_eid"], sw["orig_parent"], sw["new_parent"]
        row = {"pair": (link["original_case_id"], link["cf_case_id"]),
               "arms": {}}
        for arm, score_fn in [
            ("ce", lambda c, k: (c._sig_row(k) or {}).get("ce_both_ab", 0.0)
             if c._sig_row(k) else 0.0),
        ]:
            k_ob_o = frozenset((a, ob))
            k_nb_o = frozenset((a, nb))
            s_ob_orig = score_fn(oc, k_ob_o)
            s_nb_orig = score_fn(oc, k_nb_o)
            s_ob_cf = score_fn(cc, k_ob_o)
            s_nb_cf = score_fn(cc, k_nb_o)
            row["arms"][arm] = {
                "score(A,orig) orig->cf": [round(s_ob_orig, 3), round(s_ob_cf, 3)],
                "score(A,new) orig->cf": [round(s_nb_orig, 3), round(s_nb_cf, 3)],
                "drops": bool(s_ob_cf < s_ob_orig),
                "rises": bool(s_nb_cf > s_nb_orig),
            }
        # decision-level flips for mistral det / listwise / evidence
        for arm, dec in [("det_mistral", lambda c, k: c.dec_llm(k)),
                         ("listwise", lambda c, k: c.dec_listwise_pair(k)),
                         ("evidence", lambda c, k: c.dec_ev(k))]:
            d_ob_o = dec(oc, frozenset((a, ob)))
            d_nb_o = dec(oc, frozenset((a, nb)))
            d_ob_c = dec(cc, frozenset((a, ob)))
            d_nb_c = dec(cc, frozenset((a, nb)))
            row["arms"][arm] = {
                "(A,orig) orig->cf": [d_ob_o, d_ob_c],
                "(A,new) orig->cf": [d_nb_o, d_nb_c],
                "flips_to_new": bool(d_ob_o == "RELATED" and d_ob_c != "RELATED"
                                     and d_nb_c == "RELATED"),
            }
        out.append(row)
    n = len(out)
    flips = {arm: sum(1 for r in out if r["arms"][arm].get("flips_to_new"))
             for arm in ("det_mistral", "listwise", "evidence")}
    drops = sum(1 for r in out if r["arms"]["ce"].get("drops"))
    rises = sum(1 for r in out if r["arms"]["ce"].get("rises"))
    return {"cf_pairs": out, "n": n,
            "ce_drops": drops, "ce_rises": rises,
            "decision_flips_to_new": flips}


def cf_gate_metrics(cds):
    """Inference-time CF gate (pl_run_cf_gate) applied to BASE edges.
    ce_gate is the usable gate; llm_gate is the diagnostic (expected to be
    mostly WORLD_DRIVEN - that is the mechanism finding)."""
    per_split = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        stats = {}
        for gate_field, keep in (("ce_gate", "ce"), ("llm_gate", "llm")):
            licensed = world = unverif = no_alt = 0
            tp_l = fp_l = tp_w = fp_w = 0
            for c in sel:
                if not c.cfgate:
                    continue
                for r in c.cfgate["rows"]:
                    key = frozenset((r["a_eid"], r["b_eid"]))
                    gold = key in c.gold_pairs
                    g = r.get(gate_field)
                    if g == "LICENSED":
                        licensed += 1
                        if gold:
                            tp_l += 1
                        else:
                            fp_l += 1
                    elif g == "WORLD_DRIVEN":
                        world += 1
                        if gold:
                            tp_w += 1
                        else:
                            fp_w += 1
                    elif g == "UNVERIFIED_CF":
                        unverif += 1
                    elif g == "NO_ALTERNATIVE":
                        no_alt += 1
            stats[keep] = {
                "licensed": licensed, "world_driven": world,
                "unverified_cf": unverif, "no_alternative": no_alt,
                "precision_if_keep_licensed_only": round(tp_l / (tp_l + fp_l), 4)
                if tp_l + fp_l else None,
                "precision_if_keep_all": round((tp_l + tp_w) / max(1, tp_l + tp_w + fp_l + fp_w), 4),
                "tp_licensed": tp_l, "fp_licensed": fp_l,
                "tp_world": tp_w, "fp_world": fp_w,
            }
        per_split[split] = stats
    return per_split


# ---------------------------------------------------------------- section 6
def mp1_metrics(cds):
    links = load_cf_links()
    by_cid = {c.cid: c for c in cds}
    rows = []
    for link in links:
        for cid, parent in ((link["original_case_id"], link["swap"]["orig_parent"]),
                            (link["cf_case_id"], link["swap"]["new_parent"])):
            c = by_cid.get(cid)
            if not c:
                continue
            a = link["swap"]["condition_eid"]
            gold_sel = {parent}
            arms = {}
            # det-level: partners called RELATED for a
            for arm, dec in [("det_mistral", lambda c, k: c.dec_llm(k)),
                             ("base", lambda c, k: c.dec_base(k)),
                             ("evidence", lambda c, k: c.dec_ev(k)),
                             ("qa", lambda c, k: c.dec_qa_pair(k)),
                             ("listwise", lambda c, k: c.dec_listwise_pair(k))]:
                partners = {other["eid"] for other in c.case["events"]
                            if other["eid"] != a
                            and dec(c, frozenset((a, other["eid"]))) == "RELATED"}
                arms[arm] = {"selected": sorted(partners), "exact": partners == gold_sel}
            rows.append({"case": cid, "condition": a,
                         "gold_parent": parent, "arms": arms})
    per_arm = {}
    for arm in ("det_mistral", "base", "evidence", "qa", "listwise"):
        ok = sum(1 for r in rows if r["arms"][arm]["exact"])
        per_arm[arm] = {"exact": ok, "n": len(rows)}
        per_arm[arm]["rate"] = round(ok / len(rows), 4) if rows else None
    return {"detail": rows, "per_arm": per_arm}


# ---------------------------------------------------------------- section 7
def fablation_metrics(cds):
    """Where do false edges come from: policy-only vs tool-only vs both."""
    out = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        fp_both = fp_pol_only = fp_tool_only = 0
        fp_tool_driven = fp_policy_driven = 0
        tp_both = tp_pol_only = tp_tool_only = 0
        for c in sel:
            for pu in c.case["pair_universe"]:
                key = frozenset((pu["a_eid"], pu["b_eid"]))
                d_both = c.dec_llm(key, "det_mistral") == "RELATED"
                d_pol = c.dec_llm(key, "det_pol_mistral") == "RELATED"
                d_tool = c.dec_llm(key, "det_tool_mistral") == "RELATED"
                gold = pu["gold"] == "POSITIVE"
                if not gold:
                    if d_both and d_pol and d_tool:
                        fp_both += 1
                    elif d_both and d_pol and not d_tool:
                        fp_pol_only += 1
                    elif d_both and not d_pol and d_tool:
                        fp_tool_only += 1
                    if d_tool and not d_pol:
                        fp_tool_driven += 1
                    if d_pol and not d_tool:
                        fp_policy_driven += 1
                else:
                    if d_both and d_pol and d_tool:
                        tp_both += 1
                    elif d_both and d_pol and not d_tool:
                        tp_pol_only += 1
                    elif d_both and not d_pol and d_tool:
                        tp_tool_only += 1
        out[split] = {"fp_both": fp_both, "fp_policy_only": fp_pol_only,
                      "fp_tool_only": fp_tool_only,
                      "fp_tool_driven": fp_tool_driven,
                      "fp_policy_driven": fp_policy_driven,
                      "tp_both": tp_both, "tp_policy_only": tp_pol_only,
                      "tp_tool_only": tp_tool_only}
    return out


# ---------------------------------------------------------------- section 10
def assemble_pipeline(cd: CaseData, detection="base", gate=None):
    """Assemble a typed directed graph from arm outputs.

    detection: 'base' | 'listwise' | 'evidence' | 'qa'
    gate:      None | 'cf' (counterfactual gate) | 'conformal'
    Returns directed edges (u,v) + types + unknown-downgraded pairs.
    """
    deciders = {
        "base": cd.dec_base,
        "listwise": cd.dec_listwise_pair,
        "listwise_consensus": lambda k: cd.dec_listwise_pair(k, mode="consensus"),
        "evidence": cd.dec_ev,
        "qa": cd.dec_qa_pair,
    }
    dec = deciders[detection]
    edges = []
    unknowns = []
    for pu in cd.case["pair_universe"]:
        key = frozenset((pu["a_eid"], pu["b_eid"]))
        d = dec(key)
        if d != "RELATED":
            if d == "UNKNOWN":
                unknowns.append(sorted(key))
            continue
        # direction
        dirrow = None
        dirp = cd.dirp_ev if detection == "evidence" else cd.dirp
        if dirp:
            for r in cd.dirp["rows"]:
                if frozenset((r["a_eid"], r["b_eid"])) == key:
                    dirrow = r
                    break
        a_eid, b_eid = pu["a_eid"], pu["b_eid"]
        first = (dirrow or {}).get("first")
        if first == "B":
            a_eid, b_eid = pu["b_eid"], pu["a_eid"]
        elif first not in ("A", "B"):
            # role/position fallback (frozen from relation_edges_v1)
            ra = cd.evmap[a_eid]["role"]
            rb = cd.evmap[b_eid]["role"]
            if ra in ("PRECONDITION_CHECK", "STATE_OBSERVATION") and rb not in (
                    "PRECONDITION_CHECK", "STATE_OBSERVATION"):
                pass
            elif rb in ("PRECONDITION_CHECK", "STATE_OBSERVATION") and ra not in (
                    "PRECONDITION_CHECK", "STATE_OBSERVATION"):
                a_eid, b_eid = b_eid, a_eid
            elif cd.evmap[a_eid]["span_start"] > cd.evmap[b_eid]["span_start"]:
                a_eid, b_eid = b_eid, a_eid
        # counterfactual gate (ce_gate is the usable gate; llm_gate diagnostic)
        if gate == "cf" and cd.cfgate:
            g = None
            for r in cd.cfgate["rows"]:
                if frozenset((r["a_eid"], r["b_eid"])) == key:
                    g = r.get("ce_gate")
                    break
            if g in ("WORLD_DRIVEN", "UNVERIFIED_CF"):
                unknowns.append(sorted(key))
                continue
        edges.append((a_eid, b_eid))
    return edges, unknowns


def pipeline_metrics(cds, detection="base", gate=None):
    per_split = {}
    for split in SPLITS + ("ALL",):
        sel = cds if split == "ALL" else [c for c in cds if c.case["split"] == split]
        correct = extra = missing = direrr = typed_ok = 0
        unknown = 0
        exact_cases = total_cases = 0
        for c in sel:
            edges, unknowns = assemble_pipeline(c, detection, gate)
            unknown += len(unknowns)
            pred = set(edges)
            gold = c.gold_dir
            ok = True
            for (u, v) in pred:
                if (u, v) in gold:
                    correct += 1
                elif (v, u) in gold:
                    direrr += 1
                    ok = False
                else:
                    extra += 1
                    ok = False
            for g in gold:
                if g not in pred and (g[1], g[0]) not in pred:
                    missing += 1
                    ok = False
            # typing on correct-endpoint edges
            clsp = c.clsp_ev if detection == "evidence" else c.clsp
            if clsp:
                for r in clsp["rows"]:
                    key = (r["a_eid"], r["b_eid"])
                    if key in pred or (key[1], key[0]) in pred:
                        gold_edge = next((e for e in c.case["edges"]
                                          if (e["from_eid"], e["to_eid"]) == key), None)
                        if gold_edge and (r.get("relation") in gold_edge["acceptable"]
                                          or r.get("relation") in (gold_edge["possible"]
                                                                   if "possible" in gold_edge else [])):
                            typed_ok += 1
            total_cases += 1
            if ok and not missing:
                exact_cases += 1
        acc = correct + extra + direrr
        per_split[split] = {
            "edges_correct": correct, "edges_extra": extra,
            "edges_missing": missing, "direction_errors": direrr,
            "typed_ok": typed_ok,
            "unknown_downgraded": unknown,
            "cases_exact": exact_cases, "cases_total": total_cases,
            "accepted_precision": round(correct / acc, 4) if acc else None,
            "recall": round(correct / max(1, correct + missing), 4),
        }
    return per_split


def main():
    suite = load_suite("original")
    cds = [CaseData(c) for c in suite]

    report = {}

    # ---------------- section 1: detection ----------------------------
    arms = {
        "DET-ce(0.50/0.35)": lambda c, k: c.dec_ce(k),
        "DET-mistral": lambda c, k: c.dec_llm(k),
        "DET-codestral": lambda c, k: c.dec_llm(k, "det_codestral"),
        "DET-pol(policy-only)": lambda c, k: c.dec_llm(k, "det_pol_mistral"),
        "DET-tool(tool-only)": lambda c, k: c.dec_llm(k, "det_tool_mistral"),
        "BASE(ce-band^mistral)": lambda c, k: c.dec_base(k),
        "EVIDENCE(ev+judge)": lambda c, k: c.dec_ev(k),
        "QA-derived": lambda c, k: c.dec_qa_pair(k),
        "LISTWISE-derived": lambda c, k: c.dec_listwise_pair(k),
        "LISTWISE-consensus": lambda c, k: c.dec_listwise_pair(k, mode="consensus"),
    }
    report["detection"] = {}
    for name, dec in arms.items():
        report["detection"][name] = aggregate_detection(cds, dec)

    # ---------------- sections 2-7 ------------------------------------
    report["listwise"] = listwise_metrics(cds)
    report["evidence"] = evidence_metrics(cds)
    report["qa"] = qa_metrics(cds)
    report["cf"] = cf_metrics(cds)
    report["cf_gate"] = cf_gate_metrics(cds)
    report["mp1"] = mp1_metrics(cds)
    report["f_ablation"] = fablation_metrics(cds)

    # ---------------- section 8: conformal ---------------------------
    conf = read_json(out_dir("G_conformal") / "conformal.json")
    report["conformal"] = conf["results"] if conf else None

    # ---------------- section 9: solver ------------------------------
    sol = read_json(out_dir("H_solver") / "solver.json")
    if sol:
        srep = {}
        for variant in ("primary", "uniform", "ce_only", "llm_only"):
            per = sol["cpsat"].get(variant, {})
            fp_removed = tp_removed = 0
            for cid, rec in per.items():
                c = next((x for x in cds if x.cid == cid), None)
                if not c or "selected" not in rec:
                    continue
                cands = {frozenset(k) for k in rec.get("candidate_pairs", [])}
                sel = {frozenset((u, v)) for u, v in rec["selected"]}
                for k in cands - sel:
                    if k not in c.gold_pairs:
                        fp_removed += 1
                    else:
                        tp_removed += 1
            srep[variant] = {"fp_removed_by_solver": fp_removed,
                             "tp_removed_by_solver": tp_removed}
        # clingo cross-check agreement
        agree = 0
        tot = 0
        for cid, sel in (sol.get("clingo_crosscheck_primary") or {}).items():
            cp = sol["cpsat"]["primary"].get(cid, {}).get("selected")
            if cp is None:
                continue
            tot += 1
            if {frozenset((u, v)) for u, v in sel} == {frozenset((u, v)) for u, v in cp}:
                agree += 1
        srep["clingo_cpsat_agreement"] = f"{agree}/{tot}"
        report["solver"] = srep

    # ---------------- section 10: pipelines --------------------------
    report["pipelines"] = {
        "BASE": pipeline_metrics(cds, "base"),
        "A_listwise": pipeline_metrics(cds, "listwise"),
        "A_listwise_consensus": pipeline_metrics(cds, "listwise_consensus"),
        "B_evidence": pipeline_metrics(cds, "evidence"),
        "C_qa": pipeline_metrics(cds, "qa"),
        "BASE+cf_gate": pipeline_metrics(cds, "base", gate="cf"),
        "B_evidence+cf_gate": pipeline_metrics(cds, "evidence", gate="cf"),
    }

    # ---------------- section 11: renamed ----------------------------
    ren_suite = load_suite("renamed")
    ren_cds = [CaseData(c, suffix="_renamed") for c in ren_suite]
    report["renamed_detection"] = {
        "DET-ce": aggregate_detection(ren_cds, lambda c, k: c.dec_ce(k)),
        "DET-mistral": aggregate_detection(ren_cds, lambda c, k: c.dec_llm(k)),
        "BASE": aggregate_detection(ren_cds, lambda c, k: c.dec_base(k)),
        "LISTWISE-derived": aggregate_detection(ren_cds, lambda c, k: c.dec_listwise_pair(k)),
    }

    out_dir("SCORE").joinpath("score.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1), encoding="utf-8")

    # ---------------- printable summary ------------------------------
    print("=== DETECTION (ALL pairs) ===")
    for name, m in report["detection"].items():
        a = m.get("ALL", {})
        print(f"{name:28s} P={a.get('precision')} R={a.get('recall')} "
              f"F1={a.get('f1')} FP={a.get('fp')} (hard {a.get('fp_hard')}) "
              f"FN={a.get('fn')} UNK={a.get('unknown_rate')}")
    print("\n=== DETECTION (test split) ===")
    for name, m in report["detection"].items():
        a = m.get("test", {})
        print(f"{name:28s} P={a.get('precision')} R={a.get('recall')} F1={a.get('f1')}")
    print("\n=== MP1 ===")
    print(json.dumps(report["mp1"]["per_arm"], indent=1))
    print("\n=== CF flips ===", json.dumps(report["cf"]["decision_flips_to_new"]))
    print("=== CF gate (ALL) ===", json.dumps(report["cf_gate"].get("ALL")))
    print("\n=== PIPELINES (test) ===")
    for name, m in report["pipelines"].items():
        t = m.get("test", {})
        print(f"{name:20s} prec={t.get('accepted_precision')} rec={t.get('recall')} "
              f"extra={t.get('edges_extra')} missing={t.get('edges_missing')} "
              f"direrr={t.get('direction_errors')} unk={t.get('unknown_downgraded')}")
    print("\n=== RENAMED (ALL) ===")
    for name, m in report["renamed_detection"].items():
        a = m.get("ALL", {})
        print(f"{name:20s} P={a.get('precision')} R={a.get('recall')} F1={a.get('f1')}")
    print("\nscore.json written")


if __name__ == "__main__":
    main()
