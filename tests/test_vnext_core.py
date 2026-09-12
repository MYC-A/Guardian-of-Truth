from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.adapters import AdapterMode
from guardian_truth.vnext.certificates import check_certificate, operational_choice_valid
from guardian_truth.vnext.core import AnalysisInput, analyze
from guardian_truth.vnext.grounding import literal_grounded
from guardian_truth.vnext.escalation import EscalationState, EscalationStep, check_monotonic_update
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.proof_evidence import prove_atom
from guardian_truth.vnext.proof_records import ArgumentConstraint, AtomKind, ProofAtom, TimeMode
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.tools import ContractRegistry
from guardian_truth.vnext.types import CoreStatus, EntityRef, EvaluationHypothesis, Reason, Span, Truth


GOAL = "Read the report."
SCOPE = {"paths": ["/workspace/report.txt", "/workspace/appendix.txt"]}
REGISTRY = ContractRegistry(())


def encoded(value):
    return canonical(value).decode("utf-8")


def call(name="read", path="/workspace/report.txt", actor="ASSISTANT", *, missing=False):
    args = {} if missing else {"path": path}
    return f'⟦{actor}_TOOL_CALL name="{name}" call_id="target"⟧\n' + encoded(args)


def input_case(**changes):
    base = AnalysisInput("", call(), declared_goal=GOAL, ordered_plan=("read report",),
        allowed_scope=SCOPE, tool_schemas=({"name": "read"}, {"name": "send"}),
        history_complete=True, completeness_basis="controlled complete history")
    return replace(base, **changes)


class Backend:
    """Controlled semantic fixture, not a model benchmark or oracle fact provider."""
    def __init__(self, *, alternatives=("read",), mode="TARGET_INVOCATION", omitted_scope=False,
                 ungrounded=False, constraints=(), failure=None, unsafe_subset=False):
        self.tasks = []
        self.alternatives = alternatives
        self.mode = mode
        self.omitted_scope = omitted_scope
        self.ungrounded = ungrounded
        self.constraints = list(constraints)
        self.failure = failure
        self.unsafe_subset = unsafe_subset

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        if self.failure == task:
            return Proposal(None, "TRANSPORT_ERROR", "NOT_RUN", "safe_transport_failure")
        if task == "goal_plan_semantic_hypotheses":
            value = {"hypotheses": [{"declared_goal": GOAL, "expected_step": 0,
                "expected_action": "read report", "allowed_scope": list(SCOPE["paths"]),
                "target_action_state": "invocation", "drift_type": "NO_DRIFT",
                "constraints": self.constraints, "source_quotes": [GOAL], "unresolved_terms": []}]}
        elif task == "operational_action_binding":
            scope = payload["explicit_allowed_scope"]
            checks = []
            for key, values in scope.items():
                checks.append({"clause_id": "scope:" + key, "path": ["path"],
                    "allowed_json": [encoded(value) for value in (values[:1] if self.unsafe_subset else values)]})
            value = {"candidates": [{"tool": tool, "mode": self.mode,
                "checks": [] if self.omitted_scope else checks,
                "covered_clauses": ["action"] if self.omitted_scope else payload["required_clause_ids"],
                "source_quotes": ["imagined normative path"] if self.ungrounded else [payload["normative_source"]]}
                for tool in self.alternatives], "unresolved_terms": []}
        elif task.startswith("claim_"):
            # Only used for a deliberately nonverifiable politeness sentence.
            if task == "claim_relations":
                value = {"relations": []}
            else:
                assert all(span["text"].strip() == "Hello!" for span in payload["span_inventory"])
                fields = {"claim_disposition": {"disposition": "NON_VERIFIABLE"},
                    "claim_kind": {"kind": "NON_VERIFIABLE"}, "claim_actor": {"actor": "assistant"},
                    "claim_predicate": {"predicate": "greet"}, "claim_object_entities": {"object": "greeting", "entity_refs": []},
                    "claim_modality_polarity": {"polarity": "POSITIVE", "modality": "ASSERTED"},
                    "claim_time": {"time_anchor": "NOW"}, "claim_source": {"source_refs": ["ASSISTANT"]},
                    "claim_explicit_causality": {"explicit_causality": False}}
                value = {"spans": [{"span_id": span["span_id"], **fields[task]} for span in payload["span_inventory"]]}
        else:
            raise AssertionError("unexpected semantic task: " + task)
        return Proposal(encoded(value), "SUCCESS", "VALID")


