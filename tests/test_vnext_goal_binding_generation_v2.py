from dataclasses import asdict, replace
import json

import pytest

from guardian_truth.vnext.goal_bindings_v2 import argument_path_inventory, generate_goal_bindings
from guardian_truth.vnext.goal_call_membership_v2 import GoalCallMembershipAtom, prove_call_membership
from guardian_truth.vnext.goal_certificate_v2 import check_goal_certificate
from guardian_truth.vnext.goal_invocation_v2 import GoalInvocationInput, analyze_goal_invocation
from guardian_truth.vnext.goal_progress_v2 import PlanActivation
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.ledger import EvidenceLedger
from guardian_truth.vnext.normalize import normalize
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.tools import ContractRegistry
from guardian_truth.vnext.types import CoreStatus, EntityRef, Reason, ToolIdentity, Truth


GOAL = "Read report and then send it"
PLAN = ("Read report", "Send report")
SCOPE = {"path": ["/report", "/appendix"], "recipient": ["owner"]}
SCHEMAS = ({"name": "read", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}},
           {"name": "send", "parameters": {"type": "object", "properties": {"recipient": {"type": "string"}}}},
           {"name": "download", "parameters": {"type": "object", "properties": {"path": {"type": "string"}}}})


def source(name="send", args=None, *, activation=True):
    prompt = "⟦SYSTEM⟧\n" + GOAL + "\n" + "\n".join(PLAN)
    response = f'⟦ASSISTANT_TOOL_CALL name="{name}" call_id="target"⟧\n' + canonical(args if args is not None else {"recipient": "owner"}).decode("utf-8")
    basis = "explicit source protocol: plan starts fresh at this SYSTEM event and prefix is complete"
    return GoalInvocationInput(prompt, response, GOAL, PLAN, SCOPE, tool_schemas=SCHEMAS,
        history_complete=True, completeness_basis=basis,
        plan_activation=PlanActivation(0, "SOURCE_PROTOCOL_FRESH_PLAN", basis) if activation else None)


class Backend:
    def __init__(self, *, alternatives=False, multi_tools=False, failure=None, unknown_mode=False,
                 extra_constraint=False, bad_tool=False, duplicate_reading=False, ungrounded=False):
        self.alternatives, self.multi_tools, self.failure = alternatives, multi_tools, failure
        self.unknown_mode, self.extra_constraint = unknown_mode, extra_constraint
        self.bad_tool, self.duplicate_reading, self.ungrounded = bad_tool, duplicate_reading, ungrounded
        self.tasks = []

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        if task == self.failure:
            return Proposal(None, "ERROR", "NOT_EVALUATED", "timeout")
        if task == "goal_v2_reading_inventory":
            value = {"readings": [{"reading_id": "r0", "basis": "ordered declared plan", "source_ids": ["goal:0"]}]}
        elif task.startswith("goal_v2_action_binding:") or task.startswith("goal_v2_scope_binding:"):
            sid = payload["binding_source"]["source_id"]
            meanings = ["goal:0"] if self.ungrounded else [sid]
            candidate = {"meaning_source_ids": meanings, "unresolved_terms": []}
            if task.startswith("goal_v2_action_binding:"):
                tools = ["read", "download"] if self.multi_tools else ["read"]
                candidate.update(allowed_tools=tools if sid in {"plan:0", "goal:0"} else ["send"],
                                 mode="UNKNOWN" if self.unknown_mode else "CURRENT_GOAL_CONFORMANCE" if sid == "goal:0" else "TARGET_INVOCATION")
                if self.bad_tool:
                    candidate["allowed_tools"] = ["invented-guaranteed-effect-tool"]
            else:
                key = payload["binding_source"]["scope_key"]
                path_id = next((key_id for key_id, path in payload["target_invocation"]["argument_paths"].items() if path == [key]), None)
                candidate.update(applicable_tools=["read", "download"] if key == "path" else ["send"], argument_path_id=path_id)
            candidates = [candidate]
            if self.alternatives:
                alternative = dict(candidate)
                if "allowed_tools" in alternative:
                    alternative["allowed_tools"] = ["send"] if sid == "plan:0" else ["read"]
                else:
                    alternative["applicable_tools"] = ["send", "read", "download"]
                candidates.append(alternative)
            value = {"readings": [{"reading_id": "r0", "candidates": candidates}]}
            if self.duplicate_reading:
                value["readings"] *= 2
        else:
            field = task.removeprefix("goal_v2_")
            clauses = [{"operator": "NO_EXTRA_CONSTRAINT", "source_ids": ["goal:0"], "operands": [], "unresolved_terms": []}]
            if self.extra_constraint:
                clauses = [{"operator": "IF", "source_ids": ["goal:0"], "operands": ["goal:0", "plan:0"], "unresolved_terms": []}]
            defaults = {"declared_goal_source": "goal:0", "actor": "assistant", "expected_step": 0,
                "expected_action_source": "plan:0", "target_action_kind": "CALL_ATTEMPTED", "allowed_scope_sources": ["scope:0", "scope:1"],
                "drift_type": "SKIPPED_STEP", "extra_constraints": clauses}
            if not any(source["kind"] == "PLAN_STEP" for source in payload.get("declared_sources", [])):
                defaults.update(expected_step=None, expected_action_source="goal:0")
            value = {"readings": [{"reading_id": "r0", "clauses" if field == "extra_constraints" else field: defaults[field]}]}
        return Proposal(json.dumps(value), "SUCCESS", "VALID")


