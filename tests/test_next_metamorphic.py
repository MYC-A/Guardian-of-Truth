import json
import unittest

from guardian_truth.next.binder import bind_claim
from guardian_truth.next.claims import extract_claims
from guardian_truth.next.effects import schema_registry
from guardian_truth.next.logic import negate
from guardian_truth.next.model_tasks import parse_claim_proposal
from guardian_truth.next.normalize import build_evidence, normalize_trace
from guardian_truth.next.policy import compile_policy
from guardian_truth.next.records import (
    Claim, ClaimKind, EvidenceRecord, EvidenceStatus, FourValue, Span,
)


POLICY = """⟦SYSTEM⟧
[AVAILABLE TOOLS]
- change_line — changes a line
  line_id: string!
You should only make one tool call at a time.
⟦USER⟧
Help with line_id=L1.
"""


class RequiredMetamorphicPairs(unittest.TestCase):
    def test_01_user_action_is_not_assistant_action(self):
        user = POLICY + '⟦USER_TOOL_CALL name="change_line"⟧\n{"line_id":"L1"}'
        assistant = '⟦ASSISTANT_TOOL_CALL name="change_line"⟧\n{"line_id":"L1"}'
        user_records = build_evidence(normalize_trace(user, ""))
        assistant_records = build_evidence(normalize_trace(POLICY, assistant))
        self.assertFalse(any(r.status is EvidenceStatus.ATTEMPTED and r.source.document == "response"
                             for r in user_records))
        self.assertTrue(any(r.status is EvidenceStatus.ATTEMPTED and r.source.document == "response"
                            for r in assistant_records))

    def test_02_intent_is_not_completed(self):
        self.assertEqual(ClaimKind.INTENT, extract_claims("⟦ASSISTANT⟧\nЯ могу изменить тариф.")[0].kind)
        self.assertEqual(ClaimKind.ACTION, extract_claims("⟦ASSISTANT⟧\nЯ уже изменил тариф.")[0].kind)

    def test_03_claim_is_not_observation(self):
        evidence = build_evidence(normalize_trace(POLICY, "⟦ASSISTANT⟧\nЯ уже изменил тариф."))
        self.assertFalse(evidence)

    def test_04_attempt_is_not_effect_confirmation(self):
        evidence = build_evidence(normalize_trace(
            POLICY, '⟦ASSISTANT_TOOL_CALL name="change_line"⟧\n{"line_id":"L1"}'))
        self.assertTrue(any(r.status is EvidenceStatus.ATTEMPTED for r in evidence))
        self.assertFalse(any(r.status is EvidenceStatus.CONFIRMED for r in evidence))

    def test_05_failure_is_not_completed_or_no_effect(self):
        trace = POLICY + ('⟦ASSISTANT_TOOL_CALL name="change_line"⟧\n{"line_id":"L1"}\n'
                          '⟦TOOL_RESULT name="change_line" requestor="assistant"⟧\n'
                          '{"success":false}')
        evidence = build_evidence(normalize_trace(trace, ""))
        self.assertTrue(any(r.status is EvidenceStatus.FAILED for r in evidence))
        self.assertFalse(any(r.status is EvidenceStatus.CONFIRMED or r.predicate == "no_effect" for r in evidence))

    def test_06_not_found_is_not_proven_absence(self):
        claim = extract_claims("⟦ASSISTANT⟧\nДругих вариантов не найдено.")[0]
        self.assertEqual(FourValue.UNKNOWN, bind_claim(claim, []).status)

    def test_07_unknown_is_not_false(self):
        self.assertEqual(FourValue.UNKNOWN, negate(FourValue.UNKNOWN))

    def test_08_proposal_is_not_execution(self):
        claim = extract_claims("⟦ASSISTANT⟧\nЯ могу предложить изменить тариф.")[0]
        self.assertEqual("intent", claim.modality)

    def test_09_request_is_not_confirmation(self):
        evidence = build_evidence(normalize_trace(POLICY, "⟦ASSISTANT⟧\nПодтвердите изменение тарифа."))
        self.assertFalse(any(r.status is EvidenceStatus.CONFIRMED for r in evidence))

    def test_10_same_type_is_not_same_entity(self):
        claim = Claim("c", ClaimKind.ACTION, "assistant", "change", "completed", Span("response", 0, 1),
                      modality="completed", entities=(("line_id", "L1"),))
        evidence = [EvidenceRecord("e", "event", "call", "effect", "changed", EvidenceStatus.CONFIRMED,
                                   Span("prompt", 0, 1), entities=(("line_id", "L2"),))]
        self.assertEqual(FourValue.UNKNOWN, bind_claim(claim, evidence).status)

    def test_11_old_is_not_current_by_deletion(self):
        trace = POLICY + ('⟦ASSISTANT_TOOL_CALL name="read_line"⟧\n{"line_id":"L1"}\n'
                          '⟦TOOL_RESULT name="read_line" requestor="assistant"⟧\n{"line_id":"L1","state":"old"}\n'
                          '⟦ASSISTANT_TOOL_CALL name="read_line"⟧\n{"line_id":"L1"}\n'
                          '⟦TOOL_RESULT name="read_line" requestor="assistant"⟧\n{"line_id":"L1","state":"new"}')
        states = [r for r in build_evidence(normalize_trace(trace, "")) if r.predicate == "state"]
        self.assertEqual(["old", "new"], [r.object for r in states])
        self.assertLess(states[0].freshness, states[1].freshness)

    def test_12_tool_name_is_not_effect(self):
        contract = schema_registry(POLICY)["change_line"]
        self.assertFalse(contract.guaranteed_effects)

    def test_13_llm_interpretation_is_not_fact(self):
        response = "Тариф изменён."
        proposal = {"claims": [{"kind": "action", "subject": "assistant", "predicate": "change",
                                "object": "fare", "modality": "completed", "quote": response,
                                "occurrence": 0, "entities": []}], "uncovered_quotes": []}
        claims, _ = parse_claim_proposal(json.dumps(proposal, ensure_ascii=False), response)
        self.assertEqual(1, len(claims))
        self.assertFalse(build_evidence(normalize_trace(POLICY, "⟦ASSISTANT⟧\n" + response)))

    def test_14_irrelevant_candidate_context_does_not_change_policy(self):
        a = compile_policy(POLICY)
        b = compile_policy(POLICY + "⟦ASSISTANT⟧\nUnrelated candidate text.")
        self.assertEqual(a.source_hash, b.source_hash)
        self.assertEqual(a.rules, b.rules)


if __name__ == "__main__":
    unittest.main()
