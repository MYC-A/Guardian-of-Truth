"""EVENT_CANON_v1 - scoring: pair metrics, coref cluster metrics
(MUC / B^3 / CEAF-E / CoNLL), merge/missed-merge rates, counterfactual
flips, per-family breakdown, dev-only threshold tuning.

Metric implementations are self-contained (EasyECR has no license - we do
not vendor its code). Toy validation below checks them against hand-computed
values.

Usage:
  python3 ec_score.py tune        # dev: thresholds for score arms + config
  python3 ec_score.py pairs       # pair metrics for all arms / splits
  python3 ec_score.py clusters    # cluster metrics per (source, method)
  python3 ec_score.py cf          # counterfactual flips
  python3 ec_score.py toy         # metric self-validation
"""
from __future__ import annotations

import json
import sys
from pathlib import Path
from itertools import combinations

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import load_suite, load_pairs_gold, out_dir, FROZEN

CLASSES = ("SAME_EVENT", "RELATED_BUT_DIFFERENT", "DIFFERENT", "UNKNOWN",
           "AMBIGUOUS")

# ---------------------------------------------------------------- coref metrics


def _clusters_from_assign(assign, mids):
    by_c = {}
    for m in mids:
        by_c.setdefault(assign.get(m, m), []).append(m)
    return list(by_c.values())


def muc(gold_clusters, pred_clusters):
    num_r = den_r = 0
    for g in gold_clusters:
        if len(g) < 2:
            continue
        parts = {tuple(c) for c in pred_clusters if set(c) & set(g)}
        # links lost = |g| - (number of parts covering g)
        num_r += len(g) - len(parts)
        den_r += len(g) - 1
    num_p = den_p = 0
    for p in pred_clusters:
        if len(p) < 2:
            continue
        parts = {tuple(c) for c in gold_clusters if set(c) & set(p)}
        num_p += len(p) - len(parts)
        den_p += len(p) - 1
    r = num_r / den_r if den_r else 1.0
    p = num_p / den_p if den_p else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def b_cubed(gold_clusters, pred_clusters):
    gold_of, pred_of = {}, {}
    for i, c in enumerate(gold_clusters):
        for m in c:
            gold_of[m] = i
    for i, c in enumerate(pred_clusters):
        for m in c:
            pred_of[m] = i
    mids = list(gold_of)
    p_sum = r_sum = 0.0
    for m in mids:
        gm = {x for x in mids if gold_of[x] == gold_of[m]}
        pm = {x for x in mids if pred_of[x] == pred_of[m]}
        inter = gm & pm
        p_sum += len(inter) / len(pm) if pm else 1.0
        r_sum += len(inter) / len(gm) if gm else 1.0
    n = len(mids)
    p, r = p_sum / n, r_sum / n
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _align(gold_clusters, pred_clusters):
    """Optimal 1-1 alignment via scipy Hungarian; greedy fallback."""
    pairs = []
    for i, g in enumerate(gold_clusters):
        for j, p in enumerate(pred_clusters):
            w = len(set(g) & set(p))
            if w:
                pairs.append((w, i, j))
    chosen = []
    used_g, used_p = set(), set()
    for w, i, j in sorted(pairs, reverse=True):
        if i not in used_g and j not in used_p:
            chosen.append((w, i, j))
            used_g.add(i)
            used_p.add(j)
    if len(gold_clusters) == len(pred_clusters) and \
            len(chosen) == len(gold_clusters):
        return chosen  # greedy = perfect matching here
    try:
        import numpy as np
        from scipy.optimize import linear_sum_assignment
        W = np.zeros((len(gold_clusters), len(pred_clusters)))
        for i, g in enumerate(gold_clusters):
            for j, p in enumerate(pred_clusters):
                W[i, j] = len(set(g) & set(p))
        ri, ci = linear_sum_assignment(-W)
        return [(int(W[i, j]), int(i), int(j)) for i, j in zip(ri, ci)]
    except Exception:
        return chosen