def test_narrow_tasks_reach_a_checked_skipped_step_witness_from_original_input():
    backend = Backend()
    analysis = analyze_goal_invocation(source(), backend)
    assert analysis.decision.status is CoreStatus.PROVED_ERROR and analysis.decision.certificate_valid
    assert len(backend.tasks) == 13  # nine frontend, two step, two scope tasks
    assert not analysis.ledger.effects
    assert check_goal_certificate(analysis.decision.certificate, analysis.context, analysis.ledger, ContractRegistry(())).valid
    assert len(analysis.parsed.readings[0].clauses) == 6  # 2 steps, order, 2 scopes, no-extra


def test_wrapped_function_schemas_preserve_interface_paths_and_checked_worlds():
    data = source()
    wrapped = tuple({'type': 'function', 'function': schema} for schema in SCHEMAS)
    result = analyze_goal_invocation(replace(data, tool_schemas=wrapped), Backend())
    assert result.decision.status is CoreStatus.PROVED_ERROR
    assert result.decision.certificate_valid
    assert argument_path_inventory(wrapped, {}) == argument_path_inventory(SCHEMAS, {})
    assert all(identity.provider is None and identity.version is None for identity in result.context.tool_metadata)
    assert not result.ledger.effects


@pytest.mark.parametrize('schema', [None, {}, {'type': 'function'},
    {'type': 'function', 'function': {'name': 'read'}, 'name': 'send'}])
def test_malformed_or_conflicting_wrappers_do_not_invent_an_interface(schema):
    from guardian_truth.vnext.goal_interfaces_v2 import declared_interface
    assert declared_interface(schema) is None


def test_native_stage_adapter_does_not_invent_fresh_plan_activation():
    from guardian_truth.vnext.stage_goal_native_v2 import predict_native_goal
    value = {'declared_goal': GOAL, 'declared_plan': list(PLAN), 'allowed_scope': SCOPE,
        'history': [], 'target_action': {'name': 'send', 'args': {'recipient': 'owner'}}}
    prediction = predict_native_goal(value, Backend())
    assert prediction['plan_activation'] is None
    assert prediction['context']['plan_activation'] is None
    assert prediction['decision']['status'] is CoreStatus.UNRESOLVED