def test_full_goal_frontend_binding_solver_certificate_adapter_pipeline():
    backend = Backend()
    output = analyze(input_case(response=call("send")), backend, enable_t2=False)
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert output.result.certificate_check.valid
    assert output.product_decision.binary_label == 1
    assert not output.product_decision.used_fallback
    assert output.ledger.effects == ()
    assert backend.tasks == ["goal_plan_semantic_hypotheses", "operational_action_binding"]
    assert check_certificate(output.result.certificate, output.context, output.problem, output.ledger, REGISTRY).valid
    assert output.result.world_proofs[0].primitives[0].refutes == ("e0",)


def test_correct_action_with_empirical_meaning_is_not_proved_safe():
    output = analyze(input_case(), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.product_decision.binary_label is None
    assert "COMPLETENESS_UNPROVED" in output.result.diagnostics.missing_evidence


def test_wrong_argument_scope_is_observed_invocation_violation_not_effect():
    output = analyze(input_case(response=call(path="/private/passwords")), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert output.result.certificate_check.valid
    assert output.ledger.observations == ()
    assert output.ledger.effects == ()


def test_all_allowed_values_retained_not_only_first():
    output = analyze(input_case(response=call(path="/workspace/appendix.txt")), Backend(), enable_t2=False)
    assert output.result.world_proofs[0].primitives[0].value is Truth.TRUE
    assert output.result.status is CoreStatus.UNRESOLVED


@pytest.mark.parametrize("backend", [Backend(mode="COMPLETED_EFFECT"), Backend(omitted_scope=True),
    Backend(ungrounded=True), Backend(unsafe_subset=True), Backend(constraints=("only after owner approval",))])
def test_unsupported_effect_or_dropped_constraint_never_becomes_error(backend):
    output = analyze(input_case(response=call("send")), backend, enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.certificate is None
    assert Reason.GOAL_PLAN_AMBIGUOUS in (output.result.diagnostics.primary_reason, *output.result.diagnostics.contributing_reasons)


def test_ambiguous_action_bindings_preserve_disagreement_without_vote():
    output = analyze(input_case(), Backend(alternatives=("read", "send")), enable_t2=False)
    assert output.world_count_required == 2
    assert {world.error_value for world in output.result.world_proofs} == {Truth.TRUE, Truth.FALSE}
    assert output.result.status is CoreStatus.UNRESOLVED


def test_world_budget_stops_before_partial_truth_evaluation():
    output = analyze(input_case(), Backend(alternatives=("read", "send")), enable_t2=False, max_worlds=1)
    assert output.world_count_required == 2
    assert output.problem.worlds == ()
    assert output.result.status is CoreStatus.UNRESOLVED
    assert "WORLD_BUDGET_EXCEEDED:2>1" in output.result.diagnostics.missing_evidence


def test_user_target_call_is_not_an_assistant_violation():
    output = analyze(input_case(response=call("send", actor="USER")), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.world_proofs[0].primitives[0].value is Truth.UNKNOWN


def test_missing_argument_is_unknown_not_false():
    output = analyze(input_case(response=call(missing=True)), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.world_proofs[0].primitives[0].value is Truth.UNKNOWN


def test_wrong_tool_is_false_even_if_optional_argument_evidence_unknown():
    output = analyze(input_case(response=call("send", missing=True)), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert output.result.world_proofs[0].primitives[0].value is Truth.FALSE


def test_transport_diagnostic_survives_to_terminal_core():
    output = analyze(input_case(), Backend(failure="operational_action_binding"), enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.diagnostics.primary_reason is Reason.TRANSPORT_ERROR
    assert output.terminal_unresolved


def test_all_actual_target_calls_checked_and_certificate_rejects_dropping():
    response = call() + "\n" + call("send").replace('call_id="target"', 'call_id="target2"')
    output = analyze(input_case(response=response), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert len(output.result.world_proofs[0].primitives) == 2
    choice = output.context.operational_choices[0]
    assert not operational_choice_valid(replace(choice, atoms=choice.atoms[:1]), output.context, output.ledger)


def test_checker_rejects_literal_or_tool_or_scope_template_tampering():
    output = analyze(input_case(response=call("send")), Backend(), enable_t2=False)
    choice = output.context.operational_choices[0]
    assert operational_choice_valid(choice, output.context, output.ledger)
    atom = choice.atoms[0]
    for changed in (
        replace(choice, source_quotes=("not present",)),
        replace(choice, covered_clauses=("action",)),
        replace(choice, atoms=(replace(atom, predicate="invented_tool"),)),
        replace(choice, atoms=(replace(atom, argument_constraints=(ArgumentConstraint(("path",), ('"/private/passwords"',)),)),)),
        replace(choice, atoms=(replace(atom, time_index=100),)),
    ):
        assert not operational_choice_valid(changed, output.context, output.ledger)


def test_claim_graph_passes_still_inventory_response_text():
    output = analyze(input_case(response="⟦ASSISTANT⟧\nHello!\n" + call("send")), Backend(), enable_t2=False)
    assert len(output.claim_graph.claims) == 1
    assert output.claim_graph.claims[0].disposition.value == "NON_VERIFIABLE"
    assert output.result.status is CoreStatus.PROVED_ERROR


def test_target_primitive_does_not_accept_history_event_as_target():
    ledger = EvidenceLedger.from_events(normalize(call(), ""))
    atom = ProofAtom("a", AtomKind.TARGET_CALL_MATCH, EntityRef("event_id", "e0", "ledger"),
        "read", "true", "assistant", TimeMode.AT, 0)
    assert prove_atom(atom, ledger, LedgerIndex(ledger), REGISTRY).value is Truth.UNKNOWN


def test_no_context_is_explicit_unresolved_not_empty_safe_world():
    output = analyze(AnalysisInput("", call()), Backend(), enable_t2=False)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.diagnostics.primary_reason is Reason.POLICY_NO_INTERPRETATION


def test_competition_mapping_keeps_unresolved_and_fallback_visible():
    output = analyze(input_case(), Backend(), enable_t2=False, adapter_mode=AdapterMode.COMPETITION)
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.product_decision.binary_label == 0
    assert output.product_decision.used_fallback


@pytest.mark.parametrize("encoded_literal,source", [
    ('"Q-1"', "Q-10"), ('"/a"', "/a/b"), ('"owner"', "coowner"),
    ("4", "42"), ("true", "untrue")])
def test_literal_prefix_is_not_exact_source_identity(encoded_literal, source):
    assert not literal_grounded(encoded_literal, (source,))


def test_escalation_cannot_rewrite_operational_scope_to_obtain_desired_answer():
    output = analyze(input_case(), Backend(), enable_t2=False)
    old = EscalationState(output.problem, output.ledger, REGISTRY, output.context, output.result)
    choice = output.context.operational_choices[0]
    changed = replace(choice, atoms=(replace(choice.atoms[0], predicate="send"),))
    with pytest.raises(ValueError, match="operational binding"):
        check_monotonic_update(old, replace(old, context=replace(old.context, operational_choices=(changed,))))
    with pytest.raises(ValueError, match="normative scope"):
        check_monotonic_update(old, replace(old, context=replace(old.context, scopes_json=((choice.parent_hypothesis_id, "{}"),))))


def test_bounded_escalation_integrated_only_after_unresolved():
    called = []
    def reparse(state):
        called.append(state.result.status)
        return None
    output = analyze(input_case(), Backend(), enable_t2=False,
        escalation_callbacks={EscalationStep.NARROW_REPARSE: reparse}, max_escalation_steps=1)
    assert called == [CoreStatus.UNRESOLVED]
    assert output.result.diagnostics.attempted_escalations == ("NARROW_REPARSE",)
    assert output.terminal_unresolved
    called.clear()
    error = analyze(input_case(response=call("send")), Backend(), enable_t2=False,
        escalation_callbacks={EscalationStep.NARROW_REPARSE: reparse}, max_escalation_steps=1)
    assert error.result.status is CoreStatus.PROVED_ERROR
    assert called == []


def test_policy_candidates_challenger_and_operational_binding_share_core():
    policy_text = "Never call read."
    class PolicyBackend(Backend):
        def propose(self, task, payload, schema):
            if task in {"policy_behavioral_hypotheses", "policy_missing_interpretation_challenger"}:
                self.tasks.append(task)
                item = {"behavioral_relation": "PROHIBITION", "actor": "assistant",
                    "action_or_state": "call read", "resource": "*", "conditions": [], "exceptions": [],
                    "source_quotes": [policy_text], "unresolved_terms": []}
                return Proposal(encoded({"interpretations": [item] if task == "policy_behavioral_hypotheses" else [],
                    "unresolved_terms": []}), "SUCCESS", "VALID")
            return super().propose(task, payload, schema)
    backend = PolicyBackend()
    output = analyze(AnalysisInput("", call(), policy=policy_text, tool_schemas=({"name": "read"},)),
        backend, enable_t2=False)
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert output.result.certificate_check.valid
    assert backend.tasks == ["policy_behavioral_hypotheses", "policy_missing_interpretation_challenger",
                             "operational_action_binding"]
    assert output.policy.coverage.status.value == "EMPIRICALLY_COVERED"


def test_untrusted_t2_alternatives_are_retained_but_never_make_observed_state():
    class T2Backend(Backend):
        def propose(self, task, payload, schema):
            if task == "tool_conditional_effect_hypotheses":
                self.tasks.append(task)
                return Proposal(encoded({"hypotheses": [
                    {"argument_entity_field": "record_id", "predicate": "archived",
                     "value_json": "true", "result_grounding_fields": ["status"]},
                    {"argument_entity_field": "record_id", "predicate": "queued",
                     "value_json": "true", "result_grounding_fields": ["status"]}]}), "SUCCESS", "VALID")
            return super().propose(task, payload, schema)
    prompt = '⟦ASSISTANT_TOOL_CALL name="archive" call_id="a"⟧\n{"record_id":"Q-1"}\n'
    prompt += '⟦TOOL_RESULT name="archive" call_id="a" requestor="assistant"⟧\n{"status":"accepted"}'
    output = analyze(input_case(prompt=prompt, response=call("send")), T2Backend())
    assert len(output.ledger.effects) == 2
    assert all(effect.status.value == "POSSIBLE_EFFECT" and effect.contract_sha256 is None for effect in output.ledger.effects)
    assert output.world_count_required == 2
    assert all(obs.predicate not in {"archived", "queued"} for obs in output.ledger.observations)
    # Uncertainty about an unrelated business effect does not erase an explicit
    # wrong current invocation, but both admitted effect worlds must be checked.
    assert output.result.status is CoreStatus.PROVED_ERROR
    assert output.result.certificate_check.valid


def test_unknown_material_response_span_blocks_known_plan_violation():
    class FailedClaimsBackend(Backend):
        def propose(self, task, payload, schema):
            if task.startswith("claim_"):
                self.tasks.append(task)
                return Proposal(None, "ERROR", "NOT_EVALUATED", "safe_transport_failure")
            return super().propose(task, payload, schema)
    output = analyze(input_case(response="⟦ASSISTANT⟧\nI completed everything.\n" + call("send")),
        FailedClaimsBackend(), enable_t2=False)
    assert len(output.claim_graph.claims) == 1
    assert output.claim_graph.claims[0].disposition.value == "UNKNOWN_SEMANTICS"
    assert output.result.status is CoreStatus.UNRESOLVED
    assert output.result.diagnostics.blocked_claims == ("s0",)
    assert output.result.certificate is None
