import json
import unittest

from guardian_truth.llm_client import Completion
from guardian_truth.next.model_arms import (
    ArmVerdict,
    CanonicalQuery,
    HOLISTIC_SCHEMA,
    HolisticArmInput,
    QUERY_CONDITIONED_SCHEMA,
    QueryConditionedArmInput,
    SourceDocument,
    SourceEvent,
    parse_holistic_result,
    parse_query_conditioned_result,
    run_holistic_arm,
    run_query_conditioned_arm,
)
from guardian_truth.next.records import Span


class FakeClient:
    def __init__(self, payload):
        self.payload = payload
        self.calls = []

    def complete(self, messages, *, schema=None, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort, None))
        return Completion(json.dumps(self.payload), {"total_tokens": 7}, "fake/model")

    def complete_budgeted(self, messages, *, budget, schema=None, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort, budget))
        return Completion(json.dumps(self.payload), {"total_tokens": 7}, "fake/model")


def _holistic_input():
    response = "I changed order A. The operation failed."
    return HolisticArmInput.from_prompt_response(
        "Never claim a completed change after failure.", response,
        events=(SourceEvent("assistant:0", "response", 0, len(response)),),
    )


def _x3_input():
    policy_text = "Never claim a completed change after failure."
    response = "I changed order A. The operation failed."
    return QueryConditionedArmInput(
        policy=SourceDocument("policy", policy_text),
        documents=(SourceDocument("response", response),),
        events=(SourceEvent("assistant:0", "response", 0, len(response)),),
        queries=(CanonicalQuery(
            "claim:0", "claim", "assistant", "changed", "order A",
            Span("response", 0, 18), "assistant:0",
        ),),
    )


def _citation(document="response", quote="operation failed", event_id="assistant:0"):
    return {"document": document, "quote": quote, "occurrence": 0, "event_id": event_id}


class HolisticModelArmTests(unittest.TestCase):
    def test_holistic_input_cannot_include_evaluation_documents(self):
        with self.assertRaisesRegex(ValueError, "exactly prompt and response"):
            HolisticArmInput((
                SourceDocument("prompt", "p"), SourceDocument("response", "r"),
                SourceDocument("explanation", "evaluation-only text"),
            ))

    def test_x1_uses_strict_schema_and_sends_only_label_free_input(self):
        client = FakeClient({
            "verdict": "error", "label": 1,
            "responsible_sources": [_citation()],
        })
        result = run_holistic_arm(client, _holistic_input())
        self.assertEqual(ArmVerdict.ERROR, result.verdict)
        self.assertEqual(1, result.label)
        self.assertEqual("fake/model", result.returned_model)
        messages, schema, effort, budget = client.calls[0]
        self.assertIs(schema, HOLISTIC_SCHEMA)
        self.assertEqual("low", effort)
        self.assertIsNone(budget)
        supplied = json.loads(messages[1]["content"])
        self.assertEqual({"documents", "events"}, set(supplied))
        self.assertNotIn("label", supplied)
        self.assertNotIn("explanation", supplied)

    def test_x2_reuses_transport_but_preserves_arm_identity(self):
        client = FakeClient({
            "verdict": "no_error", "label": 0,
            "responsible_sources": [_citation(document="prompt", quote="Never claim", event_id="")],
        })
        result = run_holistic_arm(client, _holistic_input(), arm="X2_HOLISTIC_LOCAL")
        self.assertEqual("X2_HOLISTIC_LOCAL", result.arm)
        self.assertEqual(0, result.label)

    def test_unknown_is_not_coerced_to_false(self):
        result = parse_holistic_result(
            json.dumps({"verdict": "unknown", "label": None, "responsible_sources": []}),
            _holistic_input(),
        )
        self.assertEqual(ArmVerdict.UNKNOWN, result.verdict)
        self.assertIsNone(result.label)

    def test_inconsistent_unknown_label_is_rejected(self):
        with self.assertRaisesRegex(ValueError, "disagree"):
            parse_holistic_result(
                json.dumps({"verdict": "unknown", "label": 0, "responsible_sources": []}),
                _holistic_input(),
            )

    def test_binary_decision_requires_responsible_source(self):
        with self.assertRaisesRegex(ValueError, "requires responsible"):
            parse_holistic_result(
                json.dumps({"verdict": "error", "label": 1, "responsible_sources": []}),
                _holistic_input(),
            )

    def test_source_citation_must_be_exact_and_inside_named_event(self):
        payload = {"verdict": "error", "label": 1, "responsible_sources": [
            _citation(quote="Operation failed"),
        ]}
        with self.assertRaisesRegex(ValueError, "exact source"):
            parse_holistic_result(json.dumps(payload), _holistic_input())
        payload["responsible_sources"] = [_citation(event_id="missing")]
        with self.assertRaisesRegex(ValueError, "outside its event"):
            parse_holistic_result(json.dumps(payload), _holistic_input())

    def test_extra_explanation_field_is_rejected(self):
        payload = {
            "verdict": "error", "label": 1, "responsible_sources": [_citation()],
            "explanation": "not accepted by the contract",
        }
        with self.assertRaisesRegex(ValueError, "envelope"):
            parse_holistic_result(json.dumps(payload), _holistic_input())

    def test_budgeted_path_is_provider_neutral(self):
        marker = object()
        client = FakeClient({"verdict": "unknown", "label": None, "responsible_sources": []})
        run_holistic_arm(client, _holistic_input(), budget=marker, reasoning_effort=None)
        self.assertIs(marker, client.calls[0][3])