def ceaf_e(gold_clusters, pred_clusters):
    align = _align(gold_clusters, pred_clusters)
    num = sum(w for w, _, _ in align)
    den_p = sum(len(p) for p in pred_clusters)
    den_g = sum(len(g) for g in gold_clusters)
    p = num / den_p if den_p else 1.0
    r = num / den_g if den_g else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def coref_metrics(gold_assign, pred_assign, mids):
    gold = _clusters_from_assign(gold_assign, mids)
    pred = _clusters_from_assign(pred_assign, mids)
    res = {}
    for name, fn in (("muc", muc), ("b3", b_cubed), ("ceaf", ceaf_e)):
        p, r, f = fn(gold, pred)
        res[f"{name}_p"], res[f"{name}_r"], res[f"{name}_f"] = p, r, f
    res["conll_f"] = (res["muc_f"] + res["b3_f"] + res["ceaf_f"]) / 3
    # merge / missed merge over ALL mention pairs
    tp = fp = fn_ = 0
    for a, b in combinations(mids, 2):
        g = gold_assign.get(a, a) == gold_assign.get(b, b)
        q = pred_assign.get(a, a) == pred_assign.get(b, b)
        if g and q:
            tp += 1
        elif q and not g:
            fp += 1
        elif g and not q:
            fn_ += 1
    res["merge_tp"], res["false_merge"], res["missed_merge"] = tp, fp, fn_
    res["merge_p"] = tp / (tp + fp) if tp + fp else 1.0
    res["merge_r"] = tp / (tp + fn_) if tp + fn_ else 1.0
    return res


def toy():
    """Hand-computed validation of MUC / B^3 / CEAF-E.

    gold: C0={m1,m2,m3}, C1={m4,m5}; pred: {m1,m2}, {m3}, {m4,m5}.
    MUC: gold C0 split into 2 parts -> 1 of 2 links intact; C1 intact.
      R = (1+1)/(2+1) = 2/3; P: P0 1/1, P2 singleton, P1 1/1 -> 1.0
    B3: m1,m2: P=1, R=2/3; m3: P=1, R=1/3; m4,m5: 1/1
      P=1.0, R=(2/3+2/3+1/3+1+1)/5 = 11/15 = 0.7333
    CEAF-E: align C0-P0 (2), C1-P1 (2): P = 4/5, R = 4/5
    merge pairs: gold-same {m1m2,m1m3,m2m3,m4m5}; pred-same {m1m2,m4m5}
      -> tp=2, missed=2, false=0
    """
    gold = {"m1": 0, "m2": 0, "m3": 0, "m4": 1, "m5": 1}
    pred = {"m1": 0, "m2": 0, "m3": 2, "m4": 1, "m5": 1}
    res = coref_metrics(gold, pred, list(gold))
    assert abs(res["muc_r"] - 2 / 3) < 1e-9, res
    assert abs(res["muc_p"] - 1.0) < 1e-9, res
    assert abs(res["b3_p"] - 1.0) < 1e-9, res
    assert abs(res["b3_r"] - 11 / 15) < 1e-9, res
    assert abs(res["ceaf_p"] - 0.8) < 1e-9, res
    assert abs(res["ceaf_r"] - 0.8) < 1e-9, res
    assert (res["merge_tp"], res["missed_merge"],
            res["false_merge"]) == (2, 2, 0), res
    # perfect prediction -> all 1.0
    res2 = coref_metrics(gold, dict(gold), list(gold))
    for k in ("muc_p", "muc_r", "b3_p", "b3_r", "ceaf_p", "ceaf_r",
              "merge_p", "merge_r"):
        assert abs(res2[k] - 1.0) < 1e-9, (k, res2)
    # over-merge: everything in one cluster -> false merges counted
    res3 = coref_metrics(gold, {m: 0 for m in gold}, list(gold))
    assert res3["false_merge"] == 6 and res3["merge_p"] == 4 / 10, res3
    assert abs(res3["merge_r"] - 1.0) < 1e-9, res3
    print("toy OK:", {k: round(v, 4) for k, v in res.items()
                      if isinstance(v, float)})


