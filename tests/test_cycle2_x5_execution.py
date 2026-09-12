from guardian_truth.cycle2.x5_execution import _arm_metrics, _equality_reason


def _result(label, status, fallback, source):
    return {"label": label, "internal_verdict": status, "telemetry": {
        "solver_status": status, "used_binary_fallback": fallback,
        "decision_source": source,
    }}


def test_unresolved_equality_is_not_reported_as_active_agreement():
    result = _result(0, "UNRESOLVED", True, "FALLBACK")
    assert _equality_reason(0, result) == "CORE_UNRESOLVED_FALLBACK_MATCHES_X0"


def test_execution_metrics_expose_unknown_and_binary_score_together():
    rows = [
        {"gold": 1, "X5_CORE": _result(0, "UNRESOLVED", True, "FALLBACK")},
        {"gold": 0, "X5_CORE": _result(0, "PROVED_NO_ERROR", False, "X5_CORE")},
    ]
    metrics = _arm_metrics(rows, "X5_CORE")
    assert metrics["confusion"] == {"TP": 0, "FP": 0, "FN": 1, "TN": 1}
    assert metrics["internal_coverage"] == 0.5
    assert metrics["unresolved_rate"] == 0.5
