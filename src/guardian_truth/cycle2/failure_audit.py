"""Post-freeze failure taxonomy for Cycle 2 end-to-end predictions."""

from __future__ import annotations

from collections import Counter
from typing import Any, Mapping

from .external import ExternalDataset


def _failure_type(gold: int, prediction: int) -> str | None:
    if gold == prediction:
        return None
    return "FALSE_POSITIVE" if prediction else "FALSE_NEGATIVE"


def _x5_components(row: Mapping[str, Any]) -> list[str]:
    telemetry = row.get("telemetry", {})
    components = []
    if telemetry.get("n_policy_rules", 0) == 0 or telemetry.get("n_unknown_policy_segments", 0):
        components.append("POLICY_SEMANTICS")
    if telemetry.get("n_claims", 0) == 0 or telemetry.get("n_unknown_claim_spans", 0):
        components.append("CLAIM_EXTRACTION")
    if telemetry.get("n_unknown_tools", 0):
        components.append("TOOL_EFFECTS")
    if telemetry.get("n_claims", 0) and telemetry.get("n_candidate_bindings", 0) == 0:
        components.append("BINDING")
    if telemetry.get("solver_status") in {"UNRESOLVED", "INCONSISTENT"} and not components:
        components.append("SOLVER")
    return components or ["DECISION"]


def build_failure_taxonomy(dataset: ExternalDataset,
                           prediction_artifact: Mapping[str, Any]) -> dict:
    if (prediction_artifact.get("schema_version") != "guardian-cycle2-external-predictions-v1"
            or prediction_artifact.get("cases_sha256") != dataset.cases_digest
            or prediction_artifact.get("predictions_frozen_before_gold_join") is not True
            or prediction_artifact.get("gold_visible_to_prediction_stage") is not False):
        raise ValueError("failure audit requires matching frozen blind predictions")
    by_case = {case.case_id: case for case in dataset.cases}
    rows = prediction_artifact.get("predictions", [])
    arms = ("X0", "X1", "X4", "X5_CORE", "X5_PROTECTED", "G1")
    expected = {(case.case_id, arm) for case in dataset.cases for arm in arms}
    if len(rows) != len(expected) or {(row.get("case_id"), row.get("arm")) for row in rows} != expected:
        raise ValueError("incomplete prediction artifact")

    output = {}
    for arm in arms:
        failures = []
        for row in rows:
            if row["arm"] != arm:
                continue
            case = by_case[row["case_id"]]
            gold = int(case.gold["verdict"] == "ERROR")
            binary = row.get("label") if row.get("label") in {0, 1} else 0
            kind = _failure_type(gold, binary)
            if row.get("transport_status") == "ERROR":
                operational = "TRANSPORT_FAILURE"
            elif row.get("schema_status") not in {"VALID"}:
                operational = "SCHEMA_FAILURE"
            else:
                operational = None
            if kind is None and operational is None:
                continue
            failures.append({
                "case_id": case.case_id,
                "failure_type": kind,
                "operational_failure": operational,
                "gold": gold,
                "binary_prediction": binary,
                "internal_status": row.get("internal_status"),
                "used_fallback": bool(row.get("used_fallback")),
                "domain": case.domain,
                "policy_family": case.policy_family,
                "error_family": case.error_family,
                "tool_family": case.tool_family,
                "candidate_components": _x5_components(row) if arm.startswith("X5") else [],
            })
        component_counts = Counter(
            component for failure in failures for component in failure["candidate_components"]
        )
        output[arm] = {
            "failures": len(failures),
            "false_positives": sum(row["failure_type"] == "FALSE_POSITIVE" for row in failures),
            "false_negatives": sum(row["failure_type"] == "FALSE_NEGATIVE" for row in failures),
            "transport_failures": sum(row["operational_failure"] == "TRANSPORT_FAILURE" for row in failures),
            "schema_failures": sum(row["operational_failure"] == "SCHEMA_FAILURE" for row in failures),
            "component_counts_nonexclusive": dict(sorted(component_counts.items())),
            "by_error_family": dict(sorted(Counter(row["error_family"] for row in failures).items())),
            "cases": failures,
        }
    return {
        "schema_version": "guardian-cycle2-failure-taxonomy-v1",
        "cases_sha256": dataset.cases_digest,
        "predictions_sha256": prediction_artifact["predictions_sha256"],
        "gold_joined_only_after_prediction_freeze": True,
        "component_attribution_is_nonexclusive_diagnostic": True,
        "arms": output,
    }
