"""Post-seal scoring and assembly (directive §18-§22).

Runs ONLY after every mode's predictions are sealed. This is the first step
that reads the label/explanation columns (gold firewall lift).

Produces:
- outputs/vnext/real_valid/metrics.json               (§31 metrics per mode)
- outputs/vnext/real_valid/cases.jsonl                (§19 per-case audit)
- outputs/vnext/real_valid/premise_coverage.csv       (§12 dependency classes)
- outputs/vnext/real_valid/failure_decomposition.json (§22 root-cause tables)
"""
from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from pathlib import Path

import pandas as pd

REPO_ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = REPO_ROOT / "outputs" / "vnext" / "real_valid"
import sys

sys.path.insert(0, str(REPO_ROOT))
sys.path.insert(0, str(REPO_ROOT / "src"))
sys.path.insert(0, str(REPO_ROOT / "scripts"))

MODES = ("R0", "R1", "R2")


def load_mode(mode: str) -> list[dict]:
    if mode == "R0":
        path = OUT_DIR / "baseline_attemptA_progress.json"
    else:
        path = OUT_DIR / mode / f"{mode}_progress.json"
    return json.loads(path.read_text(encoding="utf-8"))


def binary_of(row: dict) -> int:
    """Frozen product adapter COMPETITION mode mapping (fixed before gold)."""
    status = row["core_status"]
    if status == "PROVED_ERROR":
        return 1
    if status == "PROVED_NO_ERROR":
        return 0
    if status == "INCONSISTENT":
        return 1
    return 0  # UNRESOLVED / EXECUTION_ERROR


def verify_seals() -> dict:
    seals = {}
    for mode in MODES:
        if mode == "R0":
            # R0 = attempt A; build the seal on the fly (write-once)
            rows = load_mode("R0")
            predictions = sorted(((row["case_id"], binary_of(row)) for row in rows))
            payload = "\n".join(f"{cid},{label}" for cid, label in predictions).encode()
            seals["R0"] = {"predictions_sha256": hashlib.sha256(payload).hexdigest(),
                           "case_count": len(rows), "gold_joined": False}
            continue
        seal_path = OUT_DIR / mode / f"{mode}_prediction_seal.json"
        seal = json.loads(seal_path.read_text(encoding="utf-8"))
        csv_path = OUT_DIR / mode / f"{mode}_predictions.csv"
        digest = hashlib.sha256(csv_path.read_bytes()).hexdigest()
        if digest != seal["predictions_sha256"]:
            raise SystemExit(f"{mode}: predictions file changed after sealing!")
        # also verify the CSV content matches the progress binary mapping
        with open(csv_path, encoding="utf-8") as handle:
            reader = csv.DictReader(handle)
            for record in reader:
                row = next(item for item in load_mode(mode) if item["case_id"] == record["id"])
                if int(record["label"]) != binary_of(row):
                    raise SystemExit(f"{mode}: CSV label diverges from adapter mapping for {record['id']}")
        seals[mode] = seal
    return seals


def confusion(rows: list[dict], gold: dict) -> dict:
    tp = fp = fn = tn = 0
    for row in rows:
        predicted = binary_of(row)
        actual = gold[row["case_id"]]
        if predicted == 1 and actual == 1:
            tp += 1
        elif predicted == 1 and actual == 0:
            fp += 1
        elif predicted == 0 and actual == 1:
            fn += 1
        else:
            tn += 1
    precision = tp / (tp + fp) if tp + fp else 0.0
    recall = tp / (tp + fn) if tp + fn else 0.0
    f1 = 2 * precision * recall / (precision + recall) if precision + recall else 0.0
    statuses = Counter(row["core_status"] for row in rows)
    return {
        "TP": tp, "FP": fp, "FN": fn, "TN": tn,
        "precision": round(precision, 4), "recall": round(recall, 4), "f1": round(f1, 4),
        "status_counts": dict(statuses),
        "PROVED_ERROR": statuses.get("PROVED_ERROR", 0),
        "PROVED_NO_ERROR": statuses.get("PROVED_NO_ERROR", 0),
        "UNRESOLVED": statuses.get("UNRESOLVED", 0) + statuses.get("EXECUTION_ERROR", 0),
        "INCONSISTENT": statuses.get("INCONSISTENT", 0),
        "certified_definitive": sum(1 for row in rows
                                    if row["core_status"] in ("PROVED_ERROR", "PROVED_NO_ERROR")
                                    and row.get("certificate_valid")),
        "false_certified_ERROR": sum(1 for row in rows if row["core_status"] == "PROVED_ERROR"
                                     and gold[row["case_id"]] == 0
                                     and row.get("certificate_valid")),
        "false_certified_NO_ERROR": sum(1 for row in rows if row["core_status"] == "PROVED_NO_ERROR"
                                        and gold[row["case_id"]] == 1
                                        and row.get("certificate_valid")),
        "uncertified_definitive": sum(1 for row in rows
                                      if row["core_status"] in ("PROVED_ERROR", "PROVED_NO_ERROR")
                                      and not row.get("certificate_valid")),
    }


