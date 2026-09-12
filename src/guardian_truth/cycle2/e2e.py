"""Frozen end-to-end arms, exact G1 composition, and paired statistics."""

from __future__ import annotations

from dataclasses import dataclass
import hashlib
import json
import math
from pathlib import Path
import random
import statistics
import time
from typing import Any, Callable, Iterable, Mapping, Protocol

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.pipeline import Detector
from guardian_truth.next.vigil import review as vigil_review

from .external import ExternalDataset, blind_external_case, guardian_documents_blind
from .x5 import core_review, protected_review


class CompletionClient(Protocol):
    def complete(self, messages: list[dict], *, schema: dict | None = None,
                 reasoning_effort: str | None = None) -> Completion: ...


@dataclass(frozen=True)
class E2EContract:
    digest: str
    timeout_seconds: float
    max_output_tokens: int
    interval_seconds: float
    reasoning_effort: str
    response_format_mode: str
    x1_system: str
    bootstrap_resamples: int
    bootstrap_seed: int
    promotion_constraints: dict


def load_e2e_contract(path: Path) -> E2EContract:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8"))
    expected_arms = {
        "X0": "CURRENT_V5_3", "X1": "HOLISTIC_STRONG", "X4": "VIGIL_LIKE",
        "X5_CORE": "POLICY_OBLIGATIONS_EFFECTS_LEDGER_CLAIMS_BINDER_SOLVER_WITHOUT_X0",
        "X5_PROTECTED": "X0_OR_SAFE_X5_CORE", "G1": "X0 OR (X4 AND X1)",
    }
    request = value.get("X1_request", {}) if isinstance(value, dict) else {}
    if (not isinstance(value, dict)
            or value.get("schema_version") != "guardian-cycle2-e2e-arms-v1"
            or value.get("frozen_before_external_predictions") is not True
            or value.get("arms") != expected_arms
            or value.get("G1_formula_locked") is not True
            or value.get("binary_mapping") != {
                "ERROR": 1, "NO_ERROR": 0, "UNRESOLVED": 0, "INCONSISTENT": 0,
            } or request.get("temperature") != 0 or request.get("max_retries") != 0
            or request.get("response_format_mode") != "none"):
        raise ValueError("invalid frozen e2e contract")
    stats = value["statistics"]
    return E2EContract(
        hashlib.sha256(raw).hexdigest(), float(request["timeout_seconds"]),
        int(request["max_output_tokens"]), float(request["interval_seconds"]),
        request["reasoning_effort"], request["response_format_mode"], value["X1_system"],
        int(stats["bootstrap_resamples"]), int(stats["bootstrap_seed"]),
        dict(value["promotion_constraints"]),
    )


def x1_schema(case_id: str) -> dict:
    return {
        "type": "object",
        "properties": {
            "case_id": {"type": "string", "const": case_id},
            "verdict": {"type": "string", "enum": ["ERROR", "NO_ERROR"]},
            "responsible_quotes": {"type": "array", "items": {"type": "string"},
                                   "maxItems": 6, "uniqueItems": True},
            "reason": {"type": "string", "minLength": 1},
        },
        "required": ["case_id", "verdict", "responsible_quotes", "reason"],
        "additionalProperties": False,
    }


