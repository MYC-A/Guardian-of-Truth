from dataclasses import replace
import inspect

import pytest

from guardian_truth.vnext import goal_certificate_v2
from guardian_truth.vnext.goal_certificate_v2 import check_goal_certificate, checked_clause_value
from guardian_truth.vnext.goal_call_membership_v2 import GoalCallMembershipAtom
from guardian_truth.vnext.goal_native import GoalClause, GoalOperator, NativeGoalParse, NativeGoalReading, source_inventory
from guardian_truth.vnext.goal_proof_records_v2 import GoalBindingChoice, GoalProofContext, GoalRoleBinding
from guardian_truth.vnext.goal_progress_v2 import PlanActivation, PlanProgressAtom, PlanProgressKind, prove_plan_progress
from guardian_truth.vnext.goal_solver_v2 import decide_goal_layer
from guardian_truth.vnext.integrity import canonical, digest
from guardian_truth.vnext.ledger import EvidenceLedger, LedgerIndex
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.proof_evidence import prove_atom
from guardian_truth.vnext.proof_records import ArgumentConstraint, AtomKind, ProofAtom, TimeMode
from guardian_truth.vnext.tools import ContractRegistry
from guardian_truth.vnext.types import CoreStatus, CoverageStatus, EntityRef, SemanticCoverage, ToolIdentity, Truth


REGISTRY = ContractRegistry(())


def fixture(path="/secret", *, predicates=("read",), complete=True, plan=()):
    goal, scope = "Read within the declared scope", {"path": ["/report", "/appendix"]}
    encoded_scope = canonical(scope).decode("utf-8")
    prompt = "⟦SYSTEM⟧\n" + goal
    args = {} if path is None else {"path": path}
    response = '⟦ASSISTANT_TOOL_CALL name="read" call_id="target"⟧\n' + canonical(args).decode("utf-8")
    metadata = (ToolIdentity("read"), ToolIdentity("write"))
    ledger = EvidenceLedger.from_events(normalize(prompt, response, tool_identities=metadata),
        history_complete=True, completeness_basis="complete supplied controlled prefix")
    target = next(event for event in ledger.events if event.kind == "call")
    entity = EntityRef("event_id", target.event_id, "ledger")
    text, sources = source_inventory(goal, plan, scope)
    clauses = tuple(GoalClause(f"r0:step:{i}", "r0", GoalOperator.PLAN_STEP, (f"plan:{i}",), (f"plan:{i}",))
                    for i in range(len(plan)))
    if not plan:
        clauses += (GoalClause("r0:goal:0", "r0", GoalOperator.REQUIRES, ("goal:0",), ("goal:0",)),)
    clauses += (GoalClause("r0:scope:0", "r0", GoalOperator.SCOPE, ("scope:0",), ("scope:0",)),
                GoalClause("r0:extra:0", "r0", GoalOperator.NO_EXTRA_CONSTRAINT, ("goal:0",), ()))
    reading = NativeGoalReading("r0", "scope applies to the proposed read interface", ("goal:0", "scope:0"),
        "goal:0", "assistant", 0 if plan else None, "plan:0" if plan else "goal:0", "CALL_ATTEMPTED", ("scope:0",),
        "SCOPE_EXPANSION", clauses, ())
    parsed = NativeGoalParse(text, sources, (reading,), SemanticCoverage(CoverageStatus.EMPIRICALLY_COVERED, None, False), ())
    choices = []
    for index, predicate in enumerate(predicates):
        applicability = ProofAtom(f"guard:{index}", AtomKind.TARGET_CALL_MATCH, entity, predicate, "true", "assistant",
                                  TimeMode.AT, target.index, target.call_id)
        compliance = replace(applicability, atom_id=f"scope:{index}",
            argument_constraints=(ArgumentConstraint(("path",), ('"/report"', '"/appendix"')),))
        bindings = (GoalRoleBinding("scope:0", "scope_applicable", applicability, ("scope:0",)),
                    GoalRoleBinding("scope:0", "scope_compliant", compliance, ("scope:0",)))
        if not plan:
            bindings += (GoalRoleBinding("goal:0", "proposition", GoalCallMembershipAtom(f"goal:{index}", "goal:0",
                entity, "assistant", target.index, target.call_id, ("read",)), ("goal:0",)),)
        choices.append(GoalBindingChoice(f"binding:{index}", "r0", bindings))
    context = GoalProofContext(goal, plan, encoded_scope, prompt, response, metadata, parsed, tuple(choices),
                               "frozen supplied empirical meaning choices; not NL completeness", complete)
    return context, ledger