def test_native_stage_scoring_excludes_only_failed_field_and_keeps_unknown_node():
    from guardian_truth.vnext.stage_goal_native_v2 import predict_native_goal, score_native_case, summarize_native_goal
    value = {'declared_goal': GOAL, 'declared_plan': list(PLAN), 'allowed_scope': SCOPE,
        'history': [], 'target_action': {'name': 'send', 'args': {'recipient': 'owner'}}}
    prediction = predict_native_goal(value, Backend(failure='goal_v2_expected_step'))
    case = {'case_id': 'controlled', 'family': 'skipped_step', 'input': value,
        'gold': {'expected_step': 0, 'expected_action': PLAN[0], 'drift': 'SKIPPED_STEP', 'verdict': 'PROVED_ERROR'}}
    score = score_native_case(case, prediction)
    assert score['fields']['expected_step']['eligible'] is False
    assert score['fields']['declared_goal_source']['eligible'] is True
    assert score['fields']['expected_step']['candidates'] == 1
    row = {'case_id': 'controlled', 'prediction': prediction, 'request_telemetry': [],
        'baseline_x0': {'binary_label': 0}}
    report = summarize_native_goal([case], [row])
    assert report['goal_layer']['unresolved_rate'] == 1
    assert report['goal_layer']['certificate_validation']['PROVED_ERROR']['rate'] is None
    assert report['whole_core_gain'] == 'NOT_ESTABLISHED_GOAL_SUBSYSTEM_ONLY'
    assert report['provider']['latency_ms_p50'] is None


def test_all_allowed_scope_values_are_code_owned_not_model_generated():
    analysis = analyze_goal_invocation(source("read", {"path": "/appendix"}), Backend())
    assert analysis.decision.status is CoreStatus.UNRESOLVED  # no NL safety closure
    scope_atoms = [binding.atom for binding in analysis.binding_candidates.choices[0].bindings if binding.role == "scope_compliant"]
    assert set(scope_atoms[0].argument_constraints[0].allowed_json) == {'"/report"', '"/appendix"'}
    assert dict(analysis.decision.world_proofs[0].clause_safety)["r0:scope:0"] is Truth.TRUE


def test_one_meaning_can_allow_multiple_tools_without_artificial_disagreement():
    analysis = analyze_goal_invocation(source("download", {"path": "/report"}), Backend(multi_tools=True))
    assert len(analysis.binding_candidates.choices) == 1
    assert dict(analysis.decision.world_proofs[0].clause_safety)["r0:step:0"] is Truth.TRUE
    assert analysis.decision.status is CoreStatus.UNRESOLVED


def test_cartesian_alternatives_are_all_retained_not_confidence_selected():
    analysis = analyze_goal_invocation(source("read", {"path": "/report"}), Backend(alternatives=True))
    assert analysis.binding_candidates.required_worlds == 16
    assert len(analysis.binding_candidates.choices) == 16 and len(analysis.decision.world_proofs) == 16
    assert analysis.decision.status is CoreStatus.UNRESOLVED


def test_world_budget_returns_no_top_k_substitute():
    analysis = analyze_goal_invocation(source(), Backend(alternatives=True), max_worlds=8)
    assert analysis.binding_candidates.required_worlds == 16
    assert not analysis.binding_candidates.choices and not analysis.decision.world_proofs
    assert analysis.decision.status is CoreStatus.UNRESOLVED


@pytest.mark.parametrize("task", ["goal_v2_action_binding:plan:0", "goal_v2_scope_binding:scope:0"])
def test_failed_narrow_component_preserves_placeholder_and_transport_reason(task):
    analysis = analyze_goal_invocation(source(), Backend(failure=task))
    assert analysis.decision.status is CoreStatus.UNRESOLVED
    assert len(analysis.binding_candidates.choices) == 1
    assert (task, Reason.TRANSPORT_ERROR) in analysis.binding_candidates.failures
    assert analysis.diagnostics.primary_reason is Reason.TRANSPORT_ERROR
    assert analysis.diagnostics.blocked_hypotheses == ("r0",)