# §22 primitive categories mapped from observed signals
def primitive_category(row: dict, gold_status: int) -> str:
    status = row["core_status"]
    failures = {(item["component"], item["kind"]) for item in row.get("frontend_failures", [])}
    summary = row.get("component_summary") or {}
    diagnostics = row.get("diagnostics") or {}
    primary = diagnostics.get("primary")
    if status == "EXECUTION_ERROR":
        return "OTHER"
    predicted = binary_of(row)
    if predicted == gold_status:
        return "CORRECT"
    if failures:
        component, kind = sorted(failures)[0]
        if component.startswith("policy_h0"):
            return "POLICY_PARSE" if kind in ("TRANSPORT", "SCHEMA") else "POLICY_PARSE"
        if component.startswith("goal"):
            return "GOAL_PARSE"
    if status == "PROVED_ERROR" and gold_status == 0:
        return "EFFECT_REASONING" if row.get("t2_premises") else "CLAIM_PARSE"
    if status in ("UNRESOLVED", "INCONSISTENT"):
        if gold_status == 1:
            if summary.get("claim_axes", 0) == 0 and not row.get("target", {}).get("tool_calls"):
                return "CLAIM_PARSE"
            if primary in ("ENTITY_UNBOUND", "ENTITY_AMBIGUOUS"):
                return "ENTITY_BINDING"
            if primary == "TIME_UNBOUND":
                return "TEMPORAL_REASONING"
            if primary == "CAUSALITY_UNPROVED":
                return "EFFECT_REASONING"
            if not row.get("trusted_effect_count") and row.get("t2_premises") is not None:
                return "MISSING_T1"
            if summary.get("goal_options", 0) == 0:
                return "GOAL_PARSE"
            return "STATE_EVIDENCE"
        return "STATE_EVIDENCE"
    return "OTHER"


