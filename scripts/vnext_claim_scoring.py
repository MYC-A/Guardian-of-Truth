"""Frozen claim scoring: explicit annotations only, no invented baseline fields."""

RULES = {
    "span": "exact offsets; span precision/recall only cases with complete disposition annotation",
    "vnext_detection": "raw disposition pass, distinct from final UNKNOWN typed coverage",
    "typed": "exact provided fields, entity/source sets; NON_VERIFIABLE excluded from factual typed metrics",
    "partial_gold": "score only annotated fields; no unannotated FP or absent-label invention",
    "c2_comparable_fields": ["kind", "entity_refs", "source_refs"],
    "c2_missing_fields": ["actor", "predicate", "object", "polarity", "modality", "time_anchor", "relations"],
    "c2_unattributed_source": "UNSPECIFIED maps to ASSISTANT only for verifiable candidate source",
    "relations": "only annotated relation type sets; no gold direction/edge accuracy when unavailable",
    "unsupported": "new response-only extension has no factual unsupported gold; NOT_ESTABLISHED",
}
FIELDS = ("kind", "actor", "predicate", "object", "entity_refs", "polarity", "modality", "time_anchor", "source_refs")


def ratio(a, b):
    return a / b if b else None


def field_equal(field, actual, expected):
    if field in {"entity_refs", "source_refs"}:
        return isinstance(actual, (list, tuple)) and set(actual) == set(expected)
    return actual == expected


def baseline_span(row):
    source = row["source"]
    return {"start": row["start"], "end": row["end"], "kind": row["kind"], "entity_refs": row["entities"],
        "source_refs": ["ASSISTANT" if source == "UNSPECIFIED" else source]}


def score_case(case, prediction):
    graph, baseline = prediction["vnext"], prediction["C2"]
    vnext_spans = {(item["span"]["start"], item["span"]["end"]): item for item in graph["claims"]}
    c2_spans = {(item["start"], item["end"]): baseline_span(item) for item in baseline["claims"]}
    results = []
    for expected in case["gold"].get("spans", []):
        offsets = (expected["start"], expected["end"])
        verifiable = expected.get("disposition") != "NON_VERIFIABLE" and expected.get("kind") != "NON_VERIFIABLE"
        for field in FIELDS:
            if field not in expected or not verifiable:
                continue
            actual = vnext_spans.get(offsets, {})
            results.append({"arm": "vnext", "field": field, "correct": field_equal(field, actual.get(field), expected[field]),
                "eligible": field not in prediction["vnext_failed_fields"], "offsets": list(offsets)})
            if field == "kind":
                results[-1].update(expected_label=expected[field], actual_label=actual.get(field) or "UNKNOWN")
            if field in RULES["c2_comparable_fields"]:
                results.append({"arm": "C2", "field": field, "correct": field_equal(field, c2_spans.get(offsets, {}).get(field), expected[field]),
                    "eligible": baseline["transport_status"] == "SUCCESS" and baseline["schema_status"] == "VALID",
                    "offsets": list(offsets)})
                if field == "kind":
                    results[-1].update(expected_label=expected[field], actual_label=c2_spans.get(offsets, {}).get(field) or "UNKNOWN")
    # Whole-case annotations without span labels cannot be converted to invented
    # offsets. A single deterministic span is the only available semantic node.
    if "spans" not in case["gold"] and len(graph["claims"]) == 1:
        node = graph["claims"][0]
        for field in FIELDS:
            if field in case["gold"]:
                results.append({"arm": "vnext", "field": field,
                    "correct": field_equal(field, node.get(field), case["gold"][field]),
                    "eligible": field not in prediction["vnext_failed_fields"], "offsets": None})
    complete = bool(case["gold"].get("spans")) and all("disposition" in item for item in case["gold"]["spans"])
    detection = None
    if complete:
        expected_spans = {(item["start"], item["end"]) for item in case["gold"]["spans"] if item["disposition"] == "VERIFIABLE_TYPED"}
        vnext_detected = {(item["start"], item["end"]) for item in prediction["vnext_dispositions"] if item["disposition"] == "VERIFIABLE_TYPED"}
        c2_detected = set(c2_spans)
        detection = {}
        for arm, actual, eligible in (
            ("vnext", vnext_detected, "disposition" not in prediction["vnext_failed_fields"]),
            ("C2", c2_detected, baseline["transport_status"] == "SUCCESS" and baseline["schema_status"] == "VALID"),
        ):
            detection[arm] = {"TP": len(expected_spans & actual), "FP": len(actual - expected_spans),
                "FN": len(expected_spans - actual), "semantic_eligible": eligible}
    relation_expected = case["gold"].get("relation_types")
    if relation_expected is None and "spans" in case["gold"] and all("relation_types" in item for item in case["gold"]["spans"]):
        relation_expected = list({value for item in case["gold"]["spans"] for value in item["relation_types"]})
    relation = None if relation_expected is None else {
        "correct": set(relation_expected) == {item["relation"] for item in graph["relations"]},
        "eligible": "relations" not in prediction["vnext_failed_fields"], "gold_edge_direction": "NOT_ANNOTATED"}
    return {"case_id": case["case_id"], "family": case["family"], "fields": results,
        "span_detection": detection, "relation_types": relation,
        "unknown_typed_nodes": sum(item["disposition"] == "UNKNOWN_SEMANTICS" for item in graph["claims"]),
        "disposition_coverage": len(graph["claims"]) == len(prediction["inventory"]),
        "identity_binding": "NOT_MEASURABLE_FROM_RESPONSE_ONLY",
        "unsupported_claim_recall": "NOT_ESTABLISHED_NO_CONTEXTUAL_GOLD"}


