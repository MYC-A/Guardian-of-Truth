from pathlib import Path

from guardian_truth.cycle2.effect_ceiling import _metrics


def _row(gold, label, verdict, fallback, evidence=1):
    result = {
        "label": label,
        "internal_verdict": verdict,
        "telemetry": {"used_binary_fallback": fallback, "n_evidence_events": evidence},
    }
    return {"gold": gold, "X5_T0": result, "X5_T1": result}


def test_conditional_recall_excludes_unresolved_positive():
    rows = [
        _row(1, 1, "PROVED_ERROR", False),
        _row(1, 0, "UNRESOLVED", True),
        _row(0, 0, "PROVED_NO_ERROR", False),
    ]
    metrics = _metrics(rows, "X5_T0")
    assert metrics["recall"] == 0.5
    assert metrics["conditional_recall_on_internally_resolved_positives"] == 1.0
    assert metrics["resolved_positive_denominator"] == 1
