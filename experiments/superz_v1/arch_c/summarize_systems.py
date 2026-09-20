"""Final synth32 systems comparison: C variants vs direct judge vs hybrids.

All numbers come from runs on the SAME dataset (synth_pairs_v1, 32 cases,
labels by construction) with per-case predictions stored under results/.
No new LLM calls — this is pure aggregation.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

HERE = Path(__file__).resolve().parent
RESULTS = HERE.parent / "results"
LABELS = json.loads((HERE.parent / "data" / "synth_pairs" / "labels_local.json").read_text())


def met(preds: dict[str, int]) -> dict:
    tp = fp = fn = tn = 0
    for cid, p in preds.items():
        g = LABELS.get(cid)
        if g is None:
            continue
        tp += p == 1 and g == 1
        fp += p == 1 and g == 0
        fn += p == 0 and g == 1
        tn += p == 0 and g == 0
    P = tp / (tp + fp) if tp + fp else 0.0
    R = tp / (tp + fn) if tp + fn else 0.0
    F = 2 * P * R / (P + R) if P + R else 0.0
    return {"n": len(preds), "TP": tp, "FP": fp, "FN": fn, "TN": tn,
            "P": round(P, 4), "R": round(R, 4), "F1": round(F, 4)}


def preds_c(variant: str, field: str = "label_lenient") -> dict[str, int]:
    pc = json.loads((RESULTS / "arch_c_e2e" / variant / "per_case.json").read_text())
    return {cid: c[field] for cid, c in pc.items()}


def preds_a0_mistral() -> dict[str, int]:
    out = {}
    for f in (RESULTS / "arch_a" / "A0_mistral_synth").glob("*.json"):
        r = json.loads(f.read_text())
        if r.get("ok") and r.get("label") in (0, 1):
            out[r["id"]] = r["label"]
    return out


def preds_b1_glm() -> dict[str, int]:
    out = {}
    for f in (RESULTS / "arch_b" / "B1").glob("synth__*.json"):
        r = json.loads(f.read_text())
        if r.get("ok"):
            out[r["id"]] = 1 if r.get("suspicions") else 0
    return out


def preds_b1_mistral() -> dict[str, int]:
    out = {}
    for f in (RESULTS / "arch_b" / "B1_mistral_synth").glob("*.json"):
        r = json.loads(f.read_text())
        if r.get("ok"):
            out[r["id"]] = 1 if r.get("suspicions") else 0
    return out


def main() -> None:
    c = {v: preds_c(v) for v in ("C0", "C1", "C2m", "C3")}
    c["C3_strict"] = preds_c("C3", "label_strict")
    a0m = preds_a0_mistral()
    b1g = preds_b1_glm()
    b1m = preds_b1_mistral()

    rows = {
        "A0-mistral direct judge": met(a0m),
        "B1-mistral suspicion judge": met(b1m),
        "B1-glm suspicion judge": met(b1g),
        "C0 glm-theory -> formal": met(c["C0"]),
        "C1 union-theory -> formal": met(c["C1"]),
        "C2m one-sided-aggressive -> formal": met(c["C2m"]),
        "C3 (+consequence flags, strict)": met(c["C3_strict"]),
    }
    # simple hybrids on the common case set
    common = set(a0m) & set(c["C1"])
    hyb_or = {cid: 1 if (a0m[cid] == 1 or c["C1"][cid] == 1) else 0 for cid in common}
    hyb_and = {cid: 1 if (a0m[cid] == 1 and c["C1"][cid] == 1) else 0 for cid in common}
    rows["Hybrid A0m OR C1"] = met(hyb_or)
    rows["Hybrid A0m AND C1 (C as filter)"] = met(hyb_and)

    common_b = set(b1g) & set(c["C1"])
    hyb_b = {cid: 1 if (b1g[cid] == 1 or c["C1"][cid] == 1) else 0 for cid in common_b}
    rows["Hybrid B1g OR C1"] = met(hyb_b)

    out = {"dataset": "synth_pairs_v1 (32 cases, 4 policies, labels by construction)",
           "providers": {"judge_a0m_b1m": "mistral", "b1g": "zai-glm",
                         "theory_A": "zai-glm (cached from arch_c_cross)",
                         "theory_B": "mistral",
                         "hypgen+formalize": "mistral",
                         "formal_engine": "arch_d typed templates + resolver + clingo"},
           "systems": rows}
    (RESULTS / "arch_c_e2e" / "systems_comparison.json").write_text(
        json.dumps(out, ensure_ascii=False, indent=1))
    print(json.dumps(rows, ensure_ascii=False, indent=1))


if __name__ == "__main__":
    main()