def summarize(cases, predictions):
    by_id = {row["case_id"]: row["prediction"] for row in predictions}
    if len(by_id) != len(predictions) or set(by_id) != {case["case_id"] for case in cases}:
        raise ValueError("exact stage case coverage required")
    scores = [score_case(case, by_id[case["case_id"]]) for case in cases]
    records = [row for score in scores for row in score["fields"]]
    fields = {}
    for arm in ("vnext", "C2"):
        fields[arm] = {}
        for field in FIELDS:
            annotated = [row for row in records if row["arm"] == arm and row["field"] == field]
            eligible = [row for row in annotated if row["eligible"]]
            if not annotated:
                fields[arm][field] = {"status": "NOT_MEASURED_UNAVAILABLE_FIELD", "denominator": 0, "accuracy": None}
                continue
            correct = sum(row["correct"] for row in eligible)
            fields[arm][field] = {"status": "MEASURED", "denominator": len(eligible), "correct": correct,
                "accuracy": ratio(correct, len(eligible)), "annotated": len(annotated),
                "excluded_transport_schema": len(annotated) - len(eligible),
                "strict_operational_yield": ratio(correct, len(annotated))}
    detection = {}
    for arm in ("vnext", "C2"):
        annotated = [score["span_detection"][arm] for score in scores if score["span_detection"] is not None]
        eligible = [row for row in annotated if row["semantic_eligible"]]
        tp, fp, fn = (sum(row[name] for row in eligible) for name in ("TP", "FP", "FN"))
        detection[arm] = {"TP": tp, "FP": fp, "FN": fn, "precision": ratio(tp, tp + fp),
            "recall": ratio(tp, tp + fn), "F1": ratio(2 * tp, 2 * tp + fp + fn),
            "eligible_cases": len(eligible), "excluded_transport_schema_cases": len(annotated) - len(eligible),
            "partial_gold_cases_not_scored_for_precision": len(scores) - len(annotated)}
    relations = [score["relation_types"] for score in scores if score["relation_types"] is not None]
    eligible_relations = [row for row in relations if row["eligible"]]
    paired = []
    for case in cases:
        score = score_case(case, by_id[case["case_id"]])
        for field in RULES["c2_comparable_fields"]:
            expected_nodes = [node for node in case["gold"].get("spans", []) if field in node and node.get("disposition") != "NON_VERIFIABLE"]
            for node in expected_nodes:
                offset = [node["start"], node["end"]]
                matched = [row for row in score["fields"] if row["field"] == field and row["offsets"] == offset and row["eligible"]]
                if len(matched) == 2:
                    values = {row["arm"]: int(row["correct"]) for row in matched}
                    paired.append({"field": field, "delta": values["vnext"] - values["C2"]})
    deltas = {field: ratio(sum(row["delta"] for row in paired if row["field"] == field),
        sum(row["field"] == field for row in paired)) for field in RULES["c2_comparable_fields"]}
    available_deltas = [delta for delta in deltas.values() if delta is not None]
    mean_delta = ratio(sum(available_deltas), len(available_deltas))
    span = detection["vnext"]
    span_gate = (span["recall"] is not None and span["precision"] is not None and span["recall"] >= .8 and span["precision"] >= .9)
    typed_gate = (mean_delta is not None and mean_delta >= .1 and all(delta >= -.02 for delta in available_deltas))
    kind_f1 = {}
    for arm in ("vnext", "C2"):
        eligible_kind = [row for row in records if row["arm"] == arm and row["field"] == "kind" and row["eligible"]]
        classes = sorted({row["expected_label"] for row in eligible_kind})
        per_class = {}
        for label in classes:
            tp = sum(row["actual_label"] == label and row["expected_label"] == label for row in eligible_kind)
            fp = sum(row["actual_label"] == label and row["expected_label"] != label for row in eligible_kind)
            fn = sum(row["actual_label"] != label and row["expected_label"] == label for row in eligible_kind)
            per_class[label] = {"TP": tp, "FP": fp, "FN": fn, "F1": ratio(2 * tp, 2 * tp + fp + fn)}
        kind_f1[arm] = {"denominator": len(eligible_kind), "per_class": per_class,
            "macro_F1": ratio(sum(row["F1"] for row in per_class.values()), len(per_class))}
    return {"scope": "CONTROLLED_DEVELOPMENT_EXTENSION", "case_count": len(cases), "field_metrics": fields,
        "kind_F1": kind_f1,
        "span_detection": detection, "disposition_coverage": ratio(sum(score["disposition_coverage"] for score in scores), len(scores)),
        "unknown_typed_nodes": sum(score["unknown_typed_nodes"] for score in scores),
        "relation_types": {"accuracy": ratio(sum(row["correct"] for row in eligible_relations), len(eligible_relations)),
            "denominator": len(eligible_relations), "excluded_transport_schema": len(relations) - len(eligible_relations),
            "directed_edge_accuracy": "NOT_ESTABLISHED_NO_DIRECTED_GOLD"},
        "paired_shared_field_gain": {"field_delta": deltas, "mean": mean_delta,
            "denominator": len(paired), "unavailable_C2_fields_never_scored_as_zero": RULES["c2_missing_fields"]},
        "admission": {"span_gate": span_gate, "shared_typed_gain_gate": typed_gate,
            "full_typed_semantic_gain": "NOT_ESTABLISHED_FOR_UNAVAILABLE_C2_FIELDS"},
        "unsupported_claim_recall": "NOT_ESTABLISHED_NO_CONTEXTUAL_GOLD",
        "per_case_scores": scores,
        "failure_taxonomy": [{"case_id": score["case_id"],
            "components": sorted(set(("CLAIM_SEGMENTATION",) if score["span_detection"] and any(
                row["FP"] or row["FN"] for row in score["span_detection"].values() if row["semantic_eligible"]) else ())
                | ({"CLAIM_TYPING"} if any(not row["correct"] for row in score["fields"] if row["eligible"]) else set())
                | ({"CAUSAL_REASONING"} if score["relation_types"] and score["relation_types"]["eligible"]
                    and not score["relation_types"]["correct"] else set())),
            "scope": "annotated semantic errors only; transport/schema appended separately by runner"} for score in scores]}