@pytest.mark.parametrize("kwargs", [{"bad_tool": True}, {"duplicate_reading": True}, {"ungrounded": True}, {"unknown_mode": True}])
def test_bad_or_unbound_meaning_is_not_promoted_to_a_fact(kwargs):
    analysis = analyze_goal_invocation(source(), Backend(**kwargs))
    assert analysis.decision.status is CoreStatus.UNRESOLVED
    assert len(analysis.binding_candidates.choices) == 1
    assert not analysis.binding_candidates.candidate_enumeration_complete


def test_missing_activation_does_not_get_inferred_from_empty_history_or_llm_step_zero():
    analysis = analyze_goal_invocation(source(activation=False), Backend())
    assert analysis.decision.status is CoreStatus.UNRESOLVED
    assert all(binding.role not in {"active_step", "prior_completion"}
               for choice in analysis.binding_candidates.choices for binding in choice.bindings)


def test_unlowered_extra_condition_is_explicit_not_silently_removed():
    analysis = analyze_goal_invocation(source(), Backend(extra_constraint=True))
    assert analysis.decision.status is CoreStatus.UNRESOLVED
    assert "extra_proposition_binding_not_yet_lowered" in analysis.diagnostics.missing_evidence


def test_paths_are_deterministic_and_include_declared_fields_not_only_present_arguments():
    paths = argument_path_inventory(SCHEMAS, {"nested": {"value": 1}})
    assert set(paths.values()) == {("path",), ("recipient",), ("nested",), ("nested", "value")}
    assert paths == argument_path_inventory(SCHEMAS[::-1], {"nested": {"value": 2}})


def test_membership_is_only_a_source_invocation_not_completion_or_causality():
    data = source("read", {"path": "/report"})
    ledger = EvidenceLedger.from_events(normalize(data.prompt, data.response))
    target = next(event for event in ledger.events if event.kind == "call")
    atom = GoalCallMembershipAtom("a", "plan:0", EntityRef("event_id", target.event_id, "ledger"),
        "assistant", target.index, target.call_id, ("read", "download"))
    assert prove_call_membership(atom, ledger).value is Truth.TRUE
    assert not ledger.effects
    assert prove_call_membership(replace(atom, actor="user"), ledger).value is Truth.UNKNOWN


def test_per_name_version_ambiguity_is_not_last_wins_t1_transfer():
    data = replace(source(), tool_metadata=(ToolIdentity("read", version="v1"), ToolIdentity("read", version="v2")))
    with pytest.raises(ValueError, match="ambiguous per-name"):
        analyze_goal_invocation(data, Backend())


def test_unresolved_diagnostics_keep_all_six_core_field_names():
    analysis = analyze_goal_invocation(source(activation=False), Backend())
    assert set(asdict(analysis.diagnostics)) == {"primary_reason", "contributing_reasons", "blocked_claims",
        "blocked_hypotheses", "missing_evidence", "attempted_escalations"}


def test_goal_without_plan_is_not_an_empty_completed_plan_and_keeps_goal_constraint():
    data = replace(source("send"), ordered_plan=(), plan_activation=None)
    analysis = analyze_goal_invocation(data, Backend())
    reading = analysis.parsed.readings[0]
    assert reading.expected_step is None and reading.expected_action_source == "goal:0"
    assert analysis.parsed.expected_action(reading) == GOAL
    assert any(clause.clause_id == "r0:goal:0" for clause in reading.clauses)
    assert analysis.decision.status is CoreStatus.PROVED_ERROR and analysis.decision.certificate_valid


def test_goal_workflow_without_plan_can_permit_a_preparatory_interface_in_one_meaning():
    data = replace(source("download", {"path": "/report"}), ordered_plan=(), plan_activation=None)
    analysis = analyze_goal_invocation(data, Backend(multi_tools=True))
    assert len(analysis.binding_candidates.choices) == 1
    assert dict(analysis.decision.world_proofs[0].clause_safety)["r0:goal:0"] is Truth.TRUE
    assert analysis.decision.status is CoreStatus.UNRESOLVED
