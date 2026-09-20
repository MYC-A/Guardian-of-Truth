#!/usr/bin/env python3
"""E5 — ensemble / agreement analysis over all available per-case predictions.

Collects every prediction source present on disk:
  - e1 offline baseline (predictions.csv)
  - e2 A0 keyless judges (per provider per_case.json)
  - Codex frozen Mistral A0 (server records.jsonl)
  - e3a A1R re-anchored suspicion labels
  - e4 verified suspicion labels (per mode/provider)
  - e7 granite labels (when available)

Then measures: single-source metrics, OR/AND/2-of-N/majority ensembles over
judge pools, pairwise correlated-error structure (FP/FN intersections), and
per-combination won-TP / removed-FP versus a chosen reference.
Gold joined post-hoc; public46 is PUBLIC_SEEN — diagnostics only.
"""
from __future__ import annotations

import csv
import json
import sys
from itertools import combinations
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
OUT_ROOT = REPO / "outputs" / "superz_fullcycle" / "e5_ensemble"
CODEX_A0 = Path("/mnt/data/guardian/Guardian-research-a-83bbbb2/outputs/"
                "research_mistral_a_20260920/public46_full_A0/records.jsonl")
S_ROOT = REPO / "outputs" / "superz_fullcycle"


def metrics(preds: dict[str, int], gold: dict[str, int]) -> dict:
    tp = fp = fn = tn = 0
    for cid, g in gold.items():
        p = preds.get(cid)
        if p is None:
            p = 0
        if p == 1 and g == 1:
            tp += 1
        elif p == 1 and g == 0:
            fp += 1
        elif p == 0 and g == 1:
            fn += 1
        else:
            tn += 1
    prec = tp / (tp + fp) if tp + fp else 0.0
    rec = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * prec * rec / (prec + rec) if prec + rec else 0.0
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "precision": round(prec, 4), "recall": round(rec, 4), "F1": round(f1, 4)}


def load_sources() -> dict[str, dict[str, int]]:
    sources: dict[str, dict[str, int]] = {}

    # E1 offline baseline
    p = S_ROOT / "e1_offline_baseline" / "predictions.csv"
    if p.is_file():
        csv.field_size_limit(64 * 1024 * 1024)
        with open(p, newline="", encoding="utf-8") as f:
            rows = list(csv.DictReader(f))
        label_col = "label" if "label" in (rows[0] if rows else {}) else "prediction"
        if rows and label_col not in rows[0]:
            label_col = [k for k in rows[0] if "pred" in k.lower() or "label" in k.lower()]
            label_col = label_col[0] if label_col else None
        if label_col:
            sources["offline_baseline"] = {r["id"]: int(float(r[label_col])) for r in rows}

    # E2 judges
    e2 = S_ROOT / "e2_a0_cross"
    if e2.is_dir():
        for prov_dir in sorted(e2.iterdir()):
            pc = prov_dir / "per_case.json"
            if pc.is_file():
                data = json.loads(pc.read_text(encoding="utf-8"))
                sources[f"judge_{prov_dir.name}"] = {
                    cid: v["pred"] for cid, v in data.items() if v["pred"] is not None}

    # Codex frozen Mistral A0
    if CODEX_A0.is_file():
        preds = {}
        with open(CODEX_A0, encoding="utf-8") as f:
            for line in f:
                rec = json.loads(line)
                if rec.get("status") == "OK":
                    preds[rec["id"]] = int(rec.get("parsed", {}).get("label", 0))
        if preds:
            sources["judge_mistral_codex"] = preds

    # E3a A1R
    p = S_ROOT / "e3a_a1r_posthoc" / "a1r_cases.jsonl"
    if p.is_file():
        preds = {}
        with open(p, encoding="utf-8") as f:
            for line in f:
                row = json.loads(line)
                preds[row["id"]] = int(row["a1r_label"])
        sources["a1r_suspicions"] = preds

    # E4 verified
    e4 = S_ROOT / "e4_a34_verify"
    if e4.is_dir():
        for d in sorted(e4.iterdir()):
            cl = d / "case_labels.json"
            if cl.is_file():
                sources[f"verified_{d.name}"] = {
                    k: int(v) for k, v in json.loads(cl.read_text(encoding="utf-8")).items()}

    # E7 granite labels
    p = S_ROOT / "e7_offline_candidate" / "granite_case_labels.json"
    if p.is_file():
        sources["granite_local"] = {k: int(v) for k, v in json.loads(p.read_text(encoding="utf-8")).items()}

    return sources


