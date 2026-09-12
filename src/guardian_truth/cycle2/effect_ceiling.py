"""Evaluate the trusted T1 tool-effect ceiling on the exact same X5 core."""

from __future__ import annotations

from collections import Counter
import hashlib
from pathlib import Path
from typing import Iterable

from guardian_truth.next.effects import load_human_contracts, schema_registry
from guardian_truth.next.normalize import normalize_trace
from guardian_truth.pipeline import Detector

from .external import ExternalDataset, guardian_documents
from .x5 import core_review


def _ratio(numerator: int, denominator: int) -> float | None:
    return numerator / denominator if denominator else None


def _metrics(rows: list[dict], arm: str) -> dict:
    tp = fp = fn = tn = resolved = resolved_positive = resolved_tp = 0
    verdicts: Counter[str] = Counter()
    for row in rows:
        result = row[arm]
        gold, prediction = row["gold"], result["label"]
        tp += gold == 1 and prediction == 1
        fp += gold == 0 and prediction == 1
        fn += gold == 1 and prediction == 0
        tn += gold == 0 and prediction == 0
        verdicts[result["internal_verdict"]] += 1
        is_resolved = not result["telemetry"]["used_binary_fallback"]
        resolved += is_resolved
        resolved_positive += is_resolved and gold == 1
        resolved_tp += is_resolved and gold == 1 and prediction == 1
    return {
        "n": len(rows),
        "confusion": {"TP": tp, "FP": fp, "FN": fn, "TN": tn},
        "recall": _ratio(tp, tp + fn),
        "precision": _ratio(tp, tp + fp),
        "internal_coverage": _ratio(resolved, len(rows)),
        "conditional_recall_on_internally_resolved_positives": _ratio(
            resolved_tp, resolved_positive
        ),
        "resolved_positive_denominator": resolved_positive,
        "internal_verdicts": dict(sorted(verdicts.items())),
        "mean_evidence_records": _ratio(
            sum(row[arm]["telemetry"]["n_evidence_events"] for row in rows), len(rows)
        ),
    }


def _called_tools(prompt: str, response: str) -> set[str]:
    return {
        event.name for event in normalize_trace(prompt, response)
        if event.kind in {"call", "result"} and event.name
    }


def _coverage(cases: Iterable[dict], trusted_tools: set[str]) -> dict:
    cases = list(cases)
    all_called = set().union(*(row["called_tools"] for row in cases)) if cases else set()
    positive_called = set().union(*(
        row["called_tools"] for row in cases if row["gold"] == 1
    )) if any(row["gold"] == 1 for row in cases) else set()
    x0_fn_called = set().union(*(
        row["called_tools"] for row in cases if row["gold"] == 1 and row["x0"] == 0
    )) if any(row["gold"] == 1 and row["x0"] == 0 for row in cases) else set()

    def describe(names: set[str]) -> dict:
        covered = names & trusted_tools
        return {
            "tools": sorted(names),
            "covered_tools": sorted(covered),
            "missing_tools": sorted(names - trusted_tools),
            "coverage": _ratio(len(covered), len(names)),
        }

    return {
        "all_called": describe(all_called),
        "positive_called": describe(positive_called),
        "x0_false_negative_called": describe(x0_fn_called),
    }


def _evaluate_rows(rows: Iterable[tuple[str, str, str, int]], contract_path: Path) -> dict:
    per_case = []
    for case_id, prompt, response, gold in rows:
        x0 = int(Detector().review(prompt, response).status == "violation")
        t0 = core_review(prompt, response)
        t1 = core_review(prompt, response, t1_contract_path=contract_path)
        per_case.append({
            "case_id": case_id,
            "gold": gold,
            "x0": x0,
            "called_tools": sorted(_called_tools(prompt, response)),
            "catalog_tools": sorted(schema_registry(prompt)),
            "X5_T0": t0,
            "X5_T1": t1,
            "changed_binary": t0["label"] != t1["label"],
            "changed_internal_verdict": t0["internal_verdict"] != t1["internal_verdict"],
            "added_evidence_records": (
                t1["telemetry"]["n_evidence_events"]
                - t0["telemetry"]["n_evidence_events"]
            ),
        })
    trusted = set(load_human_contracts(contract_path))
    t0_metrics, t1_metrics = _metrics(per_case, "X5_T0"), _metrics(per_case, "X5_T1")
    t0_recall = t0_metrics["conditional_recall_on_internally_resolved_positives"]
    t1_recall = t1_metrics["conditional_recall_on_internally_resolved_positives"]
    return {
        "arms": {"X5_T0": t0_metrics, "X5_T1": t1_metrics},
        "delta": {
            "binary_changes": sum(row["changed_binary"] for row in per_case),
            "internal_verdict_changes": sum(row["changed_internal_verdict"] for row in per_case),
            "additional_evidence_records": sum(row["added_evidence_records"] for row in per_case),
            "conditional_recall": (
                t1_recall - t0_recall
                if t0_recall is not None and t1_recall is not None else None
            ),
        },
        "registry_coverage": _coverage(per_case, trusted),
        "per_case": per_case,
    }


def build_effect_ceiling_report(internal_rows: Iterable[dict], external: ExternalDataset,
                                contract_path: Path, *, internal_sha256: str) -> dict:
    """Run T0/T1 without changing any other X5 component or binary mapping."""
    internal_input = (
        (str(row["id"]), str(row["prompt"]), str(row["response"]), int(row["label"]))
        for row in internal_rows
    )
    external_input = (
        (case.case_id, *guardian_documents(case), int(case.gold["verdict"] == "ERROR"))
        for case in external.cases
    )
    internal_result = _evaluate_rows(internal_input, contract_path)
    external_result = _evaluate_rows(external_input, contract_path)
    required_sections = [
        internal_result["registry_coverage"]["positive_called"],
        internal_result["registry_coverage"]["x0_false_negative_called"],
        external_result["registry_coverage"]["positive_called"],
        external_result["registry_coverage"]["x0_false_negative_called"],
    ]
    sufficient = all(not section["missing_tools"] for section in required_sections)
    return {
        "schema_version": "guardian-cycle2-tool-effect-ceiling-v1",
        "comparison": "same frozen X5_CORE with T0 versus trusted T1 overrides",
        "t1_registry": {
            "path": contract_path.as_posix(),
            "sha256": hashlib.sha256(contract_path.read_bytes()).hexdigest(),
            "contracts": len(load_human_contracts(contract_path)),
            "sufficient_for_required_scopes": sufficient,
            "sufficiency_rule": (
                "every actually called tool in internal/external positives and X0 false negatives "
                "must have a trusted contract"
            ),
        },
        "inputs": {
            "internal_sha256": internal_sha256,
            "external_manifest_sha256": external.digest,
            "external_cases_sha256": external.cases_digest,
        },
        "internal": internal_result,
        "external": external_result,
        "conclusion": (
            "MEASURED_SUFFICIENT_T1_CEILING" if sufficient
            else "T1_CEILING_NOT_ESTABLISHED_REGISTRY_INSUFFICIENT"
        ),
        "t2_t3_admission": (
            "ELIGIBLE_ONLY_IF_CONDITIONAL_RECALL_GAIN" if sufficient
            else "BLOCKED_UNTIL_SUFFICIENT_TRUSTED_T1"
        ),
    }
