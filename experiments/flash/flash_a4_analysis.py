#!/usr/bin/env python3
"""flash-a4-analysis: per-suspicion analysis of the completed E4b/A4 verification (prefix: flash).

Directive sec. 2.1 metrics, computed over the COMBINED verification journal:
  - who produced each suspicion (frozen Codex Mistral A0/A1 producer),
  - which violation was alleged, on which anchored facts,
  - what the verifier (pollinations AND, where pollinations failed, blockrun) said,
  - per-suspicion correctness approximated by case gold (documented approximation),
  - effect on the final decision: eliminated FP / lost TP / new FP / gained TP,
  - final TP/FP/FN/TN + F1 vs E3a control and other line controls,
  - verifier-model dependence (pollinations vs blockrun agreement on shared keys),
  - multi-suspicion case handling (CONFIRMED/REFUTED are per-suspicion, not per-case).

Policy (explicit, per directive sec.18): UNCERTAIN / FAILED / MISSING verdicts never
count as refutation; a case stays label=1 only if >=1 suspicion CONFIRMED.
"""
from __future__ import annotations

import csv
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path(__file__).resolve().parents[2]
SRC = REPO / "outputs" / "flash" / "sources_superz_e4"
E3A = SRC / "a1r_cases.jsonl"
GOLD = REPO / "valid.parquet"
OUT_DIR = REPO / "outputs" / "flash" / "e4b_a4_verify"
POLL = SRC / "a4_pollinations" / "verifications.jsonl"
FLASH = OUT_DIR / "verifications_flash.jsonl"
OUT_JSON = OUT_DIR / "a4_analysis_flash.json"
OUT_CSV = OUT_DIR / "a4_persuspicion_flash.csv"

PRODUCER = "mistral-14b-latest (frozen Codex A0/A1 run)"
VERIFIER_POLL = "pollinations/gpt-oss-20b"
VERIFIER_BLOCKRUN = "blockrun pool (gpt-oss-120b-class)"


