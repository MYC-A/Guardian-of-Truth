from scripts.evaluate_vnext_provider_gate import percentile, summarize


def row(classification="SEMANTIC_CORRECT"):
    return {"classification": classification, "telemetry": {"latency_ms": 4, "usage": {}}}


def test_gate_requires_all_twelve_attempts():
    assert summarize([row()] * 12)["status"] == "PASSED"
    assert summarize([row()] * 11)["status"] == "NOT_ADMITTED"


def test_gate_does_not_count_transport_error_as_semantic_wrong():
    result = summarize([row()] * 11 + [row("TRANSPORT_ERROR")])
    assert result["status"] == "NOT_ADMITTED"
    assert result["transport_errors"] == 1
    assert result["semantic_wrong"] == 0
    assert result["semantic_accuracy_given_valid"] == 1


def test_gate_schema_error_is_separate_from_semantic_wrong():
    result = summarize([row()] * 11 + [row("SCHEMA_ERROR")])
    assert result["status"] == "NOT_ADMITTED"
    assert result["schema_errors"] == 1
    assert result["semantic_wrong"] == 0


def test_gate_allows_only_one_valid_semantic_error():
    assert summarize([row()] * 11 + [row("SEMANTIC_WRONG")])["status"] == "PASSED"
    assert summarize([row()] * 10 + [row("SEMANTIC_WRONG")] * 2)["status"] == "NOT_ADMITTED"


def test_gate_empty_metrics_and_percentile_are_explicit():
    assert summarize([])["semantic_accuracy_given_valid"] is None
    assert percentile([], .5) is None
    assert percentile([0, 10], .5) == 5
