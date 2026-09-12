import unittest
import json
import tempfile
from pathlib import Path

from guardian_truth.next.binder import bind_claim, bind_claim_candidates
from guardian_truth.next.claims import extract_claims, extract_claims_with_coverage
from guardian_truth.next.effects import load_human_contracts
from guardian_truth.next.logic import conjunction, disjunction, negate
from guardian_truth.next.normalize import build_evidence, normalize_trace
from guardian_truth.next.policy import compile_policy
from guardian_truth.next.records import (
    Claim, ClaimKind, EvidenceRecord, EvidenceStatus, FourValue, Span, ToolEffectContract,
)


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
        self.assertEqual(len(bundle.segments), len(bundle.coverage))
        self.assertTrue(all(item.text for item in bundle.segments))
        self.assertTrue(all(item.status in {"RULE", "CONTEXT", "UNKNOWN"} for item in bundle.coverage))


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

    def test_success_confirms_only_contract_guaranteed_effect(self):
        prompt = SYSTEM + ('⟦ASSISTANT_TOOL_CALL name="update"⟧\n{"line_id":"L1"}\n'
                           '⟦TOOL_RESULT name="update" requestor="assistant"⟧\n'
                           '{"success":true}')
        contract = ToolEffectContract("update", guaranteed_effects=("line_updated",),
                                      provenance="T1_human_contract")
        evidence = build_evidence(normalize_trace(prompt, ""), {"update": contract})
        confirmed = [item for item in evidence if item.status is EvidenceStatus.CONFIRMED]
        self.assertEqual(["line_updated"], [item.object for item in confirmed])

    def test_failure_no_effect_requires_explicit_contract(self):
        prompt = SYSTEM + ('⟦ASSISTANT_TOOL_CALL name="update"⟧\n{"line_id":"L1"}\n'
                           '⟦TOOL_RESULT name="update" requestor="assistant"⟧\n'
                           '{"success":false}')
        unknown = ToolEffectContract("update", guaranteed_effects=("line_updated",))
        proven = ToolEffectContract("update", guaranteed_effects=("line_updated",),
                                    failure_no_effect=FourValue.TRUE,
                                    provenance="T1_human_contract")
        self.assertFalse(any(item.predicate == "no_effect" for item in
                             build_evidence(normalize_trace(prompt, ""), {"update": unknown})))
        self.assertTrue(any(item.predicate == "no_effect" for item in
                            build_evidence(normalize_trace(prompt, ""), {"update": proven})))

    def test_unrelated_confirmed_effect_does_not_support_action(self):
        claim = Claim("c", ClaimKind.ACTION, "assistant", "refund", "completed",
                      Span("response", 0, 1), modality="completed")
        evidence = [EvidenceRecord("e", "event", "call", "effect_confirmed", "booking_changed",
                                   EvidenceStatus.CONFIRMED, Span("prompt", 0, 1))]
        self.assertEqual(FourValue.UNKNOWN, bind_claim(claim, evidence).status)

    def test_multiple_entity_bindings_are_preserved_when_they_change_status(self):
        claim = Claim("c", ClaimKind.ACTION, "assistant", "cancel", True,
                      Span("response", 0, 1))
        evidence = [
            EvidenceRecord("e1", "x", "call", "effect_confirmed", "cancel",
                           EvidenceStatus.CONFIRMED, Span("prompt", 0, 1),
                           (("order_id", "A"),)),
            EvidenceRecord("e2", "y", "call", "call_attempted", "cancel",
                           EvidenceStatus.ATTEMPTED, Span("prompt", 1, 2),
                           (("order_id", "B"),)),
        ]
        result = bind_claim_candidates(claim, evidence)
        self.assertEqual(2, len(result.candidates))
        self.assertTrue(result.requires_resolution)
        self.assertEqual(FourValue.UNKNOWN, result.stable_status)

    def test_human_contract_registry_requires_t1_provenance(self):
        row = {"tool": "update", "guaranteed_effects": ["update"], "possible_effects": [],
               "failure_no_effect": "unknown", "reads": [], "writes": ["line"],
               "entity_fields": ["line_id"], "freshness": "result_event",
               "idempotent": "unknown", "provenance": "schema_only",
               "tool_version": "v1", "inputs": ["line_id"], "preconditions": [],
               "success_predicate": ["success=true"], "entity_key_mapping": {"line_id": "line"},
               "provenance_transform": "preserve", "evidence_source": "DOC_EXPLICIT"}
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "contracts.json"
            path.write_text(json.dumps({"schema_version": "guardian-tool-effects-v1",
                                        "contracts": [row]}), encoding="utf-8")
            with self.assertRaises(ValueError):
                load_human_contracts(path)


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

    def test_unextracted_declarative_sentence_is_visible_as_unknown(self):
        result = extract_claims_with_coverage("⟦ASSISTANT⟧\nСтоимость составляет 708 долларов.")
        self.assertFalse(result.claims)
        self.assertEqual(["UNKNOWN"], [item.status for item in result.coverage])

    def test_question_is_explicitly_non_verifiable(self):
        result = extract_claims_with_coverage("⟦ASSISTANT⟧\nПодтвердите изменение?")
        self.assertEqual(["NON_VERIFIABLE"], [item.status for item in result.coverage])


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