def x1_messages(case: Mapping[str, Any], contract: E2EContract) -> tuple[list[dict], dict, str]:
    required = {"case_id", "policy_or_normative_context", "history_prefix",
                "tool_schemas", "target_assistant_turn"}
    if set(case) != required:
        raise ValueError("X1 input is not blind")
    rendered = json.dumps(case, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    schema = x1_schema(case["case_id"])
    prompt = ("INPUT_JSON:\n" + rendered + "\nOUTPUT_JSON_SCHEMA:\n"
              + json.dumps(schema, ensure_ascii=False, separators=(",", ":")))
    return ([{"role": "system", "content": contract.x1_system},
             {"role": "user", "content": prompt}], schema, rendered)


def _strict_object(text: str) -> dict:
    def unique(pairs):
        result = {}
        for key, value in pairs:
            if key in result:
                raise ValueError("duplicate key")
            result[key] = value
        return result
    value = json.loads(text, object_pairs_hook=unique,
                       parse_constant=lambda _: (_ for _ in ()).throw(ValueError("non-finite")))
    if not isinstance(value, dict):
        raise ValueError("not object")
    return value


def _safe_usage(value: Mapping[str, Any]) -> dict[str, int]:
    return {key: item for key in ("prompt_tokens", "completion_tokens", "total_tokens")
            if type((item := value.get(key))) is int and item >= 0}


def x1_proposal(client: CompletionClient, case: Mapping[str, Any], contract: E2EContract,
                *, clock: Callable[[], float] = time.monotonic) -> dict:
    messages, schema, rendered = x1_messages(case, contract)
    started = clock()
    row = {
        "case_id": case["case_id"], "arm": "X1", "transport_status": "ERROR",
        "schema_status": "NOT_EVALUATED", "label": None, "internal_status": "UNRESOLVED",
        "responsible_spans": [], "reason": None, "error_category": None,
        "served_model": None, "latency_ms": 0.0, "usage": {}, "used_fallback": True,
    }
    try:
        completion = client.complete(messages, schema=schema, reasoning_effort=contract.reasoning_effort)
    except ChatClientError as error:
        row.update({"error_category": error.category,
                    "latency_ms": round(max(0.0, clock() - started) * 1000, 3)})
        return row
    row.update({"transport_status": "SUCCESS", "schema_status": "INVALID",
                "served_model": completion.model,
                "latency_ms": round(max(0.0, clock() - started) * 1000, 3),
                "usage": _safe_usage(completion.usage)})
    try:
        value = _strict_object(completion.content)
        if (set(value) != {"case_id", "verdict", "responsible_quotes", "reason"}
                or value["case_id"] != case["case_id"]
                or value["verdict"] not in {"ERROR", "NO_ERROR"}
                or not isinstance(value["reason"], str) or not value["reason"].strip()
                or not isinstance(value["responsible_quotes"], list)
                or len(value["responsible_quotes"]) > 6
                or len(value["responsible_quotes"]) != len(set(value["responsible_quotes"]))
                or any(not isinstance(quote, str) or not quote or quote not in rendered
                       for quote in value["responsible_quotes"])):
            raise ValueError("invalid X1 response")
        spans = []
        cursor_by_quote = {}
        for quote in value["responsible_quotes"]:
            start = rendered.find(quote, cursor_by_quote.get(quote, 0))
            cursor_by_quote[quote] = start + len(quote)
            spans.append({"document": "input_json", "start": start,
                          "end": start + len(quote), "quote": quote})
        label = int(value["verdict"] == "ERROR")
        row.update({"schema_status": "VALID", "label": label,
                    "internal_status": "PROVED_ERROR" if label else "PROVED_NO_ERROR",
                    "responsible_spans": spans, "reason": value["reason"],
                    "used_fallback": False})
    except (ValueError, TypeError, UnicodeError, RecursionError):
        pass
    return row


def run_x1(client: CompletionClient, cases: Iterable[Mapping[str, Any]], contract: E2EContract,
           *, existing: Iterable[dict] = (), checkpoint: Callable[[list[dict]], None] | None = None,
           clock: Callable[[], float] = time.monotonic,
           sleep: Callable[[float], None] = time.sleep) -> list[dict]:
    rows = list(existing)
    completed = {row.get("case_id") for row in rows}
    last_start = None
    for case in cases:
        if case["case_id"] in completed:
            continue
        now = clock()
        if last_start is not None:
            remaining = contract.interval_seconds - (now - last_start)
            if remaining > 0:
                sleep(remaining)
        last_start = clock()
        rows.append(x1_proposal(client, case, contract, clock=clock))
        completed.add(case["case_id"])
        if checkpoint:
            checkpoint(rows)
    return rows


def offline_proposals(dataset: ExternalDataset, *, t1_contract_path: Path | None = None) -> list[dict]:
    rows = []
    for case in dataset.cases:
        blind = blind_external_case(case)
        prompt, response = guardian_documents_blind(blind)
        incumbent = Detector().review(prompt, response)
        x0 = int(incumbent.status == "violation")
        rows.append({
            "case_id": case.case_id, "arm": "X0", "transport_status": "NOT_APPLICABLE",
            "schema_status": "VALID", "label": x0,
            "internal_status": "PROVED_ERROR" if x0 else "PROVED_NO_ERROR",
            "used_fallback": False, "latency_ms": 0.0, "usage": {},
            "telemetry": {"binary_result": x0, "decision_source": "X0"},
        })
        vigil = vigil_review(prompt, response)
        rows.append({
            "case_id": case.case_id, "arm": "X4", "transport_status": "NOT_APPLICABLE",
            "schema_status": "VALID", "label": vigil.label,
            "internal_status": "PROVED_ERROR" if vigil.label else "PROVED_NO_ERROR",
            "used_fallback": vigil.used_fallback, "latency_ms": 0.0, "usage": {},
            "telemetry": {"binary_result": vigil.label, "decision_source": "X4",
                          "observed_vocabulary": len(vigil.observed_vocabulary),
                          "selected_policy_segments": len(vigil.selected_segment_ids)},
        })
        core = core_review(prompt, response, t1_contract_path=t1_contract_path)
        rows.append({
            "case_id": case.case_id, "arm": "X5_CORE", "transport_status": "NOT_APPLICABLE",
            "schema_status": "VALID", "label": core["label"],
            "internal_status": core["internal_verdict"],
            "used_fallback": core["telemetry"]["used_binary_fallback"],
            "latency_ms": 0.0, "usage": {}, "telemetry": core["telemetry"],
        })
        protected = protected_review(prompt, response, t1_contract_path=t1_contract_path)
        rows.append({
            "case_id": case.case_id, "arm": "X5_PROTECTED", "transport_status": "NOT_APPLICABLE",
            "schema_status": "VALID", "label": protected["label"],
            "internal_status": protected["internal_verdict"],
            "used_fallback": protected["telemetry"]["used_binary_fallback"],
            "latency_ms": 0.0, "usage": {}, "telemetry": protected["telemetry"],
        })
    return rows


def compose_g1(offline: Iterable[dict], x1: Iterable[dict]) -> list[dict]:
    by = {(row["case_id"], row["arm"]): row for row in [*offline, *x1]}
    ids = sorted({case_id for case_id, _ in by})
    rows = []
    for case_id in ids:
        x0, x4, model = by[(case_id, "X0")], by[(case_id, "X4")], by[(case_id, "X1")]
        if x0["label"] == 1:
            label, status, fallback = 1, "PROVED_ERROR", False
            source = "BOTH" if x4["label"] == 1 and model.get("label") == 1 else "X0"
        elif x4["label"] == 0:
            label, status, fallback = 0, "PROVED_NO_ERROR", False
            source = "DEFAULT"
        elif model["schema_status"] == "VALID":
            label = int(model["label"] == 1)
            status = "PROVED_ERROR" if label else "PROVED_NO_ERROR"
            fallback = False
            source = "BOTH" if label else "DEFAULT"
        else:
            label, status, fallback = None, "UNRESOLVED", True
            source = "FALLBACK"
        rows.append({
            "case_id": case_id, "arm": "G1", "transport_status": model["transport_status"],
            "schema_status": "VALID" if label is not None else "NOT_EVALUATED",
            "label": label, "internal_status": status, "used_fallback": fallback,
            "latency_ms": model["latency_ms"], "usage": model["usage"],
            "telemetry": {"formula": "X0 OR (X4 AND X1)", "x0": x0["label"],
                          "x4": x4["label"], "x1": model["label"],
                          "binary_result": 0 if label is None else label,
                          "decision_source": source},
        })
    return rows


def freeze_external_predictions(dataset: ExternalDataset, offline: Iterable[dict],
                                x1: Iterable[dict], contract: E2EContract) -> dict:
    proposals = [*offline, *x1]
    proposals.extend(compose_g1(proposals, ()))
    expected = {(case.case_id, arm) for case in dataset.cases
                for arm in ("X0", "X1", "X4", "X5_CORE", "X5_PROTECTED", "G1")}
    actual = {(row.get("case_id"), row.get("arm")) for row in proposals}
    if actual != expected or len(proposals) != len(expected):
        raise ValueError("external predictions incomplete")
    canonical = json.dumps(proposals, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return {
        "schema_version": "guardian-cycle2-external-predictions-v1",
        "cases_sha256": dataset.cases_digest,
        "e2e_contract_sha256": contract.digest,
        "gold_visible_to_prediction_stage": False,
        "predictions_frozen_before_gold_join": True,
        "predictions_sha256": hashlib.sha256(canonical.encode("utf-8")).hexdigest(),
        "predictions": proposals,
    }


def _confusion(labels: list[int], predictions: list[int]) -> dict:
    tp = sum(gold == 1 and pred == 1 for gold, pred in zip(labels, predictions))
    fp = sum(gold == 0 and pred == 1 for gold, pred in zip(labels, predictions))
    fn = sum(gold == 1 and pred == 0 for gold, pred in zip(labels, predictions))
    tn = sum(gold == 0 and pred == 0 for gold, pred in zip(labels, predictions))
    precision = tp / (tp + fp) if tp + fp else None
    recall = tp / (tp + fn) if tp + fn else None
    specificity = tn / (tn + fp) if tn + fp else None
    f1 = 2 * tp / (2 * tp + fp + fn) if 2 * tp + fp + fn else None
    balanced = (recall + specificity) / 2 if recall is not None and specificity is not None else None
    return {"TP": tp, "FP": fp, "FN": fn, "TN": tn, "precision": precision,
            "recall": recall, "F1": f1, "specificity": specificity,
            "balanced_accuracy": balanced, "FPR": 1 - specificity if specificity is not None else None}


def _percentile(values: Iterable[float], p: float) -> float | None:
    values = sorted(values)
    return values[max(0, math.ceil(p * len(values)) - 1)] if values else None


def arm_metrics(dataset: ExternalDataset, rows: Iterable[dict], arm: str) -> dict:
    by_gold = {case.case_id: int(case.gold["verdict"] == "ERROR") for case in dataset.cases}
    selected = [row for row in rows if row["arm"] == arm]
    if len(selected) != len(dataset.cases):
        raise ValueError("incomplete e2e arm")
    valid = [row for row in selected if row.get("label") in {0, 1}
             and row.get("schema_status") == "VALID"]
    conditional = _confusion([by_gold[row["case_id"]] for row in valid], [row["label"] for row in valid])
    fallback_predictions = [row["label"] if row.get("label") in {0, 1} else 0 for row in selected]
    strict = _confusion([by_gold[row["case_id"]] for row in selected], fallback_predictions)
    statuses = {name: sum(row.get("internal_status") == name for row in selected)
                for name in ("PROVED_ERROR", "PROVED_NO_ERROR", "UNRESOLVED", "INCONSISTENT")}
    resolved = statuses["PROVED_ERROR"] + statuses["PROVED_NO_ERROR"]
    latencies = [float(row.get("latency_ms", 0.0)) for row in selected]
    usage = {key: sum(row.get("usage", {}).get(key, 0) for row in selected)
             for key in ("prompt_tokens", "completion_tokens", "total_tokens")}
    return {
        "attempted": len(selected),
        "transport_success": sum(row.get("transport_status") in {"SUCCESS", "NOT_APPLICABLE"} for row in selected),
        "schema_valid": len(valid),
        "reliability": len(valid) / len(selected),
        "coverage": resolved / len(selected),
        "abstention_rate": 1 - resolved / len(selected),
        "internal_status_counts": statuses,
        "unresolved_rate": statuses["UNRESOLVED"] / len(selected),
        "inconsistent_rate": statuses["INCONSISTENT"] / len(selected),
        "conditional_valid": conditional,
        "strict_binary_with_declared_fallback": strict,
        "confident_wrong": sum(
            row.get("label") in {0, 1} and not row.get("used_fallback")
            and row["label"] != by_gold[row["case_id"]] for row in selected
        ),
        "latency_p50_ms": _percentile(latencies, 0.5),
        "latency_p95_ms": _percentile(latencies, 0.95),
        "api_calls": sum(row.get("transport_status") != "NOT_APPLICABLE" for row in selected),
        "tokens": usage,
        "cost": None,
        "cost_status": "NOT_ESTABLISHED_PROVIDER_BILLING_NOT_AUDITED",
    }


def _metric(labels: list[int], predictions: list[int], name: str) -> float:
    value = _confusion(labels, predictions)[name]
    return 0.0 if value is None else value


def _exact_mcnemar(labels: list[int], left: list[int], right: list[int]) -> dict:
    left_only = sum(a == gold and b != gold for gold, a, b in zip(labels, left, right))
    right_only = sum(b == gold and a != gold for gold, a, b in zip(labels, left, right))
    n = left_only + right_only
    if not n:
        p = 1.0
    else:
        tail = sum(math.comb(n, k) for k in range(min(left_only, right_only) + 1)) / (2 ** n)
        p = min(1.0, 2 * tail)
    return {"left_only_correct": left_only, "right_only_correct": right_only,
            "discordant": n, "exact_two_sided_p": p}


def paired_comparison(dataset: ExternalDataset, rows: Iterable[dict], left_arm: str,
                      right_arm: str, contract: E2EContract) -> dict:
    by = {(row["case_id"], row["arm"]): row for row in rows}
    usable = [case for case in dataset.cases
              if by[(case.case_id, left_arm)].get("label") in {0, 1}
              and by[(case.case_id, right_arm)].get("label") in {0, 1}
              and by[(case.case_id, left_arm)].get("schema_status") == "VALID"
              and by[(case.case_id, right_arm)].get("schema_status") == "VALID"]
    labels = [int(case.gold["verdict"] == "ERROR") for case in usable]
    left = [by[(case.case_id, left_arm)]["label"] for case in usable]
    right = [by[(case.case_id, right_arm)]["label"] for case in usable]
    randomizer = random.Random(contract.bootstrap_seed)
    deltas = {name: [] for name in ("F1", "recall", "precision")}
    if usable:
        for _ in range(contract.bootstrap_resamples):
            indices = [randomizer.randrange(len(usable)) for _ in usable]
            sample_gold = [labels[i] for i in indices]
            sample_left = [left[i] for i in indices]
            sample_right = [right[i] for i in indices]
            for name in deltas:
                deltas[name].append(_metric(sample_gold, sample_right, name)
                                    - _metric(sample_gold, sample_left, name))
    cis = {}
    for name, values in deltas.items():
        values.sort()
        cis["delta_" + name + "_95ci"] = (
            [values[int(.025 * (len(values) - 1))], values[int(.975 * (len(values) - 1))]]
            if values else None
        )
    return {
        "left": left_arm, "right": right_arm, "n_paired": len(usable),
        "left_metrics": _confusion(labels, left), "right_metrics": _confusion(labels, right),
        "mcnemar": _exact_mcnemar(labels, left, right), **cis,
        "hierarchical_bootstrap_cluster": "trajectory_id",
        "cluster_note": "one target case per selected trajectory; cluster and case bootstrap coincide",
    }


def _breakdowns(dataset: ExternalDataset, rows: list[dict], arm: str) -> dict:
    by = {(row["case_id"], row["arm"]): row for row in rows}
    dimensions = {
        "source": lambda case: case.source,
        "domain": lambda case: case.domain,
        "policy_family": lambda case: case.policy_family,
        "error_family": lambda case: case.error_family,
        "tool_family": lambda case: case.tool_family,
        "provenance": lambda case: case.provenance["human_review_status"],
    }
    output = {}
    for name, key_fn in dimensions.items():
        grouped = {}
        for case in dataset.cases:
            row = by[(case.case_id, arm)]
            if row.get("label") not in {0, 1} or row.get("schema_status") != "VALID":
                continue
            key = key_fn(case)
            grouped.setdefault(key, [[], []])
            grouped[key][0].append(int(case.gold["verdict"] == "ERROR"))
            grouped[key][1].append(row["label"])
        output[name] = {key: _confusion(*values) for key, values in sorted(grouped.items())}
    return output


def build_e2e_report(dataset: ExternalDataset, prediction_artifact: Mapping[str, Any],
                     contract: E2EContract) -> tuple[dict, dict]:
    if (prediction_artifact.get("cases_sha256") != dataset.cases_digest
            or prediction_artifact.get("e2e_contract_sha256") != contract.digest
            or prediction_artifact.get("gold_visible_to_prediction_stage") is not False):
        raise ValueError("prediction artifact does not match frozen e2e inputs")
    rows = prediction_artifact["predictions"]
    arms = ("X0", "X1", "X4", "X5_CORE", "X5_PROTECTED", "G1")
    metrics = {arm: arm_metrics(dataset, rows, arm) for arm in arms}
    comparisons = {arm: paired_comparison(dataset, rows, "X0", arm, contract)
                   for arm in ("X1", "X4", "X5_CORE", "X5_PROTECTED", "G1")}
    by = {(row["case_id"], row["arm"]): row for row in rows}
    intersection_rows = []
    marginal = []
    for case in dataset.cases:
        x0, x1, x4 = (by[(case.case_id, arm)] for arm in ("X0", "X1", "X4"))
        intersection = int(x4["label"] == 1 and x1.get("label") == 1) if x1.get("label") in {0, 1} else None
        if intersection is not None:
            intersection_rows.append((int(case.gold["verdict"] == "ERROR"), intersection))
        if x0["label"] == 0 and x4["label"] == 1 and x1.get("label") == 1:
            marginal.append({"case_id": case.case_id, "X0": 0, "X1": 1, "X4": 1,
                             "gold": int(case.gold["verdict"] == "ERROR")})
    intersection_metrics = _confusion(
        [gold for gold, _ in intersection_rows], [pred for _, pred in intersection_rows],
    )
    g1_strict, x0_strict = metrics["G1"]["strict_binary_with_declared_fallback"], metrics["X0"]["strict_binary_with_declared_fallback"]
    report = {
        "schema_version": "guardian-cycle2-e2e-results-v1",
        "status": "COMPLETED",
        "cases_sha256": dataset.cases_digest,
        "predictions_sha256": prediction_artifact["predictions_sha256"],
        "e2e_contract_sha256": contract.digest,
        "arms": metrics,
        "breakdowns": {arm: _breakdowns(dataset, rows, arm) for arm in arms},
        "paired_vs_X0": comparisons,
        "G1_marginal": {
            "X0_TP": x0_strict["TP"], "X0_FP": x0_strict["FP"],
            "X1_TP": metrics["X1"]["strict_binary_with_declared_fallback"]["TP"],
            "X1_FP": metrics["X1"]["strict_binary_with_declared_fallback"]["FP"],
            "X4_TP": metrics["X4"]["strict_binary_with_declared_fallback"]["TP"],
            "X4_FP": metrics["X4"]["strict_binary_with_declared_fallback"]["FP"],
            "X4_intersection_X1": intersection_metrics,
            "G1_TP": g1_strict["TP"], "G1_FP": g1_strict["FP"],
            "TP_added_over_X0": g1_strict["TP"] - x0_strict["TP"],
            "FP_added_over_X0": g1_strict["FP"] - x0_strict["FP"],
            "candidate_cases": marginal,
        },
        "promotion_constraints": contract.promotion_constraints,
    }
    matrix = {"schema_version": "guardian-cycle2-disagreement-v1", "pairs": {}}
    for i, left_arm in enumerate(arms):
        for right_arm in arms[i + 1:]:
            counts = {"00": 0, "01": 0, "10": 0, "11": 0, "not_jointly_valid": 0}
            for case in dataset.cases:
                left, right = by[(case.case_id, left_arm)], by[(case.case_id, right_arm)]
                if left.get("label") not in {0, 1} or right.get("label") not in {0, 1}:
                    counts["not_jointly_valid"] += 1
                else:
                    counts[f"{left['label']}{right['label']}"] += 1
            matrix["pairs"][left_arm + "__" + right_arm] = counts
    return report, matrix
