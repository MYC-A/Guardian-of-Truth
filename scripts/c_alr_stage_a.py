#!/usr/bin/env python3
"""C-ALR Stage A — deterministic offline decomposition of sealed V6.

Per docs/vnext/C_ALR_CYCLE_PROTOCOL.md section 4:
  - no LLM, no network, no RNG, no manual rescoring;
  - inputs: sealed bundle (per-case C/B4 joined gold results) + preregistered gates;
  - outputs: quadrant decomposition, B4 failure stage attribution (sealed logs only),
    B4 gain recoverability (typed-field diff phi_C vs gold restricted to the frozen
    mutation catalog), Oracle(C + recoverable corrections), STOP-gate verdict.

Exit codes: 0 = report produced (verdict inside), 2 = input/validation error.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
DEFAULT_PREREG = REPO / "docs/vnext/C_ALR_PREREG_GATES_V1.json"

ATTRIBUTION_LABELS = (
    "slot_primary",
    "mutation_generation",
    "admission",
    "compiler",
    "gold_benchmark_issue",
    "other",
    "UNATTRIBUTED_NO_LOGS",
)
STAGE_BOOLEAN_ORDER = ("slot_primary_valid", "mutation_generation_valid", "admission_valid", "compiler_valid")
STAGE_BOOLEAN_TO_LABEL = {
    "slot_primary_valid": "slot_primary",
    "mutation_generation_valid": "mutation_generation",
    "admission_valid": "admission",
    "compiler_valid": "compiler",
}
RECOVERABILITY_LABELS = ("LOCAL_PATCH_RECOVERABLE", "REQUIRES_GLOBAL_REPARSE", "UNCERTAIN", "NOT_RECOVERABLE")


def sha256_of(path: Path) -> str:
    h = hashlib.sha256()
    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(65536), b""):
            h.update(chunk)
    return h.hexdigest()


def fail(msg: str) -> None:
    print(f"STAGE_A_ERROR: {msg}", file=sys.stderr)
    sys.exit(2)


def load_json(path: Path) -> dict:
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except FileNotFoundError:
        fail(f"file not found: {path}")
    except json.JSONDecodeError as e:
        fail(f"invalid JSON in {path}: {e}")


def validate_prereg(prereg: dict) -> None:
    stop = prereg.get("stage_a_stop_gates", {})
    for key in ("recoverable_c_errors_corpus_share_lt", "oracle_gain_lt_pp"):
        if key not in stop:
            fail(f"prereg missing stage_a_stop_gates.{key}")
    rules = prereg.get("stage_a_rules", {})
    if "max_local_mutations_per_case" not in rules:
        fail("prereg missing stage_a_rules.max_local_mutations_per_case")
    if not prereg.get("mutation_catalog_frozen_v1"):
        fail("prereg missing mutation_catalog_frozen_v1")


def catalog_fields(prereg: dict) -> set:
    return {entry["field"] for entry in prereg["mutation_catalog_frozen_v1"].values() if "field" in entry}


def validate_bundle(bundle: dict) -> list:
    cases = bundle.get("cases")
    if not isinstance(cases, list) or not cases:
        fail("bundle.cases must be a non-empty list")
    seen = set()
    for i, case in enumerate(cases):
        cid = case.get("case_id")
        if not cid:
            fail(f"case[{i}] missing case_id")
        if cid in seen:
            fail(f"duplicate case_id: {cid}")
        seen.add(cid)
    return cases


def field_diff(fields_a: dict, fields_b: dict, catalog: set) -> list:
    """Typed-field diff between two semantic-field dicts. Returns list of
    {field, old, new, catalog_covered} for every differing field."""
    diffs = []
    for key in sorted(set(fields_a) | set(fields_b)):
        old, new = fields_a.get(key, "<ABSENT>"), fields_b.get(key, "<ABSENT>")
        if old != new:
            diffs.append(
                {
                    "field": key,
                    "old": old,
                    "new": new,
                    "catalog_covered": key in catalog,
                }
            )
    return diffs


def classify_recoverability(case: dict, catalog: set, max_mutations: int) -> dict:
    """Deterministic recoverability label for a C-wrong case (vs GOLD, not vs B4)."""
    gold = case.get("gold") or {}
    c_pred = case.get("c") or {}
    if not gold:
        return {"label": "NOT_RECOVERABLE", "reason": "gold_absent"}
    gold_fields = gold.get("semantic_fields")
    c_fields = c_pred.get("semantic_fields")
    if not isinstance(gold_fields, dict) or not isinstance(c_fields, dict):
        return {"label": "UNCERTAIN", "reason": "field_level_representations_absent"}
    diffs = field_diff(c_fields, gold_fields, catalog)
    if not diffs:
        # C wrong behaviorally but fields equal to gold: behavioral-only mismatch,
        # not expressible as a field-level local patch from this data.
        return {"label": "UNCERTAIN", "reason": "fields_match_gold_but_case_marked_wrong"}
    covered = all(d["catalog_covered"] for d in diffs)
    if covered and len(diffs) <= max_mutations:
        return {"label": "LOCAL_PATCH_RECOVERABLE", "diffs": diffs}
    return {
        "label": "REQUIRES_GLOBAL_REPARSE",
        "diffs": diffs,
        "reason": "diff_outside_catalog_or_too_many" if not covered else "too_many_mutations",
    }


def attribute_b4_failure(case: dict) -> str:
    logs = (case.get("b4") or {}).get("stage_logs")
    if not isinstance(logs, dict) or not logs:
        return "UNATTRIBUTED_NO_LOGS"
    declared = logs.get("declared_error_stage")
    if declared in ATTRIBUTION_LABELS and declared != "UNATTRIBUTED_NO_LOGS":
        return declared
    for flag in STAGE_BOOLEAN_ORDER:
        if flag in logs and logs[flag] is False:
            return STAGE_BOOLEAN_TO_LABEL[flag]
    return "UNATTRIBUTED_NO_LOGS"


def run_stage_a(bundle: dict, prereg: dict) -> dict:
    cases = validate_bundle(bundle)
    catalog = catalog_fields(prereg)
    max_mut = int(prereg["stage_a_rules"]["max_local_mutations_per_case"])
    stop = prereg["stage_a_stop_gates"]

    quadrants = {"both_correct": [], "c_correct_b4_wrong": [], "c_wrong_b4_correct": [], "both_wrong": []}
    incomplete = []
    attribution = {}
    recoverability = {}
    family = {}

    for case in cases:
        cid = case["case_id"]
        fam = case.get("family", "unknown")
        frow = family.setdefault(fam, {"cases": 0, "c_ok": 0, "b4_ok": 0, "c_wrong_b4_ok": 0,
                                       "c_ok_b4_wrong": 0, "both_wrong": 0, "recoverable": 0})
        frow["cases"] += 1
        c_ok = (case.get("c") or {}).get("case_correct")
        b4_ok = (case.get("b4") or {}).get("case_correct")
        if not isinstance(c_ok, bool) or not isinstance(b4_ok, bool):
            incomplete.append({"case_id": cid, "reason": "missing_boolean_case_correct"})
            continue
        if c_ok:
            frow["c_ok"] += 1
        if b4_ok:
            frow["b4_ok"] += 1
        if c_ok and b4_ok:
            quadrants["both_correct"].append(cid)
        elif c_ok and not b4_ok:
            quadrants["c_correct_b4_wrong"].append(cid)
            frow["c_ok_b4_wrong"] += 1
            attribution[cid] = attribute_b4_failure(case)
        elif (not c_ok) and b4_ok:
            quadrants["c_wrong_b4_correct"].append(cid)
            frow["c_wrong_b4_ok"] += 1
            rec = classify_recoverability(case, catalog, max_mut)
            recoverability[cid] = rec
            if rec["label"] == "LOCAL_PATCH_RECOVERABLE":
                frow["recoverable"] += 1
        else:
            quadrants["both_wrong"].append(cid)
            frow["both_wrong"] += 1

    n = sum(len(v) for v in quadrants.values())
    c_correct = len(quadrants["both_correct"]) + len(quadrants["c_correct_b4_wrong"])
    recoverable = sum(1 for r in recoverability.values() if r["label"] == "LOCAL_PATCH_RECOVERABLE")
    c_acc = c_correct / n if n else 0.0
    share = recoverable / n if n else 0.0
    oracle_acc = (c_correct + recoverable) / n if n else 0.0
    oracle_gain = oracle_acc - c_acc

    gate_share = float(stop["recoverable_c_errors_corpus_share_lt"])
    gate_gain = float(stop["oracle_gain_lt_pp"])
    stop_conditions = {
        "recoverable_corpus_share_below_min": share < gate_share,
        "oracle_gain_below_min": oracle_gain < gate_gain,
    }
    stopped = any(stop_conditions.values())
    verdict = "REJECT_EARLY_STOP" if stopped else "PROCEED_TO_C_ALR_DESIGN"

    attribution_counts = {}
    for label in ATTRIBUTION_LABELS:
        cnt = sum(1 for v in attribution.values() if v == label)
        if cnt:
            attribution_counts[label] = cnt
    recoverability_counts = {}
    for label in RECOVERABILITY_LABELS:
        cnt = sum(1 for v in recoverability.values() if v["label"] == label)
        if cnt:
            recoverability_counts[label] = cnt

    return {
        "schema": "guardian-vnext-c-alr-stage-a-v1",
        "inputs": {
            "experiment": bundle.get("experiment"),
            "benchmark_name": bundle.get("benchmark_name"),
            "declared_case_count": bundle.get("case_count"),
            "analyzed_complete_cases": n,
            "incomplete_cases": incomplete,
        },
        "quadrants": {k: {"count": len(v), "case_ids": v} for k, v in quadrants.items()},
        "b4_failure_stage_attribution": {
            "counts": attribution_counts,
            "per_case": attribution,
        },
        "b4_gain_recoverability": {
            "counts": recoverability_counts,
            "per_case": recoverability,
        },
        "family_table": {fam: row for fam, row in sorted(family.items())},
        "oracle": {
            "n": n,
            "c_correct": c_correct,
            "c_accuracy": round(c_acc, 4),
            "local_patch_recoverable": recoverable,
            "recoverable_corpus_share": round(share, 4),
            "oracle_accuracy": round(oracle_acc, 4),
            "oracle_gain": round(oracle_gain, 4),
            "note": "Oracle(C + recoverable local corrections) is an upper-bound diagnostic only, never a system.",
        },
        "gates": {
            "preregistered": {
                "recoverable_c_errors_corpus_share_lt": gate_share,
                "oracle_gain_lt_pp": gate_gain,
            },
            "evaluated": stop_conditions,
            "decision": "STOP" if stopped else "PASS",
        },
        "verdict": verdict,
        "notes": [
            "Deterministic offline analysis only; sealed artifacts only; no LLM; no manual rescoring.",
            "Recoverability compares phi_C with GOLD field-level representations; it never consults B4 output.",
            "B4 failures without sealed stage logs are recorded as UNATTRIBUTED_NO_LOGS, never guessed.",
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser(description="C-ALR Stage A deterministic decomposition")
    parser.add_argument("--bundle", required=True, help="path to v6_sealed_bundle.json")
    parser.add_argument("--prereg", default=str(DEFAULT_PREREG), help="preregistered gates JSON")
    parser.add_argument("--out", help="optional path for the stage A report JSON")
    args = parser.parse_args()

    bundle_path = Path(args.bundle)
    prereg_path = Path(args.prereg)
    prereg = load_json(prereg_path)
    validate_prereg(prereg)
    bundle = load_json(bundle_path)

    report = run_stage_a(bundle, prereg)
    report["inputs"]["bundle_sha256"] = sha256_of(bundle_path)
    report["inputs"]["prereg_sha256"] = sha256_of(prereg_path)

    out = json.dumps(report, ensure_ascii=False, indent=1)
    if args.out:
        Path(args.out).write_text(out, encoding="utf-8")
    print(out)
    print(f"\nVERDICT: {report['verdict']}", file=sys.stderr)


if __name__ == "__main__":
    main()