def main() -> None:
    seals = verify_seals()
    frame = pd.read_parquet(REPO_ROOT / "valid.parquet")
    gold = {str(row["id"]): int(row["label"]) for _, row in frame.iterrows()}
    explanations = {str(row["id"]): (row["explanation"] if isinstance(row["explanation"], str) else "")
                    for _, row in frame.iterrows()}

    metrics = {"sealed": {mode: seals[mode] for mode in MODES},
               "gold_distribution": Counter(gold.values())}
    rows_by_mode = {mode: load_mode(mode) for mode in MODES}

    for mode in MODES:
        metrics[mode] = confusion(rows_by_mode[mode], gold)

    # failure decomposition (§22) on the primary mode R1
    decomp = defaultdict(Counter)
    for row in rows_by_mode["R1"]:
        category = primitive_category(row, gold[row["case_id"]])
        predicted = binary_of(row)
        bucket = ("FP" if predicted == 1 and gold[row["case_id"]] == 0
                  else "FN" if predicted == 0 and gold[row["case_id"]] == 1
                  else "UNRESOLVED" if row["core_status"] in ("UNRESOLVED", "EXECUTION_ERROR", "INCONSISTENT")
                  else "OK")
        decomp[category][bucket] += 1
    failure_table = {category: {"FP": counts.get("FP", 0), "FN": counts.get("FN", 0),
                                "UNRESOLVED": counts.get("UNRESOLVED", 0),
                                "total": sum(counts.values())}
                     for category, counts in sorted(decomp.items())}

    # dependency table (§22 second table)
    dependency = Counter()
    for row in rows_by_mode["R1"]:
        if row["core_status"] in ("PROVED_ERROR", "PROVED_NO_ERROR") and not row.get("t2_premises"):
            dependency["works without T1 (no T2 needed for the verdict)"] += 1
        elif row["core_status"] in ("PROVED_ERROR", "PROVED_NO_ERROR") and row.get("t2_premises"):
            dependency["verdict used prompt-derived/T2 semantics"] += 1
        elif (row.get("component_summary") or {}).get("policy_reading_count", 0) == 0 \
                and any(f["component"].startswith("policy") for f in row.get("frontend_failures", [])):
            dependency["blocked by policy parse"] += 1
        elif (row.get("component_summary") or {}).get("goal_options", 0) == 0:
            dependency["goal axis produced no contract"] += 1
        else:
            dependency["blocked by missing current-state evidence / binding"] += 1

    (OUT_DIR / "metrics.json").write_text(
        json.dumps({"metrics": metrics, "failure_decomposition_R1": failure_table,
                    "dependency_table_R1": dict(dependency)},
                   ensure_ascii=False, indent=1, default=dict), encoding="utf-8")

    # §19 cases.jsonl — merge modes
    envelope = json.loads((OUT_DIR / "dataset_envelope.json").read_text(encoding="utf-8"))
    env_by_id = {case["id"]: case for case in envelope["cases"]}
    with open(OUT_DIR / "cases.jsonl", "w", encoding="utf-8") as handle:
        for row in sorted(rows_by_mode["R1"], key=lambda item: item["case_id"]):
            case_id = row["case_id"]
            env = env_by_id[case_id]
            record = {
                "id": case_id,
                "domain_posthoc": env["domain"],
                "gold_label_posthoc": gold[case_id],
                "gold_explanation_posthoc": explanations[case_id][:600],
                "input": row.get("input", {}),
                "environment": row.get("environment", {}),
                "target": row.get("target", {}),
                "required_premises": row.get("required_premises", []),
                "t2_premises": row.get("t2_premises", []),
                "R0": next(({"core_status": r["core_status"]} for r in rows_by_mode["R0"]
                            if r["case_id"] == case_id), None),
                "R1": {"core_status": row["core_status"], "binary": binary_of(row),
                       "certificate_valid": row.get("certificate_valid"),
                       "frontend_failures": row.get("frontend_failures", []),
                       "component_summary": row.get("component_summary", {}),
                       "diagnostics": row.get("diagnostics", {}),
                       "false_witnesses": row.get("false_witnesses", [])},
                "R2": next(({"core_status": r["core_status"], "binary": binary_of(r),
                             "certificate_valid": r.get("certificate_valid")}
                            for r in rows_by_mode["R2"] if r["case_id"] == case_id), None),
                "manual_t1_required": bool(row.get("t2_premises") is not None
                                           and not row.get("trusted_effect_count")),
                "missing_information": (row.get("diagnostics") or {}).get("missing_evidence", [])[:8],
                "proof": {
                    "core_status": row["core_status"],
                    "certificate_valid": row.get("certificate_valid"),
                    "false_witnesses": row.get("false_witnesses", []),
                    "unknown_reasons": (row.get("diagnostics") or {}).get("missing_evidence", [])[:8],
                },
                "failure_category_R1": primitive_category(row, gold[case_id]),
            }
            handle.write(json.dumps(record, ensure_ascii=False) + "\n")

    # §12 premise coverage CSV
    with open(OUT_DIR / "premise_coverage.csv", "w", newline="", encoding="utf-8") as handle:
        writer = csv.writer(handle)
        writer.writerow(["id", "verdict_R1", "works_without_T1", "used_T2", "trusted_effects",
                         "t2_premise_count", "required_premise_count", "classification"])
        for row in rows_by_mode["R1"]:
            verdict = row["core_status"]
            used_t2 = bool(row.get("t2_premises"))
            trusted = row.get("trusted_effect_count", 0)
            if verdict in ("PROVED_ERROR", "PROVED_NO_ERROR") and not used_t2:
                classification = "WORKS_WITHOUT_T1"
            elif verdict in ("PROVED_ERROR", "PROVED_NO_ERROR") and used_t2:
                classification = "PROMPT_DERIVED_T2"
            else:
                classification = "UNRESOLVED_T1_DEPENDENT" if trusted == 0 and used_t2 else "UNRESOLVED_OTHER"
            writer.writerow([row["case_id"], verdict,
                             int(verdict in ("PROVED_ERROR", "PROVED_NO_ERROR") and not used_t2),
                             int(used_t2), trusted,
                             len(row.get("t2_premises") or []),
                             len(row.get("required_premises") or []),
                             classification])

    print(json.dumps({"metrics": {mode: metrics[mode] for mode in MODES},
                      "failure_decomposition_R1": failure_table,
                      "dependency_table_R1": dict(dependency)},
                     ensure_ascii=False, indent=1, default=dict))


if __name__ == "__main__":
    main()
