import unittest

from guardian_truth.next.binder import bind_claim
from guardian_truth.next.claims import extract_claims
from guardian_truth.next.logic import conjunction, disjunction, negate
from guardian_truth.next.normalize import build_evidence, normalize_trace
from guardian_truth.next.policy import compile_policy
from guardian_truth.next.records import Claim, ClaimKind, EvidenceStatus, FourValue, Span


SYSTEM = """⟦SYSTEM⟧
You should only make one tool call at a time.
In each turn you can either send a message or make a tool call. You cannot do both.
⟦USER⟧
Please update line_id=L1.
"""


class PolicySoundnessTests(unittest.TestCase):
    def test_policy_is_trace_independent(self):
        a = compile_policy(SYSTEM)
        b = compile_policy(SYSTEM + "⟦ASSISTANT_TOOL_CALL name=\"update\"⟧\n{}")
        self.assertEqual(a.source_hash, b.source_hash)
        self.assertEqual(a.rules, b.rules)
        self.assertTrue(a.trace_independent)

    def test_all_system_segments_have_coverage_records(self):
        bundle = compile_policy(SYSTEM)
        self.assertTrue(bundle.coverage)
        self.assertTrue(all(item.status in {"compiled", "unknown"} for item in bundle.coverage))


class EvidenceBoundaryTests(unittest.TestCase):
    def test_call_attempt_is_not_effect_confirmation(self):
        response = '⟦ASSISTANT_TOOL_CALL name="update"⟧\n{"line_id":"L1"}'
        evidence = build_evidence(normalize_trace(SYSTEM, response))
        self.assertIn(EvidenceStatus.ATTEMPTED, {item.status for item in evidence})
        self.assertNotIn(EvidenceStatus.CONFIRMED, {item.status for item in evidence})

    def test_failure_does_not_create_no_effect_evidence(self):
        prompt = SYSTEM + ('⟦ASSISTANT_TOOL_CALL name="update"⟧\n{"line_id":"L1"}\n'
                           '⟦TOOL_RESULT name="update" requestor="assistant"⟧\n'
                           '{"success":false,"status":"failed"}')
        evidence = build_evidence(normalize_trace(prompt, ""))
        self.assertIn(EvidenceStatus.FAILED, {item.status for item in evidence})
        self.assertFalse(any(item.predicate == "no_effect" for item in evidence))

    def test_completed_claim_is_not_supported_by_attempt(self):
        claim = Claim("c", ClaimKind.ACTION, "assistant", "обновил", "completed",
                      Span("response", 0, 10), modality="completed")
        response = '⟦ASSISTANT_TOOL_CALL name="update"⟧\n{"line_id":"L1"}'
        binding = bind_claim(claim, build_evidence(normalize_trace(SYSTEM, response)))
        self.assertEqual(FourValue.UNKNOWN, binding.status)


class ClaimBoundaryTests(unittest.TestCase):
    def test_extractor_is_blind_and_distinguishes_intent(self):
        claims = extract_claims("⟦ASSISTANT⟧\nЯ могу изменить тариф.")
        self.assertEqual([ClaimKind.INTENT], [claim.kind for claim in claims])

    def test_completed_action_is_a_separate_claim_kind(self):
        claims = extract_claims("⟦ASSISTANT⟧\nЯ уже изменил тариф.")
        self.assertEqual([ClaimKind.ACTION], [claim.kind for claim in claims])

    def test_not_found_requires_completeness(self):
        claim = extract_claims("⟦ASSISTANT⟧\nЯ не нашёл других вариантов.")[0]
        binding = bind_claim(claim, [])
        self.assertEqual(FourValue.UNKNOWN, binding.status)


class FourValuedLogicTests(unittest.TestCase):
    def test_unknown_is_not_false(self):
        self.assertEqual(FourValue.UNKNOWN, negate(FourValue.UNKNOWN))
        self.assertEqual(FourValue.UNKNOWN, conjunction(FourValue.TRUE, FourValue.UNKNOWN))
        self.assertEqual(FourValue.UNKNOWN, disjunction(FourValue.FALSE, FourValue.UNKNOWN))

    def test_contradiction_is_preserved(self):
        self.assertEqual(FourValue.BOTH, negate(FourValue.BOTH))
        self.assertEqual(FourValue.BOTH, conjunction(FourValue.BOTH, FourValue.TRUE))


if __name__ == "__main__":
    unittest.main()
