from guardian_truth.vnext.e2e.real_valid_v1 import competition_view, score


def test_gold_firewall_ignores_label_explanation_and_domain():
    base = {"id": "x", "prompt": "p", "response": "r", "label": 0,
            "explanation": "gold", "domain": "airline"}
    changed = {**base, "label": 1, "explanation": "different", "domain": "retail"}
    assert competition_view(base) == competition_view(changed) == {
        "id": "x", "prompt": "p", "response": "r"}


def test_binary_scoring_keeps_internal_status_metrics():
    rows = [
        {"id": "a", "label": 1, "core_status": "PROVED_ERROR", "certificate_valid": True},
        {"id": "b", "label": 0, "core_status": "UNRESOLVED", "certificate_valid": None},
    ]
    result = score(rows, {"a": 1, "b": 1})
    assert (result["TP"], result["FN"]) == (1, 1)
    assert result["statuses"]["PROVED_ERROR"] == 1
    assert result["statuses"]["UNRESOLVED"] == 1
