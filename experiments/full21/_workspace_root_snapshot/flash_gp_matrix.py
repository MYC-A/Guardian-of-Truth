#!/usr/bin/env python3
"""flash-gp-matrix: directive sec.8 2x2 matrix analysis over completed journals (prefix: flash).

Configurations (all on the same 94 E3a positive suspicions, same channel semantics):
  Base = E4b/A4 full-context verification      outputs/flash/e4b_a4_verify/verifications_flash.jsonl
  G    = graph-digest verification             outputs/flash/g1_graph_verify/verifications_flash.jsonl
  P    = obligation-centric verification       outputs/flash/p1_obligation_verify/verifications_flash.jsonl
  G+P  = graph digest inside P pipeline        outputs/flash/gp1_graph_obligation/verifications_flash.jsonl

Outputs:
  - per-configuration case-level confusion vs gold (>=1 CONFIRMED -> label 1)
  - per-configuration per-suspicion verdict distributions
  - paired flip tables Base->X (suspicion-level verdict changes, case-level label changes)
  - FAILED/UNCERTAIN treated as not-confirmed (never refutation), reported separately
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO = Path("/mnt/data/guardian/agent-workspace/flash-repo")
GOLD = REPO / "valid.parquet"
CFGS = {
    "Base": REPO / "outputs" / "flash" / "e4b_a4_verify" / "verifications_flash.jsonl",
    "G": REPO / "outputs" / "flash" / "g1_graph_verify" / "verifications_flash.jsonl",
    "P": REPO / "outputs" / "flash" / "p1_obligation_verify" / "verifications_flash.jsonl",
    "G+P": REPO / "outputs" / "flash" / "gp1_graph_obligation" / "verifications_flash.jsonl",
}
E3A = REPO / "outputs" / "flash" / "sources_superz_e4" / "a1r_cases.jsonl"
OUT = REPO / "outputs" / "flash" / "gp_matrix_analysis.json"


def latest_by_key(path: Path) -> dict[str, dict]:
    out: dict[str, dict] = {}
    if not path.is_file():
        return out
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


def load_suspicion_cases() -> dict[str, list[str]]:
    """case_id -> list of positive-suspicion keys (same enumeration as source)."""
    cases: dict[str, list[str]] = {}
    with open(E3A, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            cid = row["id"]
            for idx, s in enumerate(row.get("suspicions", [])):
                if s.get("label") == 1:
                    cases.setdefault(cid, []).append(f"{cid}#{idx}")
    return cases


def main() -> int:
    gold = {r["id"]: int(r["label"]) for _, r in pd.read_parquet(GOLD).iterrows()}
    susp_cases = load_suspicion_cases()

    journals = {name: latest_by_key(p) for name, p in CFGS.items()}

    def case_labels(name: str) -> tuple[dict[str, int], Counter, Counter]:
        j = journals[name]
        labels: dict[str, int] = {}
        susp_verdicts, tech = Counter(), Counter()
        for cid, keys in susp_cases.items():
            confirmed = False
            for k in keys:
                rec = j.get(k)
                v = rec.get("verdict") if rec and rec.get("status") == "OK" else None
                if v is None:
                    tech["FAILED_or_missing" if rec is None or rec.get("status") == "FAILED" else "missing"] += 1
                    v = "UNRESOLVED"
                else:
                    susp_verdicts[v] += 1
                if v == "CONFIRMED":
                    confirmed = True
            labels[cid] = 1 if confirmed else 0
        # cases without positive suspicions are label 0 by construction (E3a rule)
        for cid in gold:
            labels.setdefault(cid, 0)
        return labels, susp_verdicts, tech

    def metrics(labels: dict[str, int]) -> dict:
        tp = sum(1 for c, g in gold.items() if labels[c] == 1 and g == 1)
        fp = sum(1 for c, g in gold.items() if labels[c] == 1 and g == 0)
        fn = sum(1 for c, g in gold.items() if labels[c] == 0 and g == 1)
        tn = sum(1 for c, g in gold.items() if labels[c] == 0 and g == 0)
        pr = tp / (tp + fp) if tp + fp else 0.0
        rc = tp / (tp + fn) if tp + fn else 0.0
        f1 = 2 * pr * rc / (pr + rc) if pr + rc else 0.0
        return {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                "precision": round(pr, 4), "recall": round(rc, 4), "F1": round(f1, 4)}

    results = {}
    label_sets = {}
    for name in CFGS:
        labels, sv, tech = case_labels(name)
        label_sets[name] = labels
        results[name] = {
            "metrics": metrics(labels),
            "suspicion_verdicts": dict(sv),
            "technical": dict(tech),
            "journal_keys": len(journals[name]),
        }

    flips = {}
    for name in ("G", "P", "G+P"):
        case_flips = {
            "fp_eliminated": sorted(c for c in gold if label_sets["Base"][c] == 1 and gold[c] == 0 and label_sets[name][c] == 0),
            "tp_lost": sorted(c for c in gold if label_sets["Base"][c] == 1 and gold[c] == 1 and label_sets[name][c] == 0),
            "new_fp": sorted(c for c in gold if label_sets["Base"][c] == 0 and gold[c] == 0 and label_sets[name][c] == 1),
            "tp_gained": sorted(c for c in gold if label_sets["Base"][c] == 0 and gold[c] == 1 and label_sets[name][c] == 1),
        }
        # suspicion-level verdict transitions on shared OK-OK keys
        trans = Counter()
        base_j, x_j = journals["Base"], journals[name]
        for cid, keys in susp_cases.items():
            for k in keys:
                b, x = base_j.get(k), x_j.get(k)
                bv = b.get("verdict") if b and b.get("status") == "OK" else "UNRESOLVED"
                xv = x.get("verdict") if x and x.get("status") == "OK" else "UNRESOLVED"
                if bv != xv:
                    trans[f"{bv}->{xv}"] += 1
        flips[name] = {"case_level": case_flips, "suspicion_transitions": dict(trans)}

    # E3a unverified control for reference
    e3a_labels = {}
    with open(E3A, encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            e3a_labels[row["id"]] = int(row.get("a1r_label", 0) or 0)
    e3a_labels = {c: e3a_labels.get(c, 0) for c in gold}
    results["E3a_unverified_control"] = {"metrics": metrics(e3a_labels)}

    out = {
        "experiment": "directive sec.8 2x2 matrix: Base/G/P/G+P (flash)",
        "n_positive_suspicion_cases": len(susp_cases),
        "n_positive_suspicions": sum(len(v) for v in susp_cases.values()),
        "configurations": results,
        "flips_vs_Base": flips,
        "policy": "FAILED/missing/UNCERTAIN -> not confirmed; never treated as refutation",
    }
    OUT.write_text(json.dumps(out, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({k: v for k, v in out.items() if k != "flips_vs_Base"},
                     ensure_ascii=False, indent=1, default=str)[:3500])
    print(f"\nsaved {OUT}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