def ensemble(pred_dicts: list[dict[str, int]], rule: str) -> dict[str, int]:
    ids = set()
    for d in pred_dicts:
        ids.update(d)
    out = {}
    n = len(pred_dicts)
    for cid in ids:
        votes = [d.get(cid, 0) for d in pred_dicts]
        ones = sum(1 for v in votes if v == 1)
        if rule == "or":
            out[cid] = int(ones >= 1)
        elif rule == "and":
            out[cid] = int(ones == n and n > 0)
        elif rule.startswith("k"):
            k = int(rule[1:])
            out[cid] = int(ones >= k)
        elif rule == "majority":
            out[cid] = int(ones * 2 > n)
    return out


def main() -> int:
    import pandas as pd
    gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(REPO / "valid.parquet").iterrows()}
    sources = load_sources()
    OUT_ROOT.mkdir(parents=True, exist_ok=True)

    single = {name: metrics(preds, gold) for name, preds in sources.items()}

    # judge pool for ensembles (A0-style judges only)
    judges = {k: v for k, v in sources.items() if k.startswith("judge_")}
    ens_results = {}
    combos = []
    names = sorted(judges)
    for r in range(2, len(names) + 1):
        combos.extend(combinations(names, r))
    for combo in combos:
        dicts = [judges[n] for n in combo]
        for rule in ("or", "and", "majority"):
            key = f"{rule}:{'+'.join(combo)}"
            ens_results[key] = metrics(ensemble(dicts, rule), gold)
    # k-of-N over the full judge pool
    if len(names) >= 2:
        for k in range(2, len(names) + 1):
            ens_results[f"k{k}_of_{len(names)}"] = metrics(ensemble(list(judges.values()), f"k{k}"), gold)

    # correlated error analysis over judges
    corr = {}
    for a, b in combinations(names, 2):
        fa = {cid for cid, p in judges[a].items() if p == 1 and gold.get(cid) == 0}
        fb = {cid for cid, p in judges[b].items() if p == 1 and gold.get(cid) == 0}
        na = {cid for cid, p in judges[a].items() if p == 0 and gold.get(cid) == 1}
        nb = {cid for cid, p in judges[b].items() if p == 0 and gold.get(cid) == 1}
        corr[f"{a}|{b}"] = {
            "fp_overlap": sorted(fa & fb), "fp_only_a": sorted(fa - fb), "fp_only_b": sorted(fb - fa),
            "fn_overlap": sorted(na & nb), "fn_only_a": sorted(na - nb), "fn_only_b": sorted(nb - na),
        }

    report = {
        "single_source": single,
        "ensembles": ens_results,
        "correlated_errors_judges": corr,
        "n_sources": len(sources),
    }
    (OUT_ROOT / "ensemble_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8")

    # master per-case matrix
    ids = sorted(gold)
    matrix = {cid: {"gold": gold[cid]} for cid in ids}
    for name, preds in sources.items():
        for cid in ids:
            matrix[cid][name] = preds.get(cid)
    (OUT_ROOT / "per_case_matrix.json").write_text(
        json.dumps(matrix, ensure_ascii=False, indent=1), encoding="utf-8")

    print("== SINGLE ==")
    for name, m in sorted(single.items(), key=lambda kv: -kv[1]["F1"]):
        print(f"{name:32s} TP{m['TP']:3d} FP{m['FP']:3d} FN{m['FN']:3d} TN{m['TN']:3d} F1={m['F1']}")
    print("\n== TOP ENSEMBLES (by F1) ==")
    for name, m in sorted(ens_results.items(), key=lambda kv: -kv[1]["F1"])[:12]:
        print(f"{name:60s} TP{m['TP']:3d} FP{m['FP']:3d} FN{m['FN']:3d} TN{m['TN']:3d} F1={m['F1']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