# ---------------------------------------------------------------- arm loading


def load_arm_pairs(arm, which="original"):
    base = out_dir(f"ARMS_{which}") / arm
    out = {}
    if not base.is_dir():
        return out
    for p in sorted(base.glob("*.json")):
        if p.stem.endswith("_sigs"):
            continue
        cid_ = p.stem
        try:
            data = json.loads(p.read_text(encoding="utf-8"))
        except ValueError:
            continue
        recs = data["pairs"] if isinstance(data, dict) and "pairs" in data \
            else data
        out[cid_] = recs
    return out


def load_llm_arm(arm_dir, pairs_field="pairs"):
    base = out_dir(arm_dir)
    out = {}
    for p in sorted(base.glob("*.json")):
        if p.stem.endswith("_pairs") or p.stem.endswith("_graphs"):
            continue
        cid_ = p.stem
        data = json.loads(p.read_text(encoding="utf-8"))
        recs = data.get(pairs_field, data) if isinstance(data, dict) else data
        out[cid_] = recs
    return out


def gold_pairs_by_case(split=None):
    pg = load_pairs_gold()
    suite = load_suite("original")
    if split and split != "ALL":
        keep = {c["case_id"] for c in suite if c["split"] == split}
        pg = {k: v for k, v in pg.items() if k in keep}
    return pg


# ---------------------------------------------------------------- pair metrics


def pair_metrics(pred_by_case, gold_by_case, restrict_keys=None):
    """Per-class P/R/F1 + SAME-binary view + dangerous confusion counts."""
    cm = {g: {p: 0 for p in CLASSES} for g in CLASSES}
    for cid_, pairs in gold_by_case.items():
        pred = {(r["a"], r["b"]): r for r in pred_by_case.get(cid_, [])}
        for gp in pairs:
            key = (gp["a"], gp["b"])
            if key not in pred:
                key_r = (gp["b"], gp["a"])
                r = pred.get(key_r)
            else:
                r = pred.get(key)
            if restrict_keys is not None and (key not in pred and
                                              (gp["b"], gp["a"]) not in pred):
                continue
            pl = r.get("label") if r else "UNKNOWN"
            if pl not in CLASSES:
                pl = "UNKNOWN"
            cm[gp["label"]][pl] += 1
    res = {"confusion": cm}
    for cls in CLASSES:
        tp = cm[cls][cls]
        fp = sum(cm[g][cls] for g in CLASSES if g != cls)
        fn = sum(cm[cls][p] for p in CLASSES if p != cls)
        p = tp / (tp + fp) if tp + fp else 0.0
        r = tp / (tp + fn) if tp + fn else 0.0
        f = 2 * p * r / (p + r) if p + r else 0.0
        res[cls] = {"p": round(p, 4), "r": round(r, 4), "f1": round(f, 4),
                    "tp": tp, "fp": fp, "fn": fn}
    # SAME binary view (SAME vs everything else, AMBIGUOUS excluded)
    tp = cm["SAME_EVENT"]["SAME_EVENT"]
    fp = sum(cm[g]["SAME_EVENT"] for g in CLASSES
             if g not in ("SAME_EVENT", "AMBIGUOUS"))
    fn = sum(cm["SAME_EVENT"][p] for p in CLASSES
             if p not in ("SAME_EVENT", "AMBIGUOUS"))
    p = tp / (tp + fp) if tp + fp else 0.0
    r = tp / (tp + fn) if tp + fn else 0.0
    res["same_binary"] = {"p": round(p, 4), "r": round(r, 4),
                          "f1": round(2 * p * r / (p + r) if p + r else 0, 4),
                          "dangerous_related_as_same":
                              cm["RELATED_BUT_DIFFERENT"]["SAME_EVENT"],
                          "different_as_same": cm["DIFFERENT"]["SAME_EVENT"],
                          "same_as_unknown": cm["SAME_EVENT"]["UNKNOWN"]}
    # abstention profile
    tot = sum(sum(cm[g].values()) for g in CLASSES)
    res["unknown_rate"] = round(sum(cm[g]["UNKNOWN"] for g in CLASSES) /
                                max(1, tot), 4)
    return res


