import json
from pathlib import Path
import unittest

from guardian_truth.cycle2.model_gate import (
    build_gate_report,
    evaluate_candidate,
    load_gate_contract,
    response_schema,
)
from guardian_truth.llm_client import ChatClientError, Completion


ROOT = Path(__file__).resolve().parents[1]
CONTRACT = ROOT / "contracts" / "cycle2_model_gate_v1.json"


class FakeClient:
    def __init__(self, replies):
        self.replies = iter(replies)
        self.calls = []

    def complete(self, messages, *, schema=None, reasoning_effort=None):
        self.calls.append((messages, schema, reasoning_effort))
        reply = next(self.replies)
        if isinstance(reply, Exception):
            raise reply
        return reply


class FakeClock:
    def __init__(self):
        self.value = 0.0
        self.sleeps = []

    def __call__(self):
        return self.value

    def sleep(self, delay):
        self.sleeps.append(delay)
        self.value += delay


def correct_replies(contract):
    return [Completion(json.dumps({"case_id": case.id, "answer": case.expected_answer}),
                       {"prompt_tokens": 4, "completion_tokens": 2, "headers": "secret"},
                       "served-model") for case in contract.cases]


class Cycle2ModelGateTests(unittest.TestCase):
    def setUp(self):
        self.contract = load_gate_contract(CONTRACT)

    def test_contract_is_frozen_bounded_and_uses_one_schema(self):
        self.assertEqual(16, len(self.contract.cases))
        self.assertEqual(0, self.contract.request.max_retries)
        self.assertGreaterEqual(len({case.family for case in self.contract.cases}), 4)
        schema = response_schema(self.contract)
        self.assertFalse(schema["additionalProperties"])
        self.assertEqual({"case_id", "answer"}, set(schema["properties"]))
        self.assertEqual(64, len(self.contract.digest))

    def test_all_valid_correct_outputs_pass_and_expected_is_not_sent(self):
        client = FakeClient(correct_replies(self.contract))
        clock = FakeClock()
        result = evaluate_candidate(
            client, self.contract, provider="local", requested_model="test",
            credential_status="valid_unexposed", clock=clock, sleep=clock.sleep,
        )
        self.assertTrue(result["admitted"])
        self.assertEqual((16, 16, 16), (
            result["transport_success"], result["schema_valid"], result["semantic_correct"],
        ))
        self.assertEqual(15, len(clock.sleeps))
        for case, call in zip(self.contract.cases, client.calls):
            messages, schema, reasoning = call
            self.assertNotIn(case.expected_answer, messages[1]["content"])
            self.assertEqual(response_schema(self.contract), schema)
            self.assertEqual("low", reasoning)
        self.assertNotIn("secret", json.dumps(result))

    def test_schema_error_is_not_semantic_error(self):
        replies = correct_replies(self.contract)
        replies[0] = Completion('{"answer":"USER_ACTION","extra":true}', {}, "served-model")
        result = evaluate_candidate(
            FakeClient(replies), self.contract, provider="local", requested_model="test",
            credential_status="valid_unexposed", clock=lambda: 0.0, sleep=lambda _: None,
        )
        self.assertEqual("SCHEMA_ERROR", result["cases"][0]["outcome"])
        self.assertEqual("not_evaluated", result["cases"][0]["semantic_status"])
        self.assertTrue(result["admitted"])

    def test_rate_limits_remain_transport_errors_and_fail_admission(self):
        replies = correct_replies(self.contract)
        replies[2] = ChatClientError("rate_limit", retryable=True)
        replies[3] = ChatClientError("rate_limit", retryable=True)
        result = evaluate_candidate(
            FakeClient(replies), self.contract, provider="groq", requested_model="test",
            credential_status="valid_unexposed", clock=lambda: 0.0, sleep=lambda _: None,
        )
        self.assertFalse(result["admitted"])
        self.assertEqual(2, result["429_count"])
        self.assertEqual("TRANSPORT_ERROR", result["cases"][2]["outcome"])
        self.assertEqual("not_evaluated", result["cases"][2]["semantic_status"])

    def test_report_blocks_policy_benchmark_when_nobody_passes(self):
        replies = [ChatClientError("timeout", retryable=True) for _ in self.contract.cases]
        result = evaluate_candidate(
            FakeClient(replies), self.contract, provider="local", requested_model="test",
            credential_status="valid_unexposed", clock=lambda: 0.0, sleep=lambda _: None,
        )
        report = build_gate_report(self.contract, [result])
        self.assertEqual("EVALUATION_BLOCKED_BY_PROVIDER", report["status"])
        self.assertFalse(report["policy_benchmark_permitted"])
        self.assertEqual([], report["admitted_candidates"])


if __name__ == "__main__":
    unittest.main()
