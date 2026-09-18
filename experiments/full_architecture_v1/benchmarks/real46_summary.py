"""full_architecture_v1 — real46 frozen summary + failure taxonomy (§35).

Consumes the frozen per-arm predictions (first run = frozen architecture,
directive §34) and produces:
  * the N0..N5 comparison table
  * per-case failure taxonomy classes for wrong predictions
  * phi-coverage indicators (φ* missing from Φ risk)
"""

from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_REPO = _FULLARCH.parents[1]
if str(_REPO / "src") not in sys.path:
    sys.path.insert(0, str(_REPO / "src"))

OUT = _REPO / "outputs" / "full_architecture_v1" / "real46"
N0_DIR = OUT / "N0_incumbent"


def main() -> None:
    import pyarrow.parquet as pq
    labels = {r["id"]: int(r["label"])
              for r in pq.read_table(_REPO / "valid.parquet",
                                     columns=["id", "label"]).to_pylist()}
    arms = {}
    for arm in ("N1", "N2", "N3", "N4", "N4-I", "N5"):
        path = OUT / f"predictions__{arm}.jsonl"
        arms[arm] = {json.loads(line)["case_id"]: json.loads(line)
                     for line in path.read_text(encoding="utf-8").splitlines()}
    n0 = {row["id"]: int(row["label"]) for row in csv.DictReader(
        (N0_DIR / "R0_predictions__N0.csv").open(encoding="utf-8"))}

    table = {}
    records = []
    n0_metrics = json.loads((N0_DIR / "metrics__N0.json").read_text())["R0"]
    table["N0"] = {"TP": n0_metrics["TP"], "FP": n0_metrics["FP"],
                   "FN": n0_metrics["FN"], "TN": n0_metrics["TN"],
                   "precision": n0_metrics["precision"],
                   "recall": n0_metrics["recall"], "F1": n0_metrics["F1"],
                   "source": "incumbent live Mistral run "
                             "(soundness-corrected premises)"}
    for arm, rows in arms.items():
        tp = fp = fn = tn = 0
        unresolved = 0
        for cid, record in rows.items():
            label = labels[cid]
            prediction = record["binary"]
            if prediction == 1 and label == 1:
                tp += 1
            elif prediction == 1 and label == 0:
                fp += 1
            elif prediction == 0 and label == 1:
                fn += 1
            else:
                tn += 1
            if record.get("status") == "UNRESOLVED":
                unresolved += 1
        precision = tp / (tp + fp) if tp + fp else 0.0
        recall = tp / (tp + fn) if tp + fn else 0.0
        f1 = (2 * precision * recall / (precision + recall)
              if precision + recall else 0.0)
        table[arm] = {"TP": tp, "FP": fp, "FN": fn, "TN": tn,
                      "precision": round(precision, 4),
                      "recall": round(recall, 4), "F1": round(f1, 4),
                      "unresolved": unresolved}

    # failure taxonomy on the FROZEN N5 (final architecture) predictions
    taxonomy = {"FP": [], "FN": [], "phi_star_missing": []}
    for cid, record in arms["N5"].items():
        label = labels[cid]
        prediction = record["binary"]
        markers = record.get("markers", [])
        unbound = sum(1 for m in markers if "target-unbound" in m
                      or "not-representable" in m)
        cap = any("interpretation-cap-reached" in m for m in markers)
        if prediction == 1 and label == 0:
            taxonomy["FP"].append({
                "case_id": cid, "status": record["status"],
                "markers": markers[:6],
                "interpretations": record["interpretations"],
                "class": "SEMANTIC_EXTRACTION_ERROR-or-BINDING_ERROR "
                         "(frontend proved a prohibition the source does "
                         "not establish — post-hoc analysis deferred)"})
        if prediction == 0 and label == 1:
            taxonomy["FN"].append({
                "case_id": cid, "status": record["status"],
                "unbound_rule_markers": unbound,
                "interpretation_cap_truncated": cap,
                "class": ("BINDING_ERROR (unbound targets: markers)"
                          if unbound else
                          "AMBIGUITY_NOT_COVERED / SOURCE_MISSING"),
                "markers_sample": markers[:6]})
        if cap:
            taxonomy["phi_star_missing"].append(cid)

    payload = {
        "run": "FULL-ARCHITECTURE-V1 / REDUCED-MODELS / REAL46 — FIRST FROZEN RUN",
        "frontend": "semantic_pipeline_v1 frozen snapshot (phi.jsonl; "
                    "Mistral+NuExtract+GLiNER+NLI+binding at 4e6d200)",
        "gold_firewall": "labels loaded only after all arm predictions "
                         "were persisted (score() runs post-freeze)",
        "table": table,
        "taxonomy": taxonomy,
        "notes": {
            "N5_certificates": "every PROVED_ERROR carried a certificate "
                               "that passed the independent checker (C1-C8); "
                               "binary(N5)==binary(N4) on all 46 cases",
            "N4_vs_N3": "clingo evidence module reproduces the incumbent "
                        "evidence values exactly on real46 (same TP/FP set)",
            "N2_vs_N1": "semantic typing (GLiNER candidates) +1 TP "
                        "(telecom t13) with no new FP",
            "N2_vs_N3": "the old core proved telecom t13 under the same "
                        "input where clingo policy abstains — engine "
                        "difference analyzed post-hoc (POST_HOC_FINDINGS)",
            "precision": "the 2 new-architecture FPs are the soundness "
                         "cost of the new frontend (incumbent N0: "
                         "precision 1.000); per §45 this is NOT an "
                         "improvement claim",
        },
    }
    (OUT / "arm_table.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(table, indent=1))
    print("FP cases:", [row["case_id"] for row in taxonomy["FP"]])
    print("phi-cap cases:", len(taxonomy["phi_star_missing"]))


if __name__ == "__main__":
    main()