def tune_thresholds():
    """Dev-only threshold selection for score arms (pre-registered rule:
    argmax F1 of SAME-binary; tie -> higher precision)."""
    gold = gold_pairs_by_case("dev")
    cfg = {}
    score_arms = {
        "B_emb_span": ("B_emb", "sim_span"),
        "B_emb_ctx": ("B_emb", "sim_ctx"),
        "C_ce": ("C_ce", "ce"),
        "G_nli": ("G_nli", "nli_entail"),
    }
    for name, (arm, key) in score_arms.items():
        pred = load_arm_pairs(arm)
        best = None
        for tau in [i / 100 for i in range(20, 96, 5)]:
            labeled = {cid_: [{"a": r["a"], "b": r["b"],
                               "label": "SAME_EVENT" if r[key] >= tau else
                               "DIFFERENT"} for r in rs]
                       for cid_, rs in pred.items()}
            m = pair_metrics(labeled, gold)
            sb = m["same_binary"]
            cand = (sb["f1"], sb["p"], tau)
            if best is None or cand > (best[0], best[1], -best[2]):
                best = (sb["f1"], sb["p"], tau)
        cfg[name] = {"arm": arm, "key": key, "tau": best[2],
                     "dev_f1": best[0], "dev_p": best[1]}
    # arm F candidate recall on dev
    fdata = {}
    for p in sorted(out_dir("F_judge").glob("*.json")):
        d = json.loads(p.read_text(encoding="utf-8"))
        if isinstance(d, dict):
            fdata[p.stem] = d
    rec = miss = 0
    for cid_, pairs in gold.items():
        cands = {tuple(x) for x in fdata.get(cid_, {}).get("candidates", [])}
        for gp in pairs:
            if gp["label"] in ("AMBIGUOUS",):
                continue
            if gp["label"] == "SAME_EVENT":
                key = tuple(sorted((gp["a"], gp["b"])))
                if key in cands:
                    rec += 1
                else:
                    miss += 1
    cfg["F_blocking"] = {"same_recall": round(rec / max(1, rec + miss), 4),
                         "missed": miss}
    out = out_dir("SCORE")
    out.joinpath("thresholds_dev.json").write_text(
        json.dumps(cfg, indent=1), encoding="utf-8")
    print(json.dumps(cfg, indent=1))
    return cfg


def hybrid_pairs(mode):
    """Deterministic compositions of stored E_xamr + F_judge outputs.

    and: SAME iff both say SAME; DIFFERENT if either says DIFFERENT;
         else RELATED if either says RELATED; else UNKNOWN
    or : SAME iff either says SAME; DIFFERENT iff both DIFFERENT;
         else RELATED if either says RELATED; else UNKNOWN
    """
    e_dir = out_dir("E_xamr")
    e_pairs = {}
    if e_dir.is_dir():
        e_pairs = {p.stem.replace("_pairs", ""): json.loads(
            p.read_text(encoding="utf-8"))
            for p in sorted(e_dir.glob("*_pairs.json"))}
    f_pairs = {}
    f_dir = out_dir("F_judge")
    if f_dir.is_dir():
        f_pairs = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                   ["pairs"] for p in sorted(f_dir.glob("*.json"))}
    out = {}
    for cid_, f_recs in f_pairs.items():
        emap = {(r["a"], r["b"]): r["label"] for r in e_pairs.get(cid_, [])}
        rows = []
        for r in f_recs:
            key = (r["a"], r["b"])
            e_lab = emap.get(key) or emap.get((r["b"], r["a"])) or "UNKNOWN"
            f_lab = r["label"]
            if mode == "and":
                if f_lab == "SAME_EVENT" and e_lab == "SAME_EVENT":
                    lab = "SAME_EVENT"
                elif "DIFFERENT" in (f_lab, e_lab):
                    lab = "DIFFERENT"
                elif "RELATED" in (f_lab, e_lab):
                    lab = "RELATED_BUT_DIFFERENT"
                else:
                    lab = "UNKNOWN"
            elif mode == "or":
                if "SAME_EVENT" in (f_lab, e_lab):
                    lab = "SAME_EVENT"
                elif f_lab == "DIFFERENT" and e_lab == "DIFFERENT":
                    lab = "DIFFERENT"
                elif "RELATED" in (f_lab, e_lab):
                    lab = "RELATED_BUT_DIFFERENT"
                else:
                    lab = "UNKNOWN"
            else:
                raise SystemExit("mode must be and/or")
            rows.append({"a": r["a"], "b": r["b"], "label": lab,
                         "e_label": e_lab, "f_label": f_lab})
        out[cid_] = rows
    return out