def proved():
    context, ledger = fixture()
    decision = decide_goal_layer(context, ledger, REGISTRY)
    assert decision.status is CoreStatus.PROVED_ERROR and decision.certificate_valid is True
    return context, ledger, decision.certificate


def test_exact_scope_violation_has_independently_valid_conditional_witness():
    context, ledger, certificate = proved()
    assert check_goal_certificate(certificate, context, ledger, REGISTRY).valid
    assert certificate.world_proofs[0].primitives[1].refutes
    assert any(key == "VERDICT_SCOPE" and "Goal-layer" in value for key, value in certificate.assumptions)


@pytest.mark.parametrize("path", ["/report", "/appendix"])
def test_scope_compliance_is_not_upgraded_to_complete_core_safety(path):
    context, ledger = fixture(path)
    decision = decide_goal_layer(context, ledger, REGISTRY)
    assert decision.status is CoreStatus.UNRESOLVED and decision.certificate is None
    assert decision.world_proofs[0].error_value is Truth.FALSE


def test_material_missing_argument_is_unknown_not_absence_or_violation():
    context, ledger = fixture(None)
    decision = decide_goal_layer(context, ledger, REGISTRY)
    assert decision.status is CoreStatus.UNRESOLVED
    assert decision.world_proofs[0].error_value is Truth.UNKNOWN


def test_all_binding_alternatives_are_retained_and_disagreement_is_unresolved():
    context, ledger = fixture(predicates=("read", "write"))
    decision = decide_goal_layer(context, ledger, REGISTRY)
    assert len(decision.world_proofs) == 2
    assert {world.error_value for world in decision.world_proofs} == {Truth.TRUE, Truth.FALSE}
    assert decision.status is CoreStatus.UNRESOLVED


def test_all_error_binding_worlds_are_checked_not_majority_voted():
    context, ledger = fixture(predicates=("read", "read"))
    decision = decide_goal_layer(context, ledger, REGISTRY)
    assert decision.status is CoreStatus.PROVED_ERROR and len(decision.certificate.world_proofs) == 2


def test_checker_rejects_dropped_binding_world_and_changed_witness_truth():
    context, ledger = fixture(predicates=("read", "read"))
    certificate = decide_goal_layer(context, ledger, REGISTRY).certificate
    bad = replace(certificate, world_proofs=certificate.world_proofs[:1])
    assert "BINDING_WORLD_DROPPED_OR_DUPLICATED" in check_goal_certificate(bad, context, ledger, REGISTRY).errors
    world = certificate.world_proofs[0]
    changed = replace(world.primitives[1], value=Truth.TRUE, refutes=())
    bad = replace(certificate, world_proofs=(replace(world, primitives=(world.primitives[0], changed)), certificate.world_proofs[1]))
    assert "PRIMITIVE_PROOF_RECHECK_FAILED" in check_goal_certificate(bad, context, ledger, REGISTRY).errors


def test_checker_rejects_modified_formula_result_and_safety_certificate_kind():
    context, ledger, certificate = proved()
    bad = replace(certificate, world_proofs=(replace(certificate.world_proofs[0], clause_safety=()),))
    assert "FORMULA_OR_AGGREGATION_RECHECK_FAILED" in check_goal_certificate(bad, context, ledger, REGISTRY).errors
    assert not check_goal_certificate(replace(certificate, status=CoreStatus.PROVED_NO_ERROR), context, ledger, REGISTRY).valid


