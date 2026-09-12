"""Execution-coverage audit for isolated and protected X5 paths."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from typing import Iterable

from guardian_truth.pipeline import Detector

from .external import ExternalDataset, guardian_documents
from .x5 import core_review, protected_review


def _ratio(a: int, b: int) -> float | None:
    return a / b if b else None


def _arm_metrics(rows: list[dict], arm: str) -> dict:
    tp = fp = fn = tn = 0
    for row in rows:
        gold, pred = row["gold"], row[arm]["label"]
        tp += gold == 1 and pred == 1
        fp += gold == 0 and pred == 1
        fn += gold == 1 and pred == 0
        tn += gold == 0 and pred == 0
    telemetry = [row[arm]["telemetry"] for row in rows]
    unresolved = sum(item["solver_status"] == "UNRESOLVED" for item in telemetry)
    inconsistent = sum(item["solver_status"] == "INCONSISTENT" for item in telemetry)
    return {
        "n": len(rows),
        "confusion": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "recall": _ratio(tp, tp + fn),
        "precision": _ratio(tp, tp + fp),
        "F1": _ratio(2 * tp, 2 * tp + fp + fn),
        "internal_coverage": _ratio(len(rows) - unresolved - inconsistent, len(rows)),
        "unresolved_rate": _ratio(unresolved, len(rows)),
        "inconsistent_rate": _ratio(inconsistent, len(rows)),
        "solver_status": dict(sorted(Counter(item["solver_status"] for item in telemetry).items())),
        "decision_source": dict(sorted(Counter(item["decision_source"] for item in telemetry).items())),
    }


def _equality_reason(x0: int, core: dict) -> str:
    if core["telemetry"]["used_binary_fallback"]:
        return (
            "CORE_UNRESOLVED_FALLBACK_MATCHES_X0" if core["label"] == x0
            else "CORE_UNRESOLVED_FALLBACK_DIFFERS_FROM_X0"
        )
    return "CORE_ACTIVE_AGREEMENT" if core["label"] == x0 else "CORE_ACTIVE_DISAGREEMENT"


def _evaluate(rows: Iterable[tuple[str, str, str, int]], contract_path: Path) -> dict:
    per_case = []
    for case_id, prompt, response, gold in rows:
        x0 = int(Detector().review(prompt, response).status == "violation")
        core = core_review(prompt, response, t1_contract_path=contract_path)
        protected = protected_review(prompt, response, t1_contract_path=contract_path)
        per_case.append({
            "case_id": case_id,
            "gold": gold,
            "X0": x0,
            "X5_CORE": core,
            "X5_PROTECTED": protected,
            "core_vs_x0": _equality_reason(x0, core),
        })
    x0_tp = sum(row["gold"] == 1 and row["X0"] == 1 for row in per_case)
    x0_fp = sum(row["gold"] == 0 and row["X0"] == 1 for row in per_case)
    protected_tp = sum(row["gold"] == 1 and row["X5_PROTECTED"]["label"] == 1 for row in per_case)
    protected_fp = sum(row["gold"] == 0 and row["X5_PROTECTED"]["label"] == 1 for row in per_case)
    return {
        "arms": {
            "X5_CORE": _arm_metrics(per_case, "X5_CORE"),
            "X5_PROTECTED": _arm_metrics(per_case, "X5_PROTECTED"),
        },
        "protected_contribution_over_x0": {
            "changed_predictions": sum(
                row["X0"] != row["X5_PROTECTED"]["label"] for row in per_case
            ),
            "added_true_positives": protected_tp - x0_tp,
            "added_false_positives": protected_fp - x0_fp,
        },
        "core_vs_x0_reasons": dict(sorted(Counter(
            row["core_vs_x0"] for row in per_case
        ).items())),
        "per_case": per_case,
    }


def build_x5_execution_report(internal_rows: Iterable[dict], external: ExternalDataset,
                              contract_path: Path, *, internal_sha256: str,
                              frozen_x5_commit: str) -> dict:
    internal = _evaluate((
        (str(row["id"]), str(row["prompt"]), str(row["response"]), int(row["label"]))
        for row in internal_rows
    ), contract_path)
    external_result = _evaluate((
        (case.case_id, *guardian_documents(case), int(case.gold["verdict"] == "ERROR"))
        for case in external.cases
    ), contract_path)
    return {
        "schema_version": "guardian-cycle2-x5-execution-v1",
        "frozen_x5_commit": frozen_x5_commit,
        "isolation": {
            "X5_CORE_uses_X0_findings": False,
            "X5_PROTECTED_formula": "X0 OR safe X5_CORE",
            "unknown_is_exposed_before_binary_fallback": True,
        },
        "inputs": {
            "internal_sha256": internal_sha256,
            "external_manifest_sha256": external.digest,
            "external_cases_sha256": external.cases_digest,
            "t1_registry_sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
        },
        "internal": internal,
        "external": external_result,
    }