def cmd_pairs():
    gold_all = gold_pairs_by_case()
    arms = {
        "A_lex": load_arm_pairs("A_lex"),
        "D_ud": load_arm_pairs("D_ud"),
        "E_xamr": load_llm_arm("E_xamr", "pairs") if
            (out_dir("E_xamr")).is_dir() else {},
    }
    # labeled E pairs are stored separately
    e_dir = out_dir("E_xamr")
    if e_dir.is_dir():
        arms["E_xamr"] = {p.stem.replace("_pairs", ""): json.loads(
            p.read_text(encoding="utf-8"))
            for p in sorted(e_dir.glob("*_pairs.json"))}
    f_dir = out_dir("F_judge")
    if f_dir.is_dir():
        arms["F_judge"] = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                           ["pairs"] for p in sorted(f_dir.glob("*.json"))}
    arms["H_EF_and"] = hybrid_pairs("and")
    arms["H_EF_or"] = hybrid_pairs("or")
    arms["H_EF_and"] = hybrid_pairs("and")
    arms["H_EF_or"] = hybrid_pairs("or")
    cfg_path = out_dir("SCORE") / "thresholds_dev.json"
    cfg = json.loads(cfg_path.read_text(encoding="utf-8")) \
        if cfg_path.is_file() else {}
    for name, (arm, key, tau) in {
            "B_emb_span": ("B_emb", "sim_span",
                           cfg.get("B_emb_span", {}).get("tau", 0.6)),
            "B_emb_ctx": ("B_emb", "sim_ctx",
                          cfg.get("B_emb_ctx", {}).get("tau", 0.6)),
            "C_ce": ("C_ce", "ce", cfg.get("C_ce", {}).get("tau", 0.0)),
            "G_nli": ("G_nli", "nli_entail",
                      cfg.get("G_nli", {}).get("tau", 0.5))}.items():
        pred = load_arm_pairs(arm)
        arms[name] = {cid_: [{"a": r["a"], "b": r["b"],
                              "label": "SAME_EVENT" if r[key] >= tau else
                              "DIFFERENT"} for r in rs]
                      for cid_, rs in pred.items()}

    report = {}
    for split in ("dev", "calib", "val", "test", "ALL"):
        gold_s = gold_pairs_by_case(split)
        report[split] = {}
        for arm, pred in arms.items():
            if arm == "F_judge":
                report[split][arm] = pair_metrics(pred, gold_s,
                                                  restrict_keys=True)
            else:
                report[split][arm] = pair_metrics(pred, gold_s)
    out = out_dir("SCORE")
    out.joinpath("pair_metrics.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    for split in report:
        print(f"\n===== {split} =====")
        for arm, m in report[split].items():
            sb = m["same_binary"]
            print(f"{arm:12s} SAME-P={sb['p']:.3f} R={sb['r']:.3f} "
                  f"F1={sb['f1']:.3f} dangerous(RELATED->SAME)="
                  f"{sb['dangerous_related_as_same']:3d} "
                  f"unk={m['unknown_rate']:.2f}")


def cmd_cf():
    """Counterfactual flips: critical pairs whose gold label differs between
    twins; system must match gold in BOTH twins."""
    suite = {c["case_id"]: c for c in load_suite("original")}
    pg = load_pairs_gold()
    twins = sorted({tuple(sorted((c["case_id"], c["cf_of"]))) for c in
                    suite.values() if c["cf_of"]})
    arms = {
        "A_lex": load_arm_pairs("A_lex"),
        "D_ud": load_arm_pairs("D_ud"),
    }
    e_dir = out_dir("E_xamr")
    if e_dir.is_dir():
        arms["E_xamr"] = {p.stem.replace("_pairs", ""): json.loads(
            p.read_text(encoding="utf-8"))
            for p in sorted(e_dir.glob("*_pairs.json"))}
    f_dir = out_dir("F_judge")
    if f_dir.is_dir():
        arms["F_judge"] = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                           ["pairs"] for p in sorted(f_dir.glob("*.json"))}
    arms["H_EF_and"] = hybrid_pairs("and")
    arms["H_EF_or"] = hybrid_pairs("or")
    cfg_path = out_dir("SCORE") / "thresholds_dev.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for name, (arm, key) in {"B_emb_span": ("B_emb", "sim_span"),
                                 "B_emb_ctx": ("B_emb", "sim_ctx"),
                                 "C_ce": ("C_ce", "ce"),
                                 "G_nli": ("G_nli", "nli_entail")}.items():
            tau = cfg.get(name, {}).get("tau", 0.6)
            pred = load_arm_pairs(arm)
            arms[name] = {cid_: [{"a": r["a"], "b": r["b"],
                                  "label": "SAME_EVENT" if r[key] >= tau else
                                  "DIFFERENT"} for r in rs]
                          for cid_, rs in pred.items()}
    out = {}
    for arm, pred in arms.items():
        rows = []
        for a_id, b_id in twins:
            ga = {(p["a"], p["b"]): p["label"] for p in pg[a_id]}
            gb = {(p["a"], p["b"]): p["label"] for p in pg[b_id]}
            ma = {m["mid"]: m["span"] for m in suite[a_id]["mentions"]}
            # twins keep consistent mention ids by design (the controlled
            # edit changes the span text / cluster, not the mid)
            for (x, y), lab_a in ga.items():
                lab_b = gb.get((x, y)) or gb.get((y, x))
                if lab_b is None or lab_b == "AMBIGUOUS" or lab_a == "AMBIGUOUS":
                    continue
                if lab_b == lab_a:
                    continue
                pa_rec = next((r for r in pred.get(a_id, [])
                               if {r["a"], r["b"]} == {x, y}), None)
                pb_rec = next((r for r in pred.get(b_id, [])
                               if {r["a"], r["b"]} == {x, y}), None)
                la = pa_rec.get("label") if pa_rec else "MISSING"
                lb = pb_rec.get("label") if pb_rec else "MISSING"
                ok = (la == lab_a) and (lb == lab_b)
                rows.append({"pair": (a_id, b_id), "mentions": (ma[x], ma[y]),
                             "gold_a": lab_a, "gold_b": lab_b,
                             "pred_a": la, "pred_b": lb, "ok": ok})
        n_ok = sum(1 for r in rows if r["ok"])
        out[arm] = {"n_critical": len(rows), "n_ok": n_ok,
                    "rate": round(n_ok / max(1, len(rows)), 4),
                    "rows": rows}
    out_dir("SCORE").joinpath("cf_flips.json").write_text(
        json.dumps(out, indent=1, ensure_ascii=False), encoding="utf-8")
    for arm, r in out.items():
        print(f"{arm:12s} CF consistency {r['n_ok']}/{r['n_critical']} "
              f"= {r['rate']}")


