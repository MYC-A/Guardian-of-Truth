"""Stage aggregation keeps conditional semantics distinct from operational yield."""

from collections import Counter

from .stage_goal import score_goal_case


def fraction(numerator, denominator):
    return numerator / denominator if denominator else None


def confusion(pairs):
    counts = {name: 0 for name in ("TP", "FP", "FN", "TN")}
    for expected, actual in pairs:
        counts[("TP" if actual else "FN") if expected else ("FP" if actual else "TN")] += 1
    tp, fp, fn, tn = (counts[name] for name in ("TP", "FP", "FN", "TN"))
    return {**counts, "n": len(pairs), "precision": fraction(tp, tp + fp), "recall": fraction(tp, tp + fn),
        "F1": fraction(2 * tp, 2 * tp + fp + fn),
        "balanced_error": (fraction(fp, fp + tn) + fraction(fn, fn + tp)) / 2 if fp + tn and fn + tp else None}


def summarize_goal(cases, predictions):
    if len({row["case_id"] for row in predictions}) != len(predictions):
        raise ValueError("duplicate predictions")
    by_id = {row["case_id"]: row for row in predictions}
    if set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("stage prediction coverage incomplete")
    scores = [score_goal_case(case, by_id[case["case_id"]]["prediction"]) for case in cases]
    metrics = {}
    for field in scores[0]["fields"]:
        records = [score["fields"][field] for score in scores if score["fields"][field]["semantic_case_eligible"]]
        correct, candidates = sum(row["candidate_correct"] for row in records), sum(row["candidate_count"] for row in records)
        metrics[field] = {"eligible_cases": len(records), "excluded_transport_schema_cases": len(scores) - len(records),
            "candidate_correct": correct, "candidate_count": candidates,
            "candidate_precision": fraction(correct, candidates),
            "any_candidate_case_recall": fraction(sum(row["any_correct"] for row in records), len(records)),
            "all_candidate_case_accuracy": fraction(sum(row["all_correct"] for row in records), len(records)),
            "strict_operational_case_yield": fraction(sum(row["all_correct"] for row in records), len(scores))}
    core_counts = Counter(score["core_status"] for score in scores)
    reasons, contributing, coverage, taxonomy = Counter(), Counter(), Counter(), []
    certificate = {status: {"definitive": 0, "valid": 0} for status in ("PROVED_ERROR", "PROVED_NO_ERROR")}
    telemetry = []
    disagreement = Counter()
    for case, score in zip(cases, scores):
        row = by_id[case["case_id"]]
        prediction = row["prediction"]
        telemetry.extend(row["request_telemetry"])
        core = prediction["core_result"]
        status, diag = core["status"], core["diagnostics"]
        if diag["primary_reason"]:
            reasons[diag["primary_reason"]] += 1
        contributing.update(diag["contributing_reasons"])
        coverage[prediction["goal_plan"]["coverage"]["status"]] += 1
        if status in certificate:
            certificate[status]["definitive"] += 1
            certificate[status]["valid"] += int(bool(core["certificate_check"] and core["certificate_check"]["valid"]))
        failures = []
        for reason in prediction["goal_plan"]["failures"]:
            if reason == "TRANSPORT_ERROR":
                failures.append("TRANSPORT")
            elif reason == "SCHEMA_ERROR":
                failures.append("SCHEMA")
        if not failures and any(not record["all_correct"] for record in score["fields"].values()):
            failures.append("GOAL_PLAN_SEMANTICS")
        if not score["core_status_correct"]:
            failures.append("GOAL_PLAN_SEMANTICS" if status in {"PROVED_ERROR", "PROVED_NO_ERROR"} else "EVIDENCE_COMPLETENESS")
            if any(binding["failures"] for binding in prediction["operational_bindings"]):
                failures.append("GOAL_PLAN_SEMANTICS")
            if diag["primary_reason"] == "GOAL_PLAN_AMBIGUOUS":
                failures.append("GOAL_PLAN_SEMANTICS")
            if any("COMPLETENESS" in item for item in diag["missing_evidence"]):
                failures.append("CERTIFICATE")
        taxonomy.append({"case_id": case["case_id"], "components": sorted(set(failures)),
            "actual_core_status": status, "expected_core_status": case["gold"]["verdict"],
            "primary_reason": diag["primary_reason"], "contributing_reasons": diag["contributing_reasons"],
            "blocked_hypotheses": diag["blocked_hypotheses"], "missing_evidence": diag["missing_evidence"],
            "operational_discarded": [item for binding in prediction["operational_bindings"] for item in binding["discarded"]],
            "scope": "controlled stage annotation mismatch; conservative UNRESOLVED is not a false proof"})
        disagreement[(row["baseline_x0"]["binary_label"], score["binary_label"])] += 1
    eligible_binary = [score for score in scores if score["expected_binary_label"] is not None]
    pairs = [(score["expected_binary_label"], score["binary_label"]) for score in eligible_binary]
    baseline_pairs = [(score["expected_binary_label"], by_id[score["case_id"]]["baseline_x0"]["binary_label"]) for score in eligible_binary]
    # Report binary scores only together with actual unresolved and certificate rates.
    definitive = core_counts["PROVED_ERROR"] + core_counts["PROVED_NO_ERROR"]
    from .latency import percentile
    from .integrity import digest
    unique_semantic_inputs = {digest({key: value for key, value in case["input"].items() if key != "context_variant"}) for case in cases}
    return {"case_count": len(cases), "unique_semantic_inputs": len(unique_semantic_inputs), "field_metrics": metrics,
        "core": {"counts": dict(core_counts), "resolution_rate": fraction(definitive, len(cases)),
            "unresolved_rate": fraction(core_counts["UNRESOLVED"], len(cases)),
            "exact_status_accuracy": fraction(sum(score["core_status_correct"] for score in scores), len(cases)),
            "certificate_validation": {status: {**counts, "rate": fraction(counts["valid"], counts["definitive"])} for status, counts in certificate.items()}},
        "competition_binary": {**confusion(pairs), "excluded_gold_unresolved_cases": len(scores) - len(pairs)},
        "baseline_x0_binary": confusion(baseline_pairs), "semantic_coverage": dict(coverage),
        "primary_unresolved_reasons": dict(reasons), "contributing_unresolved_reasons": dict(contributing),
        "provider": {"attempts": len(telemetry), "transport_success": sum(row["transport_status"] == "SUCCESS" for row in telemetry),
            "schema_valid": sum(row["schema_status"] == "VALID" for row in telemetry),
            "latency_ms_p50": percentile([row["latency_ms"] for row in telemetry], .5),
            "latency_ms_p95": percentile([row["latency_ms"] for row in telemetry], .95),
            "token_usage": {key: sum(row["usage"].get(key, 0) for row in telemetry) for key in ("prompt_tokens", "completion_tokens", "total_tokens")},
            "cost": "NOT_AUDITED"},
        "failure_taxonomy": taxonomy, "per_case_scores": scores,
        "disagreement_matrix": [{"x0": pair[0], "vnext": pair[1], "count": count} for pair, count in sorted(disagreement.items())],
        "limitations": ["controlled development extension, not new blind evidence",
            "input context_variant duplicates are not independent trajectories",
            "exact normalized field scoring is not independent semantic equivalence adjudication",
            "missing true tool schemas; plan-head interface candidates are not contracts",
            "open NL meaning prevents strong NO_ERROR proof even when a controlled annotation expects it"]}
