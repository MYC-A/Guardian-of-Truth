import json
from pathlib import Path
from types import SimpleNamespace
import unittest

from guardian_truth.llm_client import ChatClientError, Completion
from guardian_truth.next.policy_benchmark import (
    ArmBudget,
    ArmSpec,
    BlindPolicyCase,
    BlindPolicySuite,
    GoldPolicyCase,
    PolicyArm,
    PolicyGoldSet,
    TransportStatus,
    ValidationStatus,
    load_frozen_policy_benchmark,
    run_policy_proposals,
    score_policy_proposals,
)


RULE = "Agents must call the support tool."


def _free_response():
    return json.dumps({
        "status": "FORMALIZED",
        "relation": "UNCONDITIONAL",
        "effect": "REQUIRED",
        "formula": "call(agent, support_tool)",
        "predicates": ["call"],
        "arguments": ["agent", "support_tool"],
        "operators": [],
        "support_quotes": [RULE],
        "features": {
            "modality": "MUST", "quantifier": "ALL", "causality": "NONE",
            "strength": "NONE", "condition": "NONE",
        },
    })


def _typed_response():
    return json.dumps({
        "meanings": [{
            "modality": "requirement",
            "subject": {"kind": "agent", "identifier": "agents"},
            "regulated": {"kind": "action", "predicate": "call", "object": "support tool"},
            "conditions": [],
            "exceptions": [],
            "temporal": {"relation": "unspecified", "anchor": "", "duration": ""},
            "identity_constraints": [],
            "quantification": {"kind": "all", "amount": 0},
            "uncertainty": "certain",
            "unsupported_reason": "",
            "quote": RULE,
            "occurrence": 0,
        }],
        "unknown_quotes": [],
    })


def _suite_and_gold():
    digest = "benchmark-digest"
    case = BlindPolicyCase("case0", "row0", RULE, 10, 10 + len(RULE), "rule-digest")
    suite = BlindPolicySuite(digest, (case,), "test")
    gold = GoldPolicyCase(
        "case0", True, ("UNCONDITIONAL",), ("REQUIRED",), (),
        tuple(sorted({
            "modality": "MUST", "quantifier": "ALL", "causality": "NONE",
            "strength": "NONE", "condition": "NONE", "negation": False,
            "exception": False,
        }.items())),
        ("agent calls support tool",),
    )
    return suite, PolicyGoldSet(digest, (gold,))


class FakeClient:
    def __init__(self, direct=None, typed=None, error=None, max_output_tokens=4096):
        self.direct = direct or _free_response()
        self.typed = typed or _typed_response()
        self.error = error
        self.calls = []
        self.config = SimpleNamespace(max_output_tokens=max_output_tokens)

    def complete(self, messages, *, schema=None, budget=None, reasoning_effort=None):
        self.calls.append({
            "messages": messages, "schema": schema, "budget": budget,
            "reasoning_effort": reasoning_effort,
        })
        if self.error:
            raise ChatClientError(self.error)
        content = self.typed if "meanings" in schema.get("properties", {}) else self.direct
        return Completion(content, {"prompt_tokens": 10, "completion_tokens": 5}, "fake-model")

    def complete_budgeted(self, messages, *, budget, schema=None, reasoning_effort=None):
        return self.complete(
            messages, schema=schema, budget=budget, reasoning_effort=reasoning_effort,
        )