def cmd_clusters():
    """Cluster metrics for each (pair source, clustering method)."""
    from ec_cluster import build_clusters, pair_score
    suite = load_suite("original")
    pg = load_pairs_gold()
    arms = {
        "A_lex": load_arm_pairs("A_lex"),
        "D_ud": load_arm_pairs("D_ud"),
    }
    e_dir = out_dir("E_xamr")
    if e_dir.is_dir():
        arms["E_xamr"] = {p.stem.replace("_pairs", ""): json.loads(
            p.read_text(encoding="utf-8"))
            for p in sorted(e_dir.glob("*_pairs.json"))}
    f_dir = out_dir("F_judge")
    if f_dir.is_dir():
        arms["F_judge"] = {p.stem: json.loads(p.read_text(encoding="utf-8"))
                           ["pairs"] for p in sorted(f_dir.glob("*.json"))}
    arms["H_EF_and"] = hybrid_pairs("and")
    arms["H_EF_or"] = hybrid_pairs("or")
    cfg_path = out_dir("SCORE") / "thresholds_dev.json"
    if cfg_path.is_file():
        cfg = json.loads(cfg_path.read_text(encoding="utf-8"))
        for name, (arm, key) in {"B_emb_span": ("B_emb", "sim_span"),
                                 "B_emb_ctx": ("B_emb", "sim_ctx"),
                                 "C_ce": ("C_ce", "ce"),
                                 "G_nli": ("G_nli", "nli_entail")}.items():
            tau = cfg.get(name, {}).get("tau", 0.6)
            pred = load_arm_pairs(arm)
            arms[name] = {cid_: [{"a": r["a"], "b": r["b"],
                                  "label": "SAME_EVENT" if r[key] >= tau else
                                  "DIFFERENT"} for r in rs]
                          for cid_, rs in pred.items()}

    report = {}
    for split in ("dev", "val", "test", "ALL"):
        sel = [c for c in suite if split == "ALL" or c["split"] == split]
        report[split] = {}
        for arm, pred in arms.items():
            for method in ("cc", "veto", "al", "cl", "corr"):
                agg = {}
                cases_rows = []
                for c in sel:
                    cid_ = c["case_id"]
                    pairs = pred.get(cid_, [])
                    if not pairs:
                        continue
                    mids = [m["mid"] for m in c["mentions"]]
                    gold_assign = {m["mid"]: m["cid"] for m in c["mentions"]}
                    assign = build_clusters(pairs, method,
                                            score_fn=lambda r: pair_score(r),
                                            thresh=0.5)
                    # mentions absent from pairs keep singleton clusters
                    for m in mids:
                        assign.setdefault(m, f"s_{m}")
                    res = coref_metrics(gold_assign, assign, mids)
                    cases_rows.append({"case_id": cid_, **{
                        k: round(v, 4) if isinstance(v, float) else v
                        for k, v in res.items()}})
                if not cases_rows:
                    continue
                n = len(cases_rows)
                summary = {k: round(sum(r[k] for r in cases_rows) / n, 4)
                           for k in ("muc_f", "b3_f", "ceaf_f", "conll_f",
                                     "merge_p", "merge_r")}
                summary["false_merge_total"] = sum(
                    r["false_merge"] for r in cases_rows)
                summary["missed_merge_total"] = sum(
                    r["missed_merge"] for r in cases_rows)
                summary["n_cases"] = n
                report[split][f"{arm}+{method}"] = {
                    "summary": summary, "cases": cases_rows}
    out_dir("SCORE").joinpath("cluster_metrics.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    for split in report:
        print(f"\n===== {split} =====")
        rows = sorted(report[split].items(),
                      key=lambda kv: -kv[1]["summary"]["conll_f"])
        for name, r in rows[:12]:
            s = r["summary"]
            print(f"{name:20s} CoNLL={s['conll_f']:.3f} B3={s['b3_f']:.3f} "
                  f"mP={s['merge_p']:.3f} mR={s['merge_r']:.3f} "
                  f"FM={s['false_merge_total']:3d} MM={s['missed_merge_total']:3d}")


def cmd_ablate_d():
    """Feature ablation for arm D (stored UD signatures): progressively
    enabled signature fields (pre-registered order)."""
    from ec_feats import lemma_family_match
    suite = load_suite("original")

    def compare(sa, sb, fields):
        if not sa["predicate"] or not sb["predicate"]:
            return "UNKNOWN"
        if not lemma_family_match(sa["predicate"], sb["predicate"]):
            return "DIFFERENT"
        if "polarity" in fields and sa["polarity"] != sb["polarity"]:
            return "RELATED_BUT_DIFFERENT"
        if "entities" in fields:
            ea, eb = set(sa["entities"]), set(sb["entities"])
            if ea and eb and not (ea & eb):
                return "RELATED_BUT_DIFFERENT"
        if "temporal" in fields:
            ta, tb = sa.get("temporal"), sb.get("temporal")
            if ta and tb and ta != tb:
                return "RELATED_BUT_DIFFERENT"
        if "args" in fields:
            aa, ab = set(sa["args"]), set(sb["args"])
            if aa and ab and not (aa <= ab or ab <= aa):
                return "RELATED_BUT_DIFFERENT"
        if "mods" in fields:
            if set(sa.get("mods", [])) != set(sb.get("mods", [])):
                return "RELATED_BUT_DIFFERENT"
        return "SAME_EVENT"

    stages = [("predicate_only", []),
              ("+polarity", ["polarity"]),
              ("+entities", ["polarity", "entities"]),
              ("+temporal", ["polarity", "entities", "temporal"]),
              ("+args", ["polarity", "entities", "temporal", "args"]),
              ("+mods(full)", ["polarity", "entities", "temporal", "args",
                               "mods"])]
    report = {}
    for split in ("dev", "val", "test", "ALL"):
        gold = gold_pairs_by_case(split)
        report[split] = {}
        for name, fields in stages:
            cm = {g: {p: 0 for p in CLASSES} for g in CLASSES}
            for cid_, pairs in gold.items():
                sp = out_dir("ARMS_original") / "D_ud" / f"{cid_}_sigs.json"
                if not sp.is_file():
                    continue
                sigs = json.loads(sp.read_text(encoding="utf-8"))
                for gp in pairs:
                    pl = compare(sigs.get(gp["a"], {}), sigs.get(gp["b"], {}),
                                 fields)
                    cm[gp["label"]][pl] += 1
            tp = cm["SAME_EVENT"]["SAME_EVENT"]
            fp = sum(cm[g]["SAME_EVENT"] for g in CLASSES
                     if g not in ("SAME_EVENT", "AMBIGUOUS"))
            fn = sum(cm["SAME_EVENT"][p] for p in CLASSES
                     if p not in ("SAME_EVENT", "AMBIGUOUS"))
            p = tp / (tp + fp) if tp + fp else 0.0
            r = tp / (tp + fn) if tp + fn else 0.0
            report[split][name] = {"p": round(p, 4), "r": round(r, 4),
                                   "f1": round(2 * p * r / (p + r)
                                               if p + r else 0, 4),
                                   "dangerous": cm["RELATED_BUT_DIFFERENT"]["SAME_EVENT"]}
    out_dir("SCORE").joinpath("d_ablation.json").write_text(
        json.dumps(report, indent=1), encoding="utf-8")
    for split in report:
        print(f"===== {split} =====")
        for name, m in report[split].items():
            print(f"D {name:14s} P={m['p']:.3f} R={m['r']:.3f} "
                  f"F1={m['f1']:.3f} dangerous={m['dangerous']}")


if __name__ == "__main__":
    cmd = sys.argv[1] if len(sys.argv) > 1 else "toy"
    {"toy": toy, "tune": tune_thresholds, "pairs": cmd_pairs,
     "cf": cmd_cf, "clusters": cmd_clusters,
     "ablate_d": cmd_ablate_d}[cmd]()
