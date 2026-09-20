#!/usr/bin/env python3
"""A4 per-suspicion analysis (directive 2.1).

Для каждого подозрения: кто сформировал, тип нарушения, якорь, вердикт верификатора,
правильность (по case-gold + перекрёстной структуре), влияние на итоговое решение.
Метрики: correctly/wrongly confirmed/refuted, eliminated FP, lost TP, new FP,
final TP/FP/FN/TN и F1 vs E3a и контроли.
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
E3A = REPO / "outputs" / "superz_fullcycle" / "e3a_a1r_posthoc" / "a1r_cases.jsonl"
A4 = REPO / "outputs" / "superz_fullcycle" / "e4_a34_verify" / "a4_pollinations" / "verifications.jsonl"
GOLD = REPO / "valid.parquet"
OUT = REPO / "outputs" / "superz_fullcycle" / "e4_a34_verify" / "a4_analysis.json"

PRODUCER = "mistral-14b-latest (frozen Codex A0/A1 run)"


def main() -> int:
    gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(GOLD).iterrows()}

    e3a = {}
    with open(E3A, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            e3a[row["id"]] = row

    ver = {}
    with open(A4, encoding="utf-8") as f:
        for line in f:
            rec = json.loads(line)
            ver[rec["key"]] = rec

    # ---- per-suspicion table ----
    susp_rows = []
    for cid, row in e3a.items():
        for idx, s in enumerate(row.get("suspicions", [])):
            if s.get("label") != 1:
                continue
            key = f"{cid}#{idx}"
            v = ver.get(key)
            g = gold.get(cid, -1)
            verdict = v.get("verdict") if v and v.get("status") == "OK" else (
                "UNRESOLVED_TECH" if v else "MISSING")
            # case-gold approximation of per-suspicion correctness
            if verdict == "CONFIRMED":
                correct = "likely_correct" if g == 1 else "wrongly_confirmed"
            elif verdict == "REFUTED":
                correct = "likely_correct" if g == 0 else "case_has_error_but_suspicion_refuted"
            elif verdict == "UNCERTAIN":
                correct = "unresolved"
            else:
                correct = "technical_failure"
            susp_rows.append({
                "key": key, "case_id": cid, "producer": PRODUCER,
                "reason_type": s.get("reason_type"), "score": s.get("score"),
                "src_anchored": s.get("src_anchored"), "tgt_anchored": s.get("tgt_anchored"),
                "verifier": "pollinations/gpt-oss-20b", "verdict": verdict,
                "confidence": v.get("confidence") if v else None,
                "reason": (v.get("reason", "") if v else "")[:300],
                "case_gold": g,
                "correctness_class": correct,
            })

    # ---- case-level labels ----
    e4_label = {}
    for r in susp_rows:
        cid = r["case_id"]
        if r["verdict"] == "CONFIRMED":
            e4_label[cid] = 1
        elif cid not in e4_label:
            e4_label[cid] = 0

    # all cases: default 0 (no positive suspicion → 0 as in E3a)
    preds = {cid: e4_label.get(cid, 0) for cid in gold}

    def metrics(p):
        tp = sum(1 for c, g in gold.items() if p[c] == 1 and g == 1)
        fp = sum(1 for c, g in gold.items() if p[c] == 1 and g == 0)
        fn = sum(1 for c, g in gold.items() if p[c] == 0 and g == 1)
        tn = sum(1 for c, g in gold.items() if p[c] == 0 and g == 0)
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                "precision": round(pr, 4), "recall": round(rc, 4), "F1": round(f1, 4)}

    e3a_preds = {cid: row.get("a1r_label", 0) for cid, row in e3a.items()}
    e3a_preds = {cid: e3a_preds.get(cid, 0) for cid in gold}

    m_e4 = metrics(preds)
    m_e3a = metrics(e3a_preds)

    # ---- deltas vs E3a ----
    elim_fp = [c for c in gold if e3a_preds[c] == 1 and gold[c] == 0 and preds[c] == 0]
    lost_tp = [c for c in gold if e3a_preds[c] == 1 and gold[c] == 1 and preds[c] == 0]
    new_fp = [c for c in gold if e3a_preds[c] == 0 and gold[c] == 0 and preds[c] == 1]
    gained_tp = [c for c in gold if e3a_preds[c] == 0 and gold[c] == 1 and preds[c] == 1]

    # ---- verdict correctness stats ----
    vc = Counter(r["correctness_class"] for r in susp_rows)
    verdicts = Counter(r["verdict"] for r in susp_rows)

    # multi-suspicion cases
    multi = defaultdict(list)
    for r in susp_rows:
        multi[r["case_id"]].append(r["verdict"])
    multi_cases = {c: vs for c, vs in multi.items() if len(vs) > 1}
    multi_stats = {
        "n_cases_with_multiple_suspicions": len(multi_cases),
        "cases_all_refuted_but_gold1": sorted(
            c for c, vs in multi_cases.items() if all(v == "REFUTED" for v in vs) and gold[c] == 1),
        "cases_mixed": sorted(
            c for c, vs in multi_cases.items()
            if any(v == "CONFIRMED" for v in vs) and any(v == "REFUTED" for v in vs)),
    }

    out = {
        "experiment": "E4/A4 full-context cross-model verification — per-suspicion analysis",
        "producer": PRODUCER,
        "verifier": "pollinations/gpt-oss-20b (keyless), temperature 0",
        "n_positive_suspicions": len(susp_rows),
        "verdict_distribution": dict(verdicts),
        "correctness_classes": dict(vc),
        "metrics_e4_a4": m_e4,
        "metrics_e3a_unverified": m_e3a,
        "controls_reference": {
            "E1_offline_baseline": {"TP": 12, "FP": 0, "FN": 11, "TN": 23, "F1": 0.6857},
            "A0_mistral": {"TP": 22, "FP": 16, "FN": 1, "TN": 7, "F1": 0.7213},
            "E2_pollinations_judge": {"TP": 17, "FP": 6, "FN": 5, "TN": 11, "F1": 0.7556, "n": 39},
            "E5_AND_mistral_x_gptoss": {"TP": 16, "FP": 4, "FN": 7, "TN": 19, "F1": 0.7442},
            "E7_granite_OR_baseline": {"TP": 13, "FP": 0, "FN": 10, "TN": 23, "F1": 0.7222},
        },
        "delta_vs_e3a": {
            "eliminated_fp": elim_fp, "lost_tp": lost_tp,
            "new_fp": new_fp, "gained_tp": gained_tp,
        },
        "multi_suspicion": multi_stats,
        "unresolved_policy": "UNCERTAIN/FAILED/MISSING → not confirmed (case stays 0 unless another suspicion CONFIRMED)",
        "per_suspicion": susp_rows,
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    print(json.dumps({k: v for k, v in out.items() if k != "per_suspicion"},
                     ensure_ascii=False, indent=2))
    print(f"\nper-suspicion table saved: {OUT} ({len(susp_rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