class FrozenPolicyBenchmarkTests(unittest.TestCase):
    def test_real_frozen_file_is_split_into_blind_and_gold_views(self):
        path = Path(__file__).parents[1] / "experiments" / "v8_typed_rules_benchmark_v3.json"
        suite, gold = load_frozen_policy_benchmark(path)
        self.assertEqual(16, len(suite.cases))
        self.assertEqual(16, len(gold.cases))
        self.assertEqual(suite.benchmark_sha256, gold.benchmark_sha256)
        self.assertFalse(hasattr(suite.cases[0], "gold"))
        self.assertFalse(hasattr(suite.cases[0], "features"))

    def test_p1_p2_generation_is_gold_blind_and_budget_matched(self):
        suite, gold = _suite_and_gold()
        client = FakeClient()
        budget = ArmBudget(max_requests_per_case=1, max_input_chars_per_case=50_000,
                           seconds_per_case=30, max_output_tokens=4096)
        run = run_policy_proposals(
            suite,
            clients={PolicyArm.P1_DIRECT: client, PolicyArm.P2_TYPED: client},
            specs=(
                ArmSpec(PolicyArm.P1_DIRECT, budget, "low"),
                ArmSpec(PolicyArm.P2_TYPED, budget, "low"),
            ),
        )
        self.assertTrue(run.p1_p2_equal_budget)
        self.assertFalse(run.gold_visible_to_proposal_stage)
        self.assertEqual(2, len(client.calls))
        visible = json.dumps([call["messages"] for call in client.calls])
        self.assertNotIn("agent calls support tool", visible)
        self.assertNotIn("critical_requirements", visible)
        limits = {(call["budget"].max_requests, call["budget"].max_input_chars,
                   call["budget"].seconds) for call in client.calls}
        self.assertEqual({(1, 50_000, 30)}, limits)

        report = score_policy_proposals(run, gold)
        by_arm = {arm: dict(values) for arm, values in report.by_arm}
        self.assertEqual(1, by_arm["P1"]["transport_success"])
        self.assertEqual(1, by_arm["P2"]["validation_success"])
        # P1 has no exception slot; P2 has no causality/strength slots.
        self.assertEqual(6 / 7, by_arm["P1"]["feature_coverage"])
        self.assertEqual(5 / 7, by_arm["P2"]["feature_coverage"])
        self.assertEqual("GOLD_APPLIED_AFTER_PROPOSAL_FREEZE", report.scoring_stage)

    def test_unequal_p1_p2_budget_is_rejected_before_calls(self):
        suite, _ = _suite_and_gold()
        client = FakeClient()
        with self.assertRaisesRegex(ValueError, "equal budgets"):
            run_policy_proposals(
                suite,
                clients={PolicyArm.P1_DIRECT: client, PolicyArm.P2_TYPED: client},
                specs=(
                    ArmSpec(PolicyArm.P1_DIRECT, ArmBudget(max_output_tokens=4096), "low"),
                    ArmSpec(PolicyArm.P2_TYPED, ArmBudget(max_output_tokens=2048), "low"),
                ),
            )
        self.assertFalse(client.calls)

    def test_transport_and_validation_failures_are_separate(self):
        suite, _ = _suite_and_gold()
        invalid = FakeClient(direct="not-json")
        invalid_run = run_policy_proposals(
            suite,
            clients={PolicyArm.P1_DIRECT: invalid},
            specs=(ArmSpec(PolicyArm.P1_DIRECT, ArmBudget(), "low"),),
        )
        record = invalid_run.records[0]
        self.assertEqual(TransportStatus.SUCCESS, record.transport_status)
        self.assertEqual(ValidationStatus.INVALID, record.validation_status)

        failing = FakeClient(error="rate_limit")
        failed_run = run_policy_proposals(
            suite,
            clients={PolicyArm.P2_TYPED: failing},
            specs=(ArmSpec(PolicyArm.P2_TYPED, ArmBudget(), "low"),),
        )
        record = failed_run.records[0]
        self.assertEqual(TransportStatus.API_ERROR, record.transport_status)
        self.assertEqual(ValidationStatus.INVALID, record.validation_status)
        self.assertEqual("rate_limit", record.error_category)

    def test_p3_interface_uses_reasoning_effort_without_live_claim(self):
        suite, _ = _suite_and_gold()
        client = FakeClient()
        run = run_policy_proposals(
            suite,
            clients={PolicyArm.P3_REASONING: client},
            specs=(ArmSpec(PolicyArm.P3_REASONING, ArmBudget(), "high"),),
        )
        self.assertEqual("high", client.calls[0]["reasoning_effort"])
        self.assertEqual(PolicyArm.P3_REASONING, run.records[0].arm)


if __name__ == "__main__":
    unittest.main()