def latest_by_key(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if path.is_file():
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            out[rec["key"]] = rec
    return out


def combined_verdicts() -> tuple[dict[str, dict], dict[str, dict]]:
    """Return (per-key combined verdict records, per-key dual-verdict map)."""
    poll = latest_by_key(POLL)
    flash = latest_by_key(FLASH)
    combined, dual = {}, {}
    for key in set(poll) | set(flash):
        p, f = poll.get(key), flash.get(key)
        p_ok = p is not None and p.get("status") == "OK"
        f_ok = f is not None and f.get("status") == "OK"
        if p_ok:
            chosen, verifier = p, VERIFIER_POLL
        elif f_ok:
            chosen, verifier = f, VERIFIER_BLOCKRUN
        else:
            chosen, verifier = (p or f or {}), "UNRESOLVED_TECH"
        rec = dict(chosen)
        rec["verifier_used"] = verifier
        if p_ok and f_ok:
            rec["agreement"] = "agree" if p["verdict"] == f["verdict"] else "disagree"
            rec["verdict_blockrun"] = f["verdict"]
        else:
            rec["agreement"] = "single_channel"
        combined[key] = rec
        dual[key] = {"pollinations": p.get("verdict") if p_ok else (p or {}).get("status"),
                     "blockrun": f.get("verdict") if f_ok else (f or {}).get("status")}
    return combined, dual


def main() -> int:
    gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(GOLD).iterrows()}

    e3a = {}
    with open(E3A, encoding="utf-8") as fh:
        for line in fh:
            row = json.loads(line)
            e3a[row["id"]] = row

    combined, dual = combined_verdicts()

    susp_rows = []
    for cid, row in e3a.items():
        for idx, s in enumerate(row.get("suspicions", [])):
            if s.get("label") != 1:
                continue
            key = f"{cid}#{idx}"
            v = combined.get(key)
            g = gold.get(cid, -1)
            verdict = v.get("verdict") if v and v.get("status") == "OK" else (
                "UNRESOLVED_TECH" if v else "MISSING")
            # case-gold approximation of per-suspicion correctness (documented)
            if verdict == "CONFIRMED":
                correct = "likely_correct" if g == 1 else "wrongly_confirmed"
            elif verdict == "REFUTED":
                correct = "likely_correct" if g == 0 else "wrongly_refuted"
            elif verdict in ("UNCERTAIN",):
                correct = "unresolved_by_design"
            else:
                correct = "technical_failure"
            susp_rows.append({
                "key": key, "case_id": cid, "producer": PRODUCER,
                "reason_type": s.get("reason_type"), "score": s.get("score"),
                "src_anchored": s.get("src_anchored"), "tgt_anchored": s.get("tgt_anchored"),
                "verifier": v.get("verifier_used") if v else "MISSING",
                "verdict": verdict,
                "confidence": v.get("confidence") if v else None,
                "verifier_agreement": v.get("agreement") if v else "n/a",
                "verdict_blockrun": v.get("verdict_blockrun") if v else None,
                "reason": (v.get("reason", "") if v else "")[:300],
                "case_gold": g,
                "correctness_class": correct,
            })

    # ---- case-level labels (policy: >=1 CONFIRMED -> 1) ----
    e4_label: dict[str, int] = {}
    for r in susp_rows:
        cid = r["case_id"]
        if r["verdict"] == "CONFIRMED":
            e4_label[cid] = 1
        elif cid not in e4_label:
            e4_label[cid] = 0
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

    e3a_preds = {cid: int(row.get("a1r_label", 0) or 0) for cid, row in e3a.items()}
    e3a_preds = {cid: e3a_preds.get(cid, 0) for cid in gold}
    # pollinations-only projection (what the interrupted session would have concluded)
    poll_only_label: dict[str, int] = {}
    for r in susp_rows:
        cid = r["case_id"]
        if r["verifier"].startswith("pollinations") and r["verdict"] == "CONFIRMED":
            poll_only_label[cid] = 1
        elif cid not in poll_only_label:
            poll_only_label[cid] = 0
    poll_only_preds = {cid: poll_only_label.get(cid, 0) for cid in gold}

    m_e4 = metrics(preds)
    m_e3a = metrics(e3a_preds)
    m_poll_only = metrics(poll_only_preds)

    elim_fp = [c for c in gold if e3a_preds[c] == 1 and gold[c] == 0 and preds[c] == 0]
    lost_tp = [c for c in gold if e3a_preds[c] == 1 and gold[c] == 1 and preds[c] == 0]
    new_fp = [c for c in gold if e3a_preds[c] == 0 and gold[c] == 0 and preds[c] == 1]
    gained_tp = [c for c in gold if e3a_preds[c] == 0 and gold[c] == 1 and preds[c] == 1]

    vc = Counter(r["correctness_class"] for r in susp_rows)
    verdicts = Counter(r["verdict"] for r in susp_rows)
    by_type = defaultdict(Counter)
    for r in susp_rows:
        by_type[r["reason_type"]][r["verdict"]] += 1

    # verifier-model dependence on shared keys
    agree = Counter(r["verifier_agreement"] for r in susp_rows)
    dual_detail = {k: v for k, v in dual.items() if v["pollinations"] and v["blockrun"]}
    disagree_keys = [k for k, v in dual.items()
                     if v["pollinations"] in ("CONFIRMED", "REFUTED", "UNCERTAIN")
                     and v["blockrun"] in ("CONFIRMED", "REFUTED", "UNCERTAIN")
                     and v["pollinations"] != v["blockrun"]]

    multi = defaultdict(list)
    for r in susp_rows:
        multi[r["case_id"]].append(r["verdict"])
    multi_cases = {c: vs for c, vs in multi.items() if len(vs) > 1}
    multi_stats = {
        "n_cases_with_multiple_positive_suspicions": len(multi_cases),
        "cases_all_refuted_but_gold1": sorted(
            c for c, vs in multi_cases.items() if all(v == "REFUTED" for v in vs) and gold[c] == 1),
        "cases_mixed": sorted(
            c for c, vs in multi_cases.items()
            if any(v == "CONFIRMED" for v in vs) and any(v == "REFUTED" for v in vs)),
        "note": "REFUTED on one suspicion does not clear other violations of the same response",
    }

    out = {
        "experiment": "E4b/A4 full-context cross-model verification — completed per-suspicion analysis (flash)",
        "provenance": {
            "source_workspace": "Guardian-superz-fullcycle @ 1c47059 (branch research/independent-fullcycle-20260920-superz, local-only, read-only copy)",
            "interrupted_state": "goal quoted intermediate 7 CONFIRMED / 9 REFUTED; journal at interruption: 24 CONFIRMED / 39 REFUTED / 15 FAILED over 82 records",
            "flash_completion": "FAILED/missing keys re-verified with blockrun (independent channel), identical A4 prompt",
        },
        "producer": PRODUCER,
        "verifiers": [VERIFIER_POLL, VERIFIER_BLOCKRUN],
        "n_positive_suspicions": len(susp_rows),
        "verdict_distribution": dict(verdicts),
        "correctness_classes": dict(vc),
        "verifier_model_dependence": {
            "shared_keys_with_dual_verdict": len(dual_detail),
            "agreement_counts": dict(agree),
            "disagreement_keys": sorted(disagree_keys)[:20],
        },
        "metrics_e4_a4_completed": m_e4,
        "metrics_e4_a4_pollinations_only_projection": m_poll_only,
        "metrics_e3a_unverified_control": m_e3a,
        "controls_reference": {
            "E1_offline_baseline": {"TP": 12, "FP": 0, "FN": 11, "TN": 23, "F1": 0.6857},
            "A0_mistral": {"TP": 22, "FP": 16, "FN": 1, "TN": 7, "F1": 0.7213},
            "E2_pollinations_judge": {"TP": 17, "FP": 6, "FN": 5, "TN": 11, "F1": 0.7556, "n": 39},
            "E5_AND_mistral_x_gptoss": {"TP": 16, "FP": 4, "FN": 7, "TN": 19, "F1": 0.7442},
            "E7_granite_OR_baseline": {"TP": 13, "FP": 0, "FN": 10, "TN": 23, "F1": 0.7222},
            "ifc_ensemble_baseline_OR_granite_grounded": {"TP": 20, "FP": 2, "FN": 3, "TN": 21, "F1": 0.8889},
        },
        "delta_vs_e3a": {
            "eliminated_fp": elim_fp, "lost_tp": lost_tp,
            "new_fp": new_fp, "gained_tp": gained_tp,
        },
        "verdicts_by_reason_type": {k: dict(v) for k, v in sorted(by_type.items())},
        "multi_suspicion": multi_stats,
        "unresolved_policy": "UNCERTAIN/FAILED/MISSING -> not confirmed (case stays 0 unless another suspicion CONFIRMED); technical failure never treated as REFUTED",
        "producer_dependence_note": "producer is fixed (frozen Codex run) in this experiment; producer-dependence is addressed by cross-verifier check here and must be varied in a follow-up",
    }
    OUT_JSON.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")

    with open(OUT_CSV, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(susp_rows[0].keys()))
        w.writeheader()
        w.writerows(susp_rows)

    print(json.dumps({k: v for k, v in out.items() if k not in ("per_suspicion",)},
                     ensure_ascii=False, indent=1, default=str)[:4000])
    print(f"\nsaved: {OUT_JSON}\nsaved: {OUT_CSV} ({len(susp_rows)} rows)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