def test_checker_rejects_allowed_value_subset_even_with_rehashed_context():
    context, ledger = fixture()
    choice = context.choices[0]
    bad_binding = replace(choice.bindings[1], atom=replace(choice.bindings[1].atom,
        argument_constraints=(ArgumentConstraint(("path",), ('"/report"',)),)))
    changed = replace(context, choices=(replace(choice, bindings=(choice.bindings[0], bad_binding)),))
    result = decide_goal_layer(changed, ledger, REGISTRY)
    assert result.status is CoreStatus.UNRESOLVED
    assert "LITERAL_SCOPE_BINDING_MISMATCH" in result.certificate_errors


def test_source_offsets_and_structural_scope_cannot_be_forged():
    context, ledger = fixture()
    changed = replace(context, parsed=replace(context.parsed, source_text="invented"))
    assert "GOAL_SOURCE_RECONSTRUCTION_FAILED" in decide_goal_layer(changed, ledger, REGISTRY).certificate_errors
    reading = context.parsed.readings[0]
    changed = replace(context, parsed=replace(context.parsed, readings=(replace(reading, clauses=reading.clauses[1:]),)))
    assert "PLAN_ORDER_OR_SCOPE_CLAUSES_DROPPED_OR_CHANGED" in decide_goal_layer(changed, ledger, REGISTRY).certificate_errors


def test_unknown_plan_progress_is_not_masked_by_known_scope_violation():
    context, ledger = fixture(plan=("Read report",))
    result = decide_goal_layer(context, ledger, REGISTRY)
    assert result.status is CoreStatus.UNRESOLVED
    assert result.world_proofs[0].error_value is Truth.UNKNOWN


def test_llm_active_step_cannot_be_bound_to_a_call_attempt_as_a_progress_fact():
    context, ledger = fixture(plan=("Read report",))
    choice = context.choices[0]
    fake_progress = GoalRoleBinding("plan:0", "active_step", choice.bindings[0].atom, ("plan:0",))
    changed = replace(context, choices=(replace(choice, bindings=choice.bindings + (fake_progress,)),))
    result = decide_goal_layer(changed, ledger, REGISTRY)
    assert "PLAN_PROGRESS_NOT_ESTABLISHED" in result.certificate_errors


def test_incomplete_candidates_and_budget_overflow_do_not_get_top_k_proof():
    context, ledger = fixture(complete=False)
    assert decide_goal_layer(context, ledger, REGISTRY).status is CoreStatus.UNRESOLVED
    context, ledger = fixture(predicates=("read", "read"))
    result = decide_goal_layer(context, ledger, REGISTRY, max_worlds=1)
    assert result.status is CoreStatus.UNRESOLVED and not result.world_proofs
    assert "WORLD_BUDGET_EXCEEDED" in result.certificate_errors


def test_checker_does_not_import_solver_compiler_or_formula_evaluator():
    source = inspect.getsource(goal_certificate_v2)
    assert "from .goal_solver" not in source
    assert "from .goal_formula" not in source


@pytest.mark.parametrize("operator", [GoalOperator.IF, GoalOperator.ONLY_IF, GoalOperator.UNLESS])
def test_independent_checker_matches_compiler_on_actual_primitive_bindings(operator):
    from guardian_truth.vnext.goal_formula import compile_goal_clause, evaluate_compiled_clause
    context, ledger = fixture()
    first, second = context.choices[0].bindings[:2]
    bindings = {("goal:0", "proposition"): replace(first, source_id="goal:0"),
                ("scope:0", "proposition"): second}
    primitives = {binding.atom.atom_id: prove_atom(binding.atom, ledger, LedgerIndex(ledger), REGISTRY)
                  for binding in bindings.values()}
    clause = GoalClause("c", "r0", operator, ("goal:0",), ("goal:0", "scope:0"))
    compiled = compile_goal_clause(clause, {key: value.atom for key, value in bindings.items()})
    assert checked_clause_value(clause, bindings, primitives) is evaluate_compiled_clause(compiled, lambda atom: primitives[atom.atom_id].value)


