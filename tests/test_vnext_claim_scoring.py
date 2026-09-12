from scripts.vnext_claim_scoring import score_case, summarize


def fixture():
    gold = {"start": 0, "end": 12, "disposition": "VERIFIABLE_TYPED", "kind": "ACTION_COMPLETED",
        "actor": "assistant", "entity_refs": ["Q-1"], "source_refs": ["ASSISTANT"], "relation_types": []}
    case = {"case_id": "c0", "family": "fixture", "input": {"response": "Done Q-1 now."}, "gold": {"spans": [gold]}}
    node = {**gold, "span": {"start": 0, "end": 12}, "claim_id": "s0"}
    prediction = {"vnext": {"claims": [node], "relations": []}, "vnext_failed_fields": [],
        "vnext_dispositions": [{"start": 0, "end": 12, "disposition": "VERIFIABLE_TYPED"}],
        "C2": {"transport_status": "SUCCESS", "schema_status": "VALID", "claims": [
            {"start": 0, "end": 12, "kind": "ACTION_COMPLETED", "entities": ["Q-1"], "source": "UNSPECIFIED"}]},
        "inventory": [{"start": 0, "end": 12}]}
    return case, prediction


def test_unavailable_baseline_actor_is_not_invented_zero_accuracy():
    case, prediction = fixture()
    result = summarize([case], [{"case_id": "c0", "prediction": prediction}])
    assert result["field_metrics"]["vnext"]["actor"]["accuracy"] == 1
    assert result["field_metrics"]["C2"]["actor"]["accuracy"] is None
    assert result["field_metrics"]["C2"]["actor"]["status"] == "NOT_MEASURED_UNAVAILABLE_FIELD"
    assert result["paired_shared_field_gain"]["mean"] == 0


def test_unknown_typed_node_keeps_inventory_and_raw_disposition_separate():
    case, prediction = fixture()
    prediction["vnext"]["claims"][0]["disposition"] = "UNKNOWN_SEMANTICS"
    prediction["vnext"]["claims"][0]["actor"] = "UNKNOWN"
    score = score_case(case, prediction)
    assert score["unknown_typed_nodes"] == 1
    assert score["disposition_coverage"]
    assert score["span_detection"]["vnext"]["TP"] == 1
    assert not next(row["correct"] for row in score["fields"] if row["field"] == "actor")


def test_partial_annotations_never_generate_span_precision_gold():
    case, prediction = fixture()
    case["gold"] = {"spans": [{"start": 0, "end": 12, "kind": "ACTION_COMPLETED"}]}
    score = score_case(case, prediction)
    assert score["span_detection"] is None
    assert len(score["fields"]) == 2  # one provided kind for each arm only
    assert score["relation_types"] is None


def test_transport_failure_excluded_not_semantic_false_negative():
    case, prediction = fixture()
    prediction["vnext_failed_fields"] = ["disposition", "kind", "actor", "entity_refs", "source_refs"]
    prediction["vnext_dispositions"] = []
    prediction["vnext"]["claims"][0]["kind"] = None
    result = summarize([case], [{"case_id": "c0", "prediction": prediction}])
    assert result["span_detection"]["vnext"]["FN"] == 0
    assert result["span_detection"]["vnext"]["excluded_transport_schema_cases"] == 1
    assert result["field_metrics"]["vnext"]["kind"]["accuracy"] is None
    assert result["field_metrics"]["vnext"]["kind"]["strict_operational_yield"] == 0


def test_no_contextual_unsupported_gold_never_claims_unsupported_recall():
    case, prediction = fixture()
    result = summarize([case], [{"case_id": "c0", "prediction": prediction}])
    assert result["unsupported_claim_recall"] == "NOT_ESTABLISHED_NO_CONTEXTUAL_GOLD"
    assert result["relation_types"]["directed_edge_accuracy"] == "NOT_ESTABLISHED_NO_DIRECTED_GOLD"