class QueryConditionedModelArmTests(unittest.TestCase):
    def test_x3_rejects_evaluation_only_documents(self):
        with self.assertRaisesRegex(ValueError, "evaluation-only"):
            QueryConditionedArmInput(
                policy=SourceDocument("policy", "rule"),
                documents=(SourceDocument("explanation", "hidden"),),
                events=(),
                queries=(CanonicalQuery(
                    "q", "claim", "assistant", "p", True,
                    Span("policy", 0, 4),
                ),),
            )

    def test_x3_uses_strict_schema_and_deterministic_violation_aggregation(self):
        client = FakeClient({"decisions": [{
            "query_id": "claim:0", "relation": "violates",
            "responsible_sources": [_citation()],
        }]})
        result = run_query_conditioned_arm(client, _x3_input())
        self.assertEqual(ArmVerdict.ERROR, result.verdict)
        self.assertEqual(1, result.label)
        messages, schema, _, _ = client.calls[0]
        self.assertIs(schema, QUERY_CONDITIONED_SCHEMA)
        supplied = json.loads(messages[1]["content"])
        self.assertEqual({"policy", "documents", "events", "queries"}, set(supplied))
        self.assertNotIn("label", supplied["queries"][0])
        self.assertNotIn("explanation", supplied["queries"][0])

    def test_any_unknown_abstains_instead_of_becoming_no_error(self):
        result = parse_query_conditioned_result(
            json.dumps({"decisions": [{
                "query_id": "claim:0", "relation": "unknown", "responsible_sources": [],
            }]}), _x3_input(),
        )
        self.assertEqual(ArmVerdict.UNKNOWN, result.verdict)
        self.assertIsNone(result.label)

    def test_applies_aggregates_to_no_error_with_source(self):
        result = parse_query_conditioned_result(
            json.dumps({"decisions": [{
                "query_id": "claim:0", "relation": "applies",
                "responsible_sources": [_citation(document="policy", quote="Never claim", event_id="")],
            }]}), _x3_input(),
        )
        self.assertEqual(ArmVerdict.NO_ERROR, result.verdict)
        self.assertEqual(0, result.label)

    def test_missing_duplicate_and_unknown_queries_are_rejected(self):
        with self.assertRaisesRegex(ValueError, "missing"):
            parse_query_conditioned_result(json.dumps({"decisions": []}), _x3_input())
        duplicate = {"decisions": [
            {"query_id": "claim:0", "relation": "unknown", "responsible_sources": []},
            {"query_id": "claim:0", "relation": "unknown", "responsible_sources": []},
        ]}
        with self.assertRaisesRegex(ValueError, "duplicate"):
            parse_query_conditioned_result(json.dumps(duplicate), _x3_input())
        unknown = {"decisions": [
            {"query_id": "not-a-query", "relation": "unknown", "responsible_sources": []},
        ]}
        with self.assertRaisesRegex(ValueError, "unknown"):
            parse_query_conditioned_result(json.dumps(unknown), _x3_input())

    def test_non_unknown_local_decision_requires_citation(self):
        payload = {"decisions": [{
            "query_id": "claim:0", "relation": "violates", "responsible_sources": [],
        }]}
        with self.assertRaisesRegex(ValueError, "requires responsible"):
            parse_query_conditioned_result(json.dumps(payload), _x3_input())

    def test_query_source_must_remain_within_named_event(self):
        with self.assertRaisesRegex(ValueError, "outside its event"):
            QueryConditionedArmInput(
                policy=SourceDocument("policy", "rule"),
                documents=(SourceDocument("response", "abcdef"),),
                events=(SourceEvent("e0", "response", 0, 2),),
                queries=(CanonicalQuery(
                    "q", "claim", "assistant", "p", True,
                    Span("response", 0, 3), "e0",
                ),),
            )


if __name__ == "__main__":
    unittest.main()