def fresh_fixture():
    context, _ = fixture("/report", plan=("Read report",))
    prompt = context.prompt + "\nDECLARED_PLAN: Read report"
    response = context.response.replace('name="read"', 'name="write"')
    ledger = EvidenceLedger.from_events(normalize(prompt, response, tool_identities=context.tool_metadata),
        history_complete=True, completeness_basis="source protocol: fresh plan and complete prefix")
    activation_event = next(event for event in ledger.events if event.actor == "system")
    target = next(event for event in ledger.events if event.kind == "call")
    context = replace(context, prompt=prompt, response=response,
        plan_activation=PlanActivation(activation_event.index, "SOURCE_PROTOCOL_FRESH_PLAN", ledger.completeness_basis))
    progress = PlanProgressAtom("progress:0", "plan:0", 0, target.index)
    satisfied = ProofAtom("step:0", AtomKind.TARGET_CALL_MATCH, EntityRef("event_id", target.event_id, "ledger"),
        "read", "true", "assistant", TimeMode.AT, target.index, target.call_id)
    scope_bindings = tuple(replace(binding, atom=replace(binding.atom, entity=satisfied.entity,
        time_index=target.index, call_id=target.call_id)) for binding in context.choices[0].bindings)
    bindings = scope_bindings + (GoalRoleBinding("plan:0", "active_step", progress, ("plan:0",)),
                                GoalRoleBinding("plan:0", "step_satisfied", satisfied, ("plan:0",)))
    return replace(context, choices=(replace(context.choices[0], bindings=bindings),)), ledger


def test_fresh_source_protocol_proves_wrong_first_dispatch_without_inventing_effects():
    context, ledger = fresh_fixture()
    result = decide_goal_layer(context, ledger, REGISTRY)
    assert result.status is CoreStatus.PROVED_ERROR and result.certificate_valid is True
    assert not ledger.effects
    assert any(item.atom.atom_id == "progress:0" and item.value is Truth.TRUE for item in result.world_proofs[0].primitives)
    assert check_goal_certificate(result.certificate, context, ledger, REGISTRY).valid


@pytest.mark.parametrize("change", ["no_activation", "incomplete_history", "wrong_basis", "missing_plan_source", "intervening_event"])
def test_fresh_progress_requires_actual_source_contract_and_complete_empty_prefix(change):
    context, ledger = fresh_fixture()
    if change == "no_activation":
        context = replace(context, plan_activation=None)
    elif change == "incomplete_history":
        ledger = replace(ledger, history_complete=False, completeness_basis=None)
    elif change == "wrong_basis":
        context = replace(context, plan_activation=replace(context.plan_activation, source_completeness_basis="unrelated prefix"))
    else:
        prompt = context.prompt.replace("DECLARED_PLAN: Read report", "missing plan") if change == "missing_plan_source" else context.prompt + "\n⟦USER⟧\nI already read it."
        ledger = EvidenceLedger.from_events(normalize(prompt, context.response, tool_identities=context.tool_metadata),
            history_complete=True, completeness_basis=ledger.completeness_basis)
        context = replace(context, prompt=prompt)
    progress = next(binding.atom for binding in context.choices[0].bindings if binding.role == "active_step")
    if change == "intervening_event":
        progress = replace(progress, before_index=next(event.index for event in ledger.events if event.kind == "call"))
    assert prove_plan_progress(progress, context, ledger).value is Truth.UNKNOWN


