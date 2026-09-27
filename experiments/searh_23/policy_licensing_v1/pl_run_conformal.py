"""IDEA G — calibrated selective prediction (MAPIE conformal).

Two mechanisms, BOTH fitted ONLY on the frozen calibration split
(6 cases, ~45 pairs); the test split is scored once at the end:

  G1  MAPIE MapieClassifier (method='aps') over a logistic-regression
      licensing model on local pair features:
        [ce_both_max, ce_policy_max, ce_tool_max, emb_sim, tool_sim,
         same_sentence, sentence_distance_inv]
      Accept an edge iff the APS prediction set is the singleton {RELATED};
      anything else abstains to UNKNOWN.

  G2  Target-precision threshold: smallest LR probability t such that
      empirical precision on the calibration split >= target
      (targets preregistered: 0.90 / 0.93 / 0.95); accepted iff p >= t.

  G3  (diagnostic) MAPIE with LLM features added (det_mistral one-hot,
      listwise-selection one-hot) - still fitted on calib only.

Outputs per split: coverage, mean set size, precision/recall among accepted
(non-abstained), abstention rate, error among non-abstained.

Run: python3 pl_run_conformal.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, out_dir, write_usage, load_splits

FEATURES = ["ce_both_max", "ce_policy_max", "ce_tool_max", "emb_sim",
            "tool_sim", "same_sentence", "sentence_distance_inv"]
LLM_FEATURES = ["det_related", "det_unknown", "listwise_hit"]


def pair_features(sig_row):
    ce_both_max = max(sig_row["ce_both_ab"], sig_row["ce_both_ba"])
    ce_policy_max = max(sig_row["ce_policy_ab"], sig_row["ce_policy_ba"])
    ce_tool_max = max(sig_row["ce_tool_ab"], sig_row["ce_tool_ba"])
    st = sig_row["struct"]
    return {
        "ce_both_max": ce_both_max,
        "ce_policy_max": ce_policy_max,
        "ce_tool_max": ce_tool_max,
        "emb_sim": sig_row["emb_sim"],
        "tool_sim": sig_row["tool_sim"],
        "same_sentence": float(st["same_sentence"]),
        "sentence_distance_inv": 1.0 / (1.0 + st["sentence_distance"]),
    }


def load_xy(suite_name, split, llm_extras=True):
    cases = load_suite(suite_name, split=split)
    suffix = "" if suite_name == "original" else "_" + suite_name
    sig_dir = out_dir("PAIR_signals" + suffix)
    det_dir = out_dir(f"det_mistral{suffix}")
    lw_dir = out_dir(f"listwise_mistral{suffix}")
    X, y, meta = [], [], []
    for case in cases:
        sig = json.loads((sig_dir / f"{case['case_id']}.json").read_text())
        det = {}
        dpath = det_dir / f"{case['case_id']}.json"
        if dpath.is_file():
            for r in json.loads(dpath.read_text())["rows"]:
                det[frozenset((r["a_eid"], r["b_eid"]))] = r.get("decision")
        lw = {}
        lpath = lw_dir / f"{case['case_id']}.json"
        if lpath.is_file():
            for r in json.loads(lpath.read_text())["rows"]:
                for c, s in zip(r.get("candidates", []), r.get("selected", [])):
                    lw[frozenset((r["eid"], c))] = str(s) in r.get("selected", [])
        for row in sig["pairs"]:
            f = pair_features(row)
            if llm_extras:
                d = det.get(frozenset((row["a_eid"], row["b_eid"])), "MISSING")
                f["det_related"] = 1.0 if d == "RELATED" else 0.0
                f["det_unknown"] = 1.0 if d == "UNKNOWN" else 0.0
                f["listwise_hit"] = 1.0 if lw.get(frozenset((row["a_eid"], row["b_eid"]))) else 0.0
            X.append([f[k] for k in (FEATURES + (LLM_FEATURES if llm_extras else []))])
            y.append(1 if row["gold"] == "POSITIVE" else 0)
            meta.append({"case_id": case["case_id"], "split": split,
                         "a_eid": row["a_eid"], "b_eid": row["b_eid"],
                         "gold": row["gold"], "hard": row["hard"]})
    return np.array(X), np.array(y), meta, (FEATURES + (LLM_FEATURES if llm_extras else []))


def metrics_for_accepted(y, y_pred, abstain_mask):
    n = len(y)
    accepted = ~abstain_mask
    n_acc = int(accepted.sum())
    if n_acc == 0:
        return {"accepted": 0, "abstention_rate": 1.0, "precision": None,
                "recall": None, "error_rate_nonabstained": None}
    tp = int(((y == 1) & (y_pred == 1) & accepted).sum())
    fp = int(((y == 0) & (y_pred == 1) & accepted).sum())
    fn = int(((y == 1) & ((y_pred == 0) | abstain_mask)).sum())
    err = int((y_pred != y)[accepted].sum())
    prec = tp / (tp + fp) if tp + fp else None
    rec = tp / (tp + fn) if tp + fn else None
    return {"accepted": n_acc, "abstention_rate": round(float(abstain_mask.mean()), 4),
            "precision": round(prec, 4) if prec is not None else None,
            "recall": round(rec, 4) if rec is not None else None,
            "tp": tp, "fp": fp, "fn": fn,
            "error_rate_nonabstained": round(err / n_acc, 4)}


def main():
    from sklearn.linear_model import LogisticRegression
    from mapie.classification import MapieClassifier

    results = {}

    for variant, llm_extras in [("local", False), ("with_llm", True)]:
        Xc, yc, _, names = load_xy("original", "calib", llm_extras)
        Xv, yv, mv, _ = load_xy("original", "val", llm_extras)
        Xt, yt, mt, _ = load_xy("original", "test", llm_extras)

        lr = LogisticRegression(max_iter=2000, class_weight="balanced")
        lr.fit(Xc, yc)

        # ---------- G1: MAPIE APS prediction sets ----------------------
        mapie = MapieClassifier(estimator=lr, method="aps", cv="prefit")
        mapie.fit_conformal(Xc, yc)  # calibrate ONLY on calib split
        out = {}
        for split, X, y, metas in (("calib", Xc, yc, None), ("val", Xv, yv, mv),
                                   ("test", Xt, yt, mt)):
            alpha = 0.10
            try:
                sets, _ = mapie.predict(X, alpha=alpha)
            except TypeError:
                _, sets = mapie.predict(X, alpha=alpha)
            # sets: list of arrays of predicted labels in the set
            sizes = [len(s) for s in sets]
            y_pred = np.array([1 if (len(s) == 1 and s[0] == 1) else 0 for s in sets])
            abstain = np.array([len(s) != 1 for s in sets])  # non-singleton => UNKNOWN
            m = metrics_for_accepted(y, y_pred, abstain)
            m["mean_set_size"] = round(float(np.mean(sizes)), 3)
            m["alpha"] = alpha
            out[split] = m

        # ---------- G2: target-precision thresholds --------------------
        probs = lr.predict_proba(Xc)[:, 1]
        thresholds = {}
        for target in (0.90, 0.93, 0.95):
            best = None
            for t in sorted(set(probs), reverse=True):
                sel = probs >= t
                if sel.sum() == 0:
                    continue
                p = yc[sel].mean()
                if p >= target:
                    best = float(t)
                    break
            thresholds[target] = best
        g2 = {}
        for target, t in thresholds.items():
            row = {"threshold": t}
            for split, X, y in (("calib", Xc, yc), ("val", Xv, yv), ("test", Xt, yt)):
                if t is None:
                    row[split] = None
                    continue
                p = lr.predict_proba(X)[:, 1]
                y_pred = (p >= t).astype(int)
                abstain = np.zeros(len(y), dtype=bool)  # thresholding: no abstain
                # abstention = not accepted
                abstain = p < t
                row[split] = metrics_for_accepted(y, y_pred, abstain)
            g2[str(target)] = row

        results[variant] = {
            "features": names,
            "n_calib": int(len(yc)), "n_val": int(len(yv)), "n_test": int(len(yt)),
            "G1_mapie_aps": out,
            "G2_target_precision": g2,
        }

    payload = {
        "fitted_on": "calibration split only (6 cases)",
        "preregistered_targets": [0.90, 0.93, 0.95],
        "results": results,
    }
    out_dir("G_conformal").joinpath("conformal.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage("G_conformal", {"phase": "conformal",
                                "lib": f"mapie+sklearn local features"})
    print(json.dumps({k: {"G1_test": v["G1_mapie_aps"]["test"],
                          "G2_0.93_test": v["G2_target_precision"]["0.93"]["test"]}
                      for k, v in results.items()}, indent=1))


if __name__ == "__main__":
    main()