def test_schema_or_model_cannot_declare_itself_a_fresh_plan_authority():
    with pytest.raises(ValueError):
        PlanActivation(0, "LLM_CONFIDENCE", "complete")


def test_first_step_proof_is_not_a_general_later_progress_inference():
    context, ledger = fresh_fixture()
    progress = PlanProgressAtom("later", "plan:missing", 1, len(ledger.events) - 1)
    assert prove_plan_progress(progress, context, ledger).value is Truth.UNKNOWN


def test_fresh_plan_bounded_noncompletion_is_not_retrieval_miss_or_global_absence():
    context, ledger = fresh_fixture()
    atom = PlanProgressAtom("uncompleted", "plan:0", 0, len(ledger.events) - 1, PlanProgressKind.COMPLETED_STEP)
    proof = prove_plan_progress(atom, context, ledger)
    assert proof.value is Truth.FALSE and proof.refutes
    assert prove_plan_progress(atom, replace(context, plan_activation=None), ledger).value is Truth.UNKNOWN


def test_skipped_step_is_proved_with_all_steps_and_order_preserved():
    context, ledger = fresh_fixture()
    goal, plan = context.declared_goal, ("Read report", "Send report")
    text, sources = source_inventory(goal, plan, {"path": ["/report", "/appendix"]})
    prompt = context.prompt + "\nSend report"
    response = context.response.replace('name="write"', 'name="send"')
    metadata = context.tool_metadata + (ToolIdentity("send"),)
    ledger = EvidenceLedger.from_events(normalize(prompt, response, tool_identities=metadata),
        history_complete=True, completeness_basis=ledger.completeness_basis)
    target = next(event for event in ledger.events if event.kind == "call")
    entity = EntityRef("event_id", target.event_id, "ledger")
    reading = context.parsed.readings[0]
    clauses = tuple(GoalClause(f"r0:step:{i}", "r0", GoalOperator.PLAN_STEP, (f"plan:{i}",), (f"plan:{i}",)) for i in range(2))
    clauses += (GoalClause("r0:order:0", "r0", GoalOperator.BEFORE, ("plan:0", "plan:1"), ("plan:0", "plan:1")),) + reading.clauses[1:]
    reading = replace(reading, clauses=clauses)
    parsed = replace(context.parsed, source_text=text, sources=sources, readings=(reading,))
    bindings = []
    for i, name in enumerate(("read", "send")):
        source = f"plan:{i}"
        satisfied = ProofAtom(f"satisfied:{i}", AtomKind.TARGET_CALL_MATCH, entity, name, "true", "assistant",
            TimeMode.AT, target.index, target.call_id)
        bindings += [GoalRoleBinding(source, "active_step", PlanProgressAtom(f"active:{i}", source, i, target.index), (source,)),
            GoalRoleBinding(source, "step_satisfied", satisfied, (source,))]
        if i == 0:
            bindings.append(GoalRoleBinding(source, "prior_completion", PlanProgressAtom("completed:0", source, i,
                target.index, PlanProgressKind.COMPLETED_STEP), (source,)))
        else:
            bindings.append(GoalRoleBinding(source, "current_attempt", replace(satisfied, atom_id="attempt:1"), (source,)))
    bindings += [replace(binding, atom=replace(binding.atom, entity=entity, time_index=target.index, call_id=target.call_id))
                 for binding in context.choices[0].bindings if binding.source_id == "scope:0"]
    context = replace(context, prompt=prompt, response=response, ordered_plan=plan, tool_metadata=metadata, parsed=parsed,
        choices=(GoalBindingChoice("all-step-choice", "r0", tuple(bindings)),))
    result = decide_goal_layer(context, ledger, REGISTRY)
    assert result.status is CoreStatus.PROVED_ERROR and result.certificate_valid
    assert dict(result.world_proofs[0].clause_safety)["r0:order:0"] is Truth.FALSE
    assert check_goal_certificate(result.certificate, context, ledger, REGISTRY).valid
