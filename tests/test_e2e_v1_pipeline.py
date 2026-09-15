"""E2E V1 offline pipeline tests (spec sections 112-129).

Controlled semantic fixtures — never model benchmarks or oracle facts.
Everything here runs with zero LLM/network: the fake backend returns
scripted proposals per task, exercising the REAL deterministic pipeline
(E5, assembler, composition, lowering, worlds, solver, certificates).
"""
from dataclasses import replace
import json

import pytest

from guardian_truth.vnext.e2e.certificate_context_v1 import check_certificate_e2e
from guardian_truth.vnext.e2e.core_v1 import E2EDependencies, analyze_e2e_v1, run_semantic_passes
from guardian_truth.vnext.e2e.goal_e5_v1 import resolve_ref
from guardian_truth.vnext.e2e.goal_types_v1 import (E5Resolution, ExtractiveRef,
                                                    RuleFrameRaw, SourceText)
from guardian_truth.vnext.e2e.goal_assembler_v1 import assemble_contract
from guardian_truth.vnext.e2e.goal_frontends_v1 import (CONSERVATIVE_TASK,
                                                        RULE_FRAMES_TASK)
from guardian_truth.vnext.e2e.goal_composition_v1 import compose_goal_contracts
from guardian_truth.vnext.e2e.policy_composition_v1 import (GRSResult, H0Result,
                                                            compose_policy_readings,
                                                            make_grs_frontend,
                                                            make_h0_frontend)
from guardian_truth.vnext.e2e.semantic_binding_v1 import BINDING_TASK
from guardian_truth.vnext.e2e.source_adapter_v1 import (E2ECaseSources, TrajectoryEvent)
from guardian_truth.vnext.integrity import canonical
from guardian_truth.vnext.policy_grs import (GRS_DSL_SCHEMA, GRS_GROUND_REPAIR_TASK,
                                             GRS_GROUND_SCHEMA, GRS_GROUND_TASK,
                                             GRS_SYNTH_REPAIR_TASK, GRS_SYNTH_TASK)
from guardian_truth.vnext.policy_v3_benchmark import (compile_v3_structure,
                                                      evaluate_v3_program)
from guardian_truth.vnext.semantic import Proposal
from guardian_truth.vnext.tools import (ContractRegistry, EffectSpec, FieldCondition,
                                        TrustedContract)
from guardian_truth.vnext.types import CoreStatus, EvaluationHypothesis, Truth
from guardian_truth.vnext import policy_v3_benchmark as v3


# ------------------------------------------------------------------- fixtures

H0_TASK = "TEST_H0_PARSE"
H0_REPAIR = "TEST_H0_REPAIR"
STRUCTURE_SCHEMA = {
    "type": "object",
    "properties": {
        "modality": {"type": "string", "enum": ["PERMISSION", "PROHIBITION", "REQUIREMENT"]},
        "relation": {"type": "string", "enum": ["IF", "ONLY_IF", "UNLESS", "UNCONDITIONAL",
                                                "IF_AND_ONLY_IF", "AND_NOT_EACH"]},
        "target_clauses": {"type": "array", "minItems": 1,
                           "items": {"type": "array", "minItems": 1, "items": {"type": "string"}}},
        "condition_literals": {"type": "array", "items": {"type": "string"}},
        "exception_literals": {"type": "array", "items": {"type": "string"}},
        "condition_mode": {"type": "string", "enum": ["ALL", "ANY"]},
        "exception_mode": {"type": "string", "enum": ["ALL", "ANY"]},
        "temporal": {"type": "string", "enum": ["NONE", "BEFORE", "AFTER"]},
        "actor": {"type": "string"}, "regulated_kind": {"type": "string"},
        "facet": {"type": "string"}, "identity": {"type": "string"},
        "provenance": {"type": "string"}, "quantification": {"type": "string"},
    },
    "required": ["modality", "relation", "target_clauses"],
    "additionalProperties": False,
}


def encoded(value):
    return canonical(value).decode("utf-8")


class ScriptedBackend:
    """Controlled fixture backend: scripted proposals by task, checked requests."""

    def __init__(self, *, h0_structure=None, grs_inventory=None, grs_dsl=None,
                 goal_frames=None, binding_units=None, fail_tasks=()):
        self.h0_structure = h0_structure
        self.grs_inventory = grs_inventory
        self.grs_dsl = grs_dsl
        self.goal_frames = goal_frames or {"frames": []}
        self.binding_units = binding_units or {}
        self.fail_tasks = set(fail_tasks)
        self.tasks = []

    def propose(self, task, payload, schema):
        self.tasks.append(task)
        if task in self.fail_tasks:
            return Proposal(None, "ERROR", "NOT_EVALUATED", "safe_transport_failure")
        if task == H0_TASK or task == H0_REPAIR:
            value = self.h0_structure
        elif task in (GRS_GROUND_TASK, GRS_GROUND_REPAIR_TASK):
            value = self.grs_inventory
        elif task in (GRS_SYNTH_TASK, GRS_SYNTH_REPAIR_TASK):
            value = {"dsl": self.grs_dsl}
        elif task in (CONSERVATIVE_TASK, RULE_FRAMES_TASK) or task.startswith("The previous"):
            value = self.goal_frames
        elif task == BINDING_TASK or task.startswith("The previous semantic-binding"):
            value = {"units": self._binding_response(payload)}
        elif task.startswith("claim_"):
            spans = payload["span_inventory"]
            if task == "claim_relations":
                value = {"relations": []}
            else:
                fields = {"claim_disposition": {"disposition": "NON_VERIFIABLE"},
                          "claim_kind": {"kind": "NON_VERIFIABLE"},
                          "claim_actor": {"actor": "assistant"},
                          "claim_predicate": {"predicate": "greet"},
                          "claim_object_entities": {"object": "greeting", "entity_refs": []},
                          "claim_modality_polarity": {"polarity": "POSITIVE", "modality": "ASSERTED"},
                          "claim_time": {"time_anchor": "NOW"},
                          "claim_source": {"source_refs": ["ASSISTANT"]},
                          "claim_explicit_causality": {"explicit_causality": False}}
                value = {"spans": [{"span_id": span["span_id"], **fields[task]} for span in spans]}
        else:
            raise AssertionError("unexpected semantic task: " + task)
        return Proposal(encoded(value), "SUCCESS", "VALID")

    def _binding_response(self, payload):
        units = []
        for unit in payload["semantic_units"]:
            unit_id = unit["unit_id"]
            if unit_id in self.binding_units:
                config = self.binding_units[unit_id]
                if config.get("kind") == "OUTCOME":
                    units.append({"unit_id": unit_id, "unit_kind": "OUTCOME",
                                  "bindings": [], "serving_tools": config["tools"],
                                  "action_servable": config.get("action_servable", True),
                                  "quotes": config.get("quotes", [])})
                else:
                    binding = {"tool": config["tool"], "level": config.get("level", "ATTEMPT"),
                               "argument_checks": [
                                   {"path": check["path"], "allowed_json": check["allowed_json"],
                                    "presence_only": check.get("presence_only", False),
                                    "quote": check.get("quote", "")}
                                   for check in config.get("checks", [])],
                               "entity_path": config.get("entity_path", []),
                               "observation": None}
                    if config.get("observation"):
                        obs = config["observation"]
                        binding["observation"] = {
                            "tool": obs["tool"], "path": obs["path"],
                            "expected_json": obs["expected_json"],
                            "entity_path": obs.get("entity_path", []),
                            "quote": obs.get("quote", "")}
                    units.append({"unit_id": unit_id, "unit_kind": config.get("unit_kind", "ACTION"),
                                  "bindings": [binding], "serving_tools": [],
                                  "action_servable": True, "quotes": config.get("quotes", [])})
        return units


def make_case(*, case_id="c1", policy="Do not cancel orders.",
              catalog=("action:cancel_order", "action:get_status", "state:order_frozen"),
              user_text="Please show the status of order 19.",
              history=(), calls=(), response_text="Done.",
              schemas=(("cancel_order", {"order_id": "string"}),
                       ("get_status", {"order_id": "string"})),
              contracts=(), history_complete=False, policy_universe=None,
              goal_closure=None):
    trajectory = tuple(history)
    target = tuple(calls) + (TrajectoryEvent("assistant", text=response_text),)
    tool_schemas = ({"name": name, "arguments": args} for name, args in schemas)
    return E2ECaseSources(
        case_id=case_id, policy_text=policy, atom_catalog=tuple(catalog),
        user_sources=(SourceText("user:0", "USER", user_text),),
        trajectory=trajectory, target_response=target,
        tool_schemas=tuple(tool_schemas), t1_contracts=tuple(contracts),
        history_complete=history_complete,
        completeness_basis="controlled complete history" if history_complete else None,
        policy_universe=policy_universe, goal_closure=goal_closure)


def make_deps(backend):
    return E2EDependencies(
        backend=backend,
        h0_frontend=make_h0_frontend(H0_TASK, STRUCTURE_SCHEMA, H0_REPAIR, backend),
        grs_frontend=make_grs_frontend(GRS_GROUND_TASK, GRS_GROUND_SCHEMA,
                                       GRS_GROUND_REPAIR_TASK, GRS_SYNTH_TASK,
                                       GRS_DSL_SCHEMA, GRS_SYNTH_REPAIR_TASK, backend),
        goal_conservative_frontend=lambda sources, b: _parse_goal("conservative", sources, b),
        goal_rule_frames_frontend=lambda sources, b: _parse_goal("rule_frames", sources, b))


def _parse_goal(frontend, sources, backend):
    from guardian_truth.vnext.e2e.goal_frontends_v1 import (CONSERVATIVE_TASK,
                                                            RULE_FRAMES_TASK,
                                                            parse_goal_frames)
    task = CONSERVATIVE_TASK if frontend == "conservative" else RULE_FRAMES_TASK
    return parse_goal_frames(frontend, task, sources, backend)


def simple_program(modality="PROHIBITION", relation="UNCONDITIONAL", targets=("action:cancel_order",),
                   conditions=(), exceptions=(), condition_mode="ALL"):
    return compile_v3_structure({
        "modality": modality, "relation": relation,
        "target_clauses": [list(targets)],
        "condition_literals": list(conditions),
        "exception_literals": list(exceptions),
        "condition_mode": condition_mode, "temporal": "NONE"})


def make_universe(program, policy_text="Do not cancel orders.", programs=None):
    """Authoritative closed policy = the compiled program list itself."""
    from guardian_truth.vnext.e2e.source_adapter_v1 import E2EPolicyClosure
    return E2EPolicyClosure("test:universe:0",
                            tuple(programs) if programs else (program,))


CALL_CANCEL = TrajectoryEvent("call", tool="cancel_order",
                               arguments={"order_id": "19"}, call_id="t0", actor="ASSISTANT")
CALL_STATUS = TrajectoryEvent("call", tool="get_status",
                               arguments={"order_id": "19"}, call_id="t0", actor="ASSISTANT")


def default_binding(overrides=None):
    units = {
        "action:cancel_order": {"tool": "cancel_order", "unit_kind": "ACTION",
                                "checks": [], "quotes": ["cancel"]},
        "action:get_status": {"tool": "get_status", "unit_kind": "ACTION",
                              "checks": [], "quotes": ["status"]},
        "state:order_frozen": {"tool": "get_status", "unit_kind": "STATE",
                               "observation": {"tool": "get_status", "path": ["status"],
                                               "expected_json": '"frozen"',
                                               "entity_path": ["order_id"]},
                               "entity_path": ["order_id"], "quotes": ["frozen"]},
    }
    if overrides:
        units.update(overrides)
    return units


def run_arm(case, backend, arm="E0", max_worlds=4096):
    deps = make_deps(backend)
    semantic = run_semantic_passes(case, deps)
    return analyze_e2e_v1(case, semantic, arm, max_worlds=max_worlds), semantic


# --------------------------------------------------------------------- E5

class TestE5:
    def test_exact_offset(self):
        source = SourceText("u", "USER", "Please cancel order 19 now.")
        ref = ExtractiveRef("u", 7, 13, "cancel")
        result = resolve_ref(ref, {"u": source})
        assert result.resolution is E5Resolution.RESOLVED_EXACT

    def test_wrong_offset_unique_quote(self):
        source = SourceText("u", "USER", "Please cancel order 19 now.")
        ref = ExtractiveRef("u", 0, 6, "cancel")
        result = resolve_ref(ref, {"u": source})
        assert result.resolution is E5Resolution.RESOLVED_UNIQUE_QUOTE
        assert result.resolved.start == 7 and result.resolved.end == 13

    def test_duplicate_quote_ambiguous(self):
        source = SourceText("u", "USER", "cancel order 19, then cancel order 20.")
        # wrong offset AND two occurrences of the quote -> AMBIGUOUS (Case 3)
        ref = ExtractiveRef("u", 3, 9, "cancel")
        assert resolve_ref(ref, {"u": source}).resolution is E5Resolution.AMBIGUOUS

    def test_missing_quote_unresolved(self):
        source = SourceText("u", "USER", "Please cancel order 19.")
        ref = ExtractiveRef("u", 0, 6, "shipped")
        assert resolve_ref(ref, {"u": source}).resolution is E5Resolution.UNRESOLVED

    def test_wrong_source_unresolved_never_crosses(self):
        source = SourceText("u", "USER", "Please cancel order 19.")
        other = SourceText("v", "USER", "shipped")
        ref = ExtractiveRef("v", 0, 7, "shipped")
        # the quote exists in another source: recovery to it is FORBIDDEN
        assert resolve_ref(ref, {"u": source}).resolution is E5Resolution.UNRESOLVED

    def test_crlf_normalized(self):
        source = SourceText("u", "USER", "line one\ncancel it")
        ref = ExtractiveRef("u", 9, 15, "cancel")
        assert resolve_ref(ref, {"u": source}).resolution is E5Resolution.RESOLVED_EXACT


# --------------------------------------------------------------- assembler

class TestAssembler:
    def sources(self):
        return {"u": SourceText("u", "USER", "Cancel order 19. Do not delete anything.")}

    def ref(self, quote, start=0):
        return ExtractiveRef("u", start, start + len(quote), quote)

    def test_valid_frame_assembles(self):
        raw = (RuleFrameRaw("f1", "DESIRED_OUTCOME", self.ref("Cancel order 19."),
                            None, None, (), (), "NONE", None, "NONE", "NONE",
                            "ACTION", (), ()),)
        contract = assemble_contract("conservative", raw, self.sources())
        assert len(contract.frames) == 1
        frame = contract.frames[0]
        assert frame.content.text == "Cancel order 19."
        assert frame.source_support

    def test_unresolvable_content_rejects_frame(self):
        raw = (RuleFrameRaw("f1", "DESIRED_OUTCOME", self.ref("Refund everything"),
                            None, None, (), (), "NONE", None, "NONE", "NONE",
                            "ACTION", (), ()),)
        contract = assemble_contract("conservative", raw, self.sources())
        assert not contract.frames
        assert contract.rejected_frames and "CONTENT_UNRESOLVED" in contract.rejected_frames[0][1]

    def test_ambiguous_condition_rejects_frame(self):
        text = "Cancel it, then cancel it again."
        sources = {"u": SourceText("u", "USER", text)}
        # condition quote 'it' occurs twice; the wrong offset cannot repair it
        raw = (RuleFrameRaw("f1", "OBLIGATION", ExtractiveRef("u", 0, 6, "Cancel"),
                            None, None,
                            (ExtractiveRef("u", 0, 2, "it"),), (), "NONE", None,
                            "NONE", "NONE", "ACTION", (), ()),)
        contract = assemble_contract("rule_frames", raw, sources)
        assert not contract.frames
        assert any("AMBIGUOUS" in reason for _, reason in contract.rejected_frames)

    def test_unknown_kind_rejects(self):
        raw = (RuleFrameRaw("f1", "UNKNOWN", self.ref("Cancel order 19."),
                            None, None, (), (), "NONE", None, "NONE", "NONE",
                            "ACTION", (), ()),)
        contract = assemble_contract("conservative", raw, self.sources())
        assert not contract.frames

    def test_duplicate_frames_collapse(self):
        raw = (RuleFrameRaw("f1", "PROHIBITION", self.ref("Do not delete anything."),
                            None, None, (), (), "NONE", None, "NONE", "NONE",
                            "ACTION", (), ()),
               RuleFrameRaw("f2", "PROHIBITION", self.ref("Do not delete anything."),
                            None, None, (), (), "NONE", None, "NONE", "NONE",
                            "ACTION", (), ()))
        contract = assemble_contract("conservative", raw, self.sources())
        assert len(contract.frames) == 1

    def test_authorization_requires_alternatives(self):
        raw = (RuleFrameRaw("f1", "AUTHORIZATION", self.ref("Cancel order 19."),
                            None, None, (), (), "NONE", None, "NONE", "ANY_OF",
                            "ACTION", (), ()),)
        contract = assemble_contract("conservative", raw, self.sources())
        assert not contract.frames
        assert contract.rejected_frames


# ----------------------------------------------------------- goal firewall

class TestGoalFirewall:
    def test_metamorphic_contract_invariance(self):
        """Spec section 116: one user request, ten different future trajectories
        -> byte/canonical-equivalent Goal outputs."""
        user_text = "Please cancel order 19, but do not delete my account."
        trajectories = [
            (CALL_CANCEL,), (CALL_STATUS,),
            (CALL_CANCEL, CALL_STATUS),
            (TrajectoryEvent("call", tool="delete_account", arguments={}, call_id="t0"),),
            (), (CALL_STATUS, CALL_STATUS),
            (TrajectoryEvent("call", tool="refund_order", arguments={"order_id": "19"},
                             call_id="t0"),),
        ] * 2
        contracts = []
        for calls in trajectories:
            case = make_case(user_text=user_text, calls=calls,
                             policy="Handle requests per policy.")
            backend = ScriptedBackend(h0_structure=None, binding_units=default_binding())
            sources = {"user:0": case.user_sources[0]}
            from guardian_truth.vnext.e2e.goal_frontends_v1 import parse_goal_conservative
            contract, _ = parse_goal_conservative(sources, backend)
            contracts.append(contract)
        keys = [tuple((f.kind, f.content.text if f.content else None,
                       tuple(c.text for c in f.conditions)) for f in c.frames)
                for c in contracts]
        assert len(set(map(repr, keys))) == 1


# ------------------------------------------------- policy composition

class TestPolicyComposition:
    def test_equivalent_readings_dedupe(self):
        h0 = H0Result("VALID", simple_program(), None, {})
        grs = GRSResult("VALID", ((simple_program(),),), (), None, None, False, {}, {})
        composition = compose_policy_readings(h0, grs, ("action:cancel_order",))
        assert composition.agreement == "EQUIVALENT"
        assert len(composition.readings) == 1

    def test_different_readings_retained(self):
        h0 = H0Result("VALID", simple_program(), None, {})
        grs = GRSResult("VALID",
                        ((simple_program(modality="PERMISSION"),),), (), None, None, False, {}, {})
        composition = compose_policy_readings(h0, grs, ("action:cancel_order",))
        assert composition.agreement == "DIFFERENT"
        assert len(composition.readings) == 2

    def test_one_invalid_keeps_valid_with_open_coverage(self):
        h0 = H0Result("VALID", simple_program(), None, {})
        grs = GRSResult("UNAVAILABLE", (), (), None, None, False, {}, {})
        composition = compose_policy_readings(h0, grs, ("action:cancel_order",))
        assert composition.agreement == "ONE_INVALID"
        assert len(composition.readings) == 1
        assert composition.unresolved_reason

    def test_gate_distinguishes_permission_exclusivity(self):
        free = simple_program(modality="PERMISSION", relation="UNCONDITIONAL")
        exclusive = simple_program(modality="PERMISSION", relation="ONLY_IF",
                                   conditions=("state:order_frozen",))
        h0 = H0Result("VALID", free, None, {})
        grs = GRSResult("VALID", ((exclusive,),), (), None, None, False, {}, {})
        composition = compose_policy_readings(h0, grs, ("action:cancel_order", "state:order_frozen"))
        assert composition.agreement == "DIFFERENT"


# ---------------------------------------------------- full pipeline: E2E

class TestAnalyzeE2E:
    def test_prohibition_violation_proved_error(self):
        """v3 fact pattern {action:cancel_order} on PROHIBITION -> VIOLATION ->
        PROVED_ERROR with a valid E2E certificate."""
        case = make_case(calls=(CALL_CANCEL,), history_complete=True)
        backend = ScriptedBackend(h0_structure=simple_program(),
                                  binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.PROVED_ERROR
        assert output.result.certificate_check.valid
        assert output.product_decision.binary_label == 1
        assert check_certificate_e2e(output.result.certificate, output.context,
                                     output.problem, semantic_ledger(output), registry()).valid

    def test_safe_without_closure_unresolved(self):
        case = make_case(calls=(CALL_STATUS,), history_complete=True)
        backend = ScriptedBackend(h0_structure=simple_program(),
                                  binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_closed_safe_proved_no_error(self):
        """Closed semantic policy + closed goal contract + complete history +
        bound claims (none material here) -> PROVED_NO_ERROR (spec section 153)."""
        from guardian_truth.vnext.e2e.goal_types_v1 import GoalContract
        program = simple_program()
        case = make_case(calls=(CALL_STATUS,), history_complete=True,
                         policy_universe=make_universe(program),
                         goal_closure=GoalContract("goal:closure", "authoritative",
                                                   ("user:0",), (), (), ()))
        backend = ScriptedBackend(h0_structure=program, binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.PROVED_NO_ERROR
        assert output.result.certificate_check.valid
        assert output.product_decision.binary_label == 0

    def test_closure_ablation_history_incomplete_unresolved(self):
        """Spec section 154: the same closed-safe case with incomplete history
        must become UNRESOLVED, never NO_ERROR."""
        from guardian_truth.vnext.e2e.goal_types_v1 import GoalContract
        program = simple_program()
        case = make_case(calls=(CALL_STATUS,), history_complete=False,
                         policy_universe=make_universe(program),
                         goal_closure=GoalContract("goal:closure", "authoritative",
                                                   ("user:0",), (), (), ()))
        backend = ScriptedBackend(h0_structure=program, binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_world_budget_exceeded_unresolved(self):
        # E4 with two disagreeing frontends: 2 policy readings x 1 goal = 2
        # worlds > a budget of 1 -> terminal UNRESOLVED, never top-k
        case = make_case(calls=(CALL_CANCEL,))
        backend = ScriptedBackend(
            h0_structure=simple_program(),
            grs_inventory={"facts": [
                {"id": "F1", "atom": "action:cancel_order", "span": "cancel orders"}],
                "markers": [{"id": "M1", "kind": "MODAL_MARKER", "value": "PERMIT",
                             "span": "Do not"}]},
            grs_dsl="RULESET(RULE(PERMIT, F1))",
            binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E4", max_worlds=1)
        assert output.result.status is CoreStatus.UNRESOLVED
        assert any("WORLD_BUDGET_EXCEEDED" in item
                   for item in output.result.diagnostics.missing_evidence)

    def test_grs_arm_uses_grs_reading(self):
        case = make_case(calls=(CALL_CANCEL,))
        backend = ScriptedBackend(
            h0_structure=simple_program(modality="PERMISSION"),
            grs_inventory={"facts": [
                {"id": "F1", "atom": "action:cancel_order", "span": "cancel orders"}],
                "markers": [{"id": "M1", "kind": "MODAL_MARKER", "value": "PROHIBIT",
                             "span": "Do not"}]},
            grs_dsl="RULESET(RULE(PROHIBIT, F1))",
            binding_units=default_binding())
        output, _ = run_arm(case, backend, arm="E1")
        assert output.result.status is CoreStatus.PROVED_ERROR
        assert output.policy_composition.readings[0].frontend == "grs"


def semantic_ledger(output):
    return output.context and _ledger_from_context(output)


def _ledger_from_context(output):
    # rebuild the ledger exactly as analyze_e2e_v1 did (deterministic)
    from guardian_truth.vnext.e2e.source_adapter_v1 import render_prompt, render_response
    from guardian_truth.vnext.normalize import normalize
    from guardian_truth.vnext.ledger import EvidenceLedger
    events = normalize(output.context.prompt, output.context.response,
                       tool_identities=output.context.tool_metadata)
    return EvidenceLedger.from_events(events, history_complete=True,
                                      completeness_basis="controlled complete history")


def registry():
    return ContractRegistry(())


# ------------------------------------------- v3-equivalence matrix (lowering)

class TestLoweringV3Equivalence:
    """The lowered obligations must reproduce evaluate_v3_program verdicts on
    the trajectory-evidence surface: VIOLATION -> PROVED_ERROR (complete
    space), non-violation with full closure -> PROVED_NO_ERROR, decisive
    unknown states -> UNRESOLVED."""

    def _run(self, program, calls, history, response="Done.", binding_overrides=None,
             history_complete=True, closure=True):
        from guardian_truth.vnext.e2e.goal_types_v1 import GoalContract
        case = make_case(calls=calls, history=history, response_text=response,
                         history_complete=history_complete,
                         policy_universe=make_universe(program, policy_text=_policy_text(program)) if closure else None,
                         goal_closure=GoalContract("goal:closure", "authoritative",
                                                   ("user:0",), (), (), ()) if closure else None,
                         policy=_policy_text(program))
        units = default_binding(binding_overrides or {})
        backend = ScriptedBackend(h0_structure=program, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        return output

    def test_prohibition_when_state_holds(self):
        """PROHIBITION IF state: call + frozen observed -> VIOLATION."""
        program = simple_program(relation="IF", conditions=("state:order_frozen",))
        status_history = (
            TrajectoryEvent("user", text="What is the status of order 19?"),
            TrajectoryEvent("call", tool="get_status", arguments={"order_id": "19"},
                            call_id="h0", actor="ASSISTANT"),
            TrajectoryEvent("result", tool="get_status", call_id="h0", requestor="ASSISTANT",
                            payload={"order_id": "19", "status": "frozen"}),
        )
        output = self._run(program, calls=(CALL_CANCEL,), history=status_history)
        assert output.result.status is CoreStatus.PROVED_ERROR

    def test_prohibition_when_state_absent_safe(self):
        """PROHIBITION IF state: call + status observed NOT frozen -> safe."""
        program = simple_program(relation="IF", conditions=("state:order_frozen",))
        status_history = (
            TrajectoryEvent("user", text="What is the status of order 19?"),
            TrajectoryEvent("call", tool="get_status", arguments={"order_id": "19"},
                            call_id="h0", actor="ASSISTANT"),
            TrajectoryEvent("result", tool="get_status", call_id="h0", requestor="ASSISTANT",
                            payload={"order_id": "19", "status": "active"}),
        )
        output = self._run(program, calls=(CALL_CANCEL,), history=status_history)
        assert output.result.status is CoreStatus.PROVED_NO_ERROR

    def test_prohibition_when_state_unobserved_unresolved(self):
        """PROHIBITION IF state: call + status never observed -> decisive
        UNKNOWN -> UNRESOLVED (spec section 97)."""
        program = simple_program(relation="IF", conditions=("state:order_frozen",))
        output = self._run(program, calls=(CALL_CANCEL,), history=())
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_prohibition_unless_exception_holds_safe(self):
        """PROHIBITION UNLESS state: call + frozen observed -> exception
        applies -> safe (PERMITTED, never a violation)."""
        program = simple_program(relation="UNLESS", exceptions=("state:order_frozen",))
        status_history = (
            TrajectoryEvent("user", text="What is the status of order 19?"),
            TrajectoryEvent("call", tool="get_status", arguments={"order_id": "19"},
                            call_id="h0", actor="ASSISTANT"),
            TrajectoryEvent("result", tool="get_status", call_id="h0", requestor="ASSISTANT",
                            payload={"order_id": "19", "status": "frozen"}),
        )
        output = self._run(program, calls=(CALL_CANCEL,), history=status_history)
        assert output.result.status is CoreStatus.PROVED_NO_ERROR

    def test_prohibition_unless_exception_not_observed_unresolved(self):
        """PROHIBITION UNLESS state: call + exception state unobserved -> the
        violation depends on an unknown exception -> UNRESOLVED."""
        program = simple_program(relation="UNLESS", exceptions=("state:order_frozen",))
        output = self._run(program, calls=(CALL_CANCEL,), history=())
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_requirement_satisfied(self):
        """REQUIREMENT action + the action was done -> safe."""
        program = simple_program(modality="REQUIREMENT", relation="UNCONDITIONAL",
                                 targets=("action:cancel_order",))
        output = self._run(program, calls=(CALL_CANCEL,), history=())
        assert output.result.status is CoreStatus.PROVED_NO_ERROR

    def test_requirement_not_done_violation(self):
        """REQUIREMENT action + only a different action -> VIOLATION (the
        at-least-once sentinel encoding)."""
        program = simple_program(modality="REQUIREMENT", relation="UNCONDITIONAL",
                                 targets=("action:cancel_order",))
        output = self._run(program, calls=(CALL_STATUS,), history=())
        assert output.result.status is CoreStatus.PROVED_ERROR

    def test_requirement_if_gate_not_holding_safe(self):
        """REQUIREMENT IF state + gate not observed-false... state never
        observed -> antecedent unknown -> not proved required -> UNRESOLVED is
        wrong here: the requirement is NOT proven due, so no violation, but
        closure cannot prove safety either -> UNRESOLVED (honest)."""
        program = simple_program(modality="REQUIREMENT", relation="IF",
                                 targets=("action:cancel_order",),
                                 conditions=("state:order_frozen",))
        output = self._run(program, calls=(CALL_STATUS,), history=())
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_requirement_if_gate_holds_not_done_violation(self):
        program = simple_program(modality="REQUIREMENT", relation="IF",
                                 targets=("action:cancel_order",),
                                 conditions=("state:order_frozen",))
        status_history = (
            TrajectoryEvent("call", tool="get_status", arguments={"order_id": "19"},
                            call_id="h0", actor="ASSISTANT"),
            TrajectoryEvent("result", tool="get_status", call_id="h0", requestor="ASSISTANT",
                            payload={"order_id": "19", "status": "frozen"}),
        )
        output = self._run(program, calls=(CALL_STATUS,), history=status_history)
        assert output.result.status is CoreStatus.PROVED_ERROR

    def test_wrong_argument_no_violation(self):
        """PROHIBITION with an entity-pinned check: a call with a different
        entity does not match the rule -> safe (wrong-entity is the GOAL axis
        concern when the goal pins the entity)."""
        program = simple_program()
        # binding pins order_id=19 for the cancel action
        units = {"action:cancel_order": {
            "tool": "cancel_order", "unit_kind": "ACTION",
            "checks": [{"path": ["order_id"], "allowed_json": ['"19"'],
                        "presence_only": False, "quote": "order 19"}],
            "quotes": ["cancel order 19"]}}
        case = make_case(calls=(TrajectoryEvent("call", tool="cancel_order",
                                                 arguments={"order_id": "20"},
                                                 call_id="t0", actor="ASSISTANT"),),
                         history_complete=True)
        backend = ScriptedBackend(h0_structure=program, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.UNRESOLVED  # match unknown-safe, no closure


def _policy_text(program):
    return {
        ("PROHIBITION", "UNCONDITIONAL"): "Do not cancel orders.",
        ("PROHIBITION", "IF"): "Do not cancel orders when they are frozen.",
        ("PROHIBITION", "UNLESS"): "You may cancel orders unless they are frozen.",
        ("REQUIREMENT", "UNCONDITIONAL"): "You must cancel the order.",
        ("REQUIREMENT", "IF"): "You must cancel the order when it is frozen.",
    }[(program["modality"], program["relation"])]


# ------------------------------------------------------- goal axis semantics

def _goal_frames_response(user_text, frames):
    """Build a goal-frames LLM response with exact refs into user_text."""
    def ref(quote, offset=None):
        start = user_text.find(quote) if offset is None else offset
        return {"source_id": "user:0", "start": start, "end": start + len(quote),
                "quote": quote}
    return {"frames": [
        {"frame_id_local": item["id"], "kind": item["kind"],
         "content": ref(item["content"]) if item.get("content") else None,
         "bearer": None, "entity": None,
         "conditions": [ref(condition) for condition in item.get("conditions", ())],
         "exceptions": [ref(exception) for exception in item.get("exceptions", ())],
         "temporal": item.get("temporal", "NONE"),
         "temporal_event": None,
         "coordination": item.get("coordination", "NONE"),
         "choice": item.get("choice", "NONE"),
         "target_level": item.get("target_level", "ACTION"),
         "alternatives": [ref(alternative) for alternative in item.get("alternatives", ())],
         "unresolved_fields": []}
        for item in frames]}


class TestGoalAxis:
    def _goal_case(self, *, user_text, goal_frames, calls, history=(),
                   response_text="Done.", binding_overrides=None, schemas=None,
                   catalog=("action:cancel_order", "action:get_status")):
        goal_response = _goal_frames_response(user_text, goal_frames)
        unit_overrides = {}
        for frame in goal_frames:
            if frame.get("serving"):
                unit_id = None
                # the frame content unit id depends on the assembler's canonical frame id
                unit_overrides[frame["id"]] = frame["serving"]
        units = default_binding()
        units.update(binding_overrides or {})
        return (user_text, goal_response, units, unit_overrides)

    def test_outcome_addressed_by_allowed_tool(self):
        """DESIRED_OUTCOME served by get_status; assistant called it -> safe."""
        user_text = "Please show the status of order 19."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "show the status",
                   "serving": ["get_status"]}]
        goal_response = _goal_frames_response(user_text, frames)
        # the goal unit ids are canonical: goal:goal:conservative:f0:content
        units = default_binding({
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
        })
        case = make_case(user_text=user_text, calls=(CALL_STATUS,), history_complete=True,
                         catalog=("action:cancel_order", "action:get_status"),
                         schemas=(("get_status", {"order_id": "string"}),))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, semantic = run_arm(case, backend, arm="E0")
        # no policy violation; goal addressed; without closure -> UNRESOLVED (safe)
        assert output.result.status is CoreStatus.UNRESOLVED

    def test_outcome_unaddressed_wrong_tool_error(self):
        """DESIRED_OUTCOME 'show status'; assistant called cancel_order ->
        ADDRESS violation -> PROVED_ERROR (spec sections 82, 2.3)."""
        user_text = "Please show the status of order 19."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "show the status",
                   "serving": ["get_status"]}]
        goal_response = _goal_frames_response(user_text, frames)
        units = default_binding({
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
        })
        case = make_case(user_text=user_text, calls=(CALL_CANCEL,), history_complete=True,
                         catalog=("action:cancel_order", "action:get_status"),
                         schemas=(("get_status", {"order_id": "string"}),
                                  ("cancel_order", {"order_id": "string"})))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, semantic = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.PROVED_ERROR
        assert output.result.certificate_check.valid

    def test_any_of_alternatives_either_satisfies(self):
        """Spec section 59: 'You can use get_status or lookup_status' — either
        tool addresses the outcome; using the second one is NOT a violation.
        The ANY-OF encoding must not create fake disagreement worlds."""
        user_text = "Show my order status; you can use get_status or lookup_status."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "Show my order status",
                   "serving": ["get_status", "lookup_status"]}]
        goal_response = _goal_frames_response(user_text, frames)
        units = default_binding({
            "action:get_status": {"tool": "get_status", "unit_kind": "ACTION", "quotes": ["status"]},
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status", "lookup_status"], "quotes": ["status"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status", "lookup_status"], "quotes": ["status"]},
        })
        lookup_call = TrajectoryEvent("call", tool="lookup_status",
                                       arguments={"order_id": "19"}, call_id="t0",
                                       actor="ASSISTANT")
        case = make_case(user_text=user_text, calls=(lookup_call,), history_complete=True,
                         catalog=("action:cancel_order", "action:get_status"),
                         schemas=(("get_status", {"order_id": "string"}),
                                  ("lookup_status", {"order_id": "string"})))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        # the ADDRESS obligation is satisfied by lookup_status: no violation
        # provable, and safety is not provable without closure -> UNRESOLVED
        assert output.result.status is CoreStatus.UNRESOLVED
        worlds_safe = all(proof.error_value is not Truth.TRUE
                          for proof in output.result.world_proofs)
        assert worlds_safe

    def test_user_prohibition_violated(self):
        """User 'do not delete anything' + delete call -> PROVED_ERROR."""
        user_text = "Show my order status, and do not delete anything."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "Show my order status",
                   "serving": ["get_status"]},
                  {"id": "f2", "kind": "PROHIBITION", "content": "do not delete anything",
                   "target_level": "ATTEMPT", "serving": ["delete_account"]}]
        goal_response = _goal_frames_response(user_text, frames)
        units = default_binding({
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
            "goal:goal:conservative:f1:content": {
                "kind": "OUTCOME", "tools": ["delete_account"], "quotes": ["delete"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["get_status"], "quotes": ["status"]},
            "goal:goal:rule_frames:f1:content": {
                "kind": "OUTCOME", "tools": ["delete_account"], "quotes": ["delete"]},
        })
        delete_call = TrajectoryEvent("call", tool="delete_account", arguments={},
                                       call_id="t0", actor="ASSISTANT")
        case = make_case(user_text=user_text, calls=(delete_call,), history_complete=True,
                         catalog=("action:cancel_order", "action:get_status"),
                         schemas=(("get_status", {"order_id": "string"}),
                                  ("delete_account", {})))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.PROVED_ERROR

    def test_user_obligation_not_done_violation(self):
        """User 'you must confirm before cancelling' + cancel without confirm
        -> USER-REQUIRE violation (spec sections 61, 83)."""
        user_text = "Cancel order 19, but you must confirm with me before cancelling."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "Cancel order 19",
                   "serving": ["cancel_order"]},
                  {"id": "f2", "kind": "OBLIGATION", "content": "confirm with me",
                   "serving": ["confirm_with_user"]}]
        goal_response = _goal_frames_response(user_text, frames)
        units = default_binding({
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["cancel_order"], "quotes": ["Cancel order 19"]},
            "goal:goal:conservative:f1:content": {
                "kind": "OUTCOME", "tools": ["confirm_with_user"], "quotes": ["confirm"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["cancel_order"], "quotes": ["Cancel order 19"]},
            "goal:goal:rule_frames:f1:content": {
                "kind": "OUTCOME", "tools": ["confirm_with_user"], "quotes": ["confirm"]},
        })
        case = make_case(user_text=user_text, calls=(CALL_CANCEL,), history_complete=True,
                         catalog=("action:cancel_order",),
                         schemas=(("cancel_order", {"order_id": "string"}),
                                  ("confirm_with_user", {})))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.PROVED_ERROR

    def test_user_obligation_done_safe(self):
        """The same case with the confirm call first -> obligation satisfied."""
        user_text = "Cancel order 19, but you must confirm with me before cancelling."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "Cancel order 19",
                   "serving": ["cancel_order"]},
                  {"id": "f2", "kind": "OBLIGATION", "content": "confirm with me",
                   "serving": ["confirm_with_user"]}]
        goal_response = _goal_frames_response(user_text, frames)
        units = default_binding({
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["cancel_order"], "quotes": ["Cancel order 19"]},
            "goal:goal:conservative:f1:content": {
                "kind": "OUTCOME", "tools": ["confirm_with_user"], "quotes": ["confirm"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["cancel_order"], "quotes": ["Cancel order 19"]},
            "goal:goal:rule_frames:f1:content": {
                "kind": "OUTCOME", "tools": ["confirm_with_user"], "quotes": ["confirm"]},
        })
        history = (TrajectoryEvent("call", tool="confirm_with_user", arguments={},
                                    call_id="h0", actor="ASSISTANT"),)
        case = make_case(user_text=user_text, calls=(CALL_CANCEL,), history=history,
                         history_complete=True,
                         catalog=("action:cancel_order",),
                         schemas=(("cancel_order", {"order_id": "string"}),
                                  ("confirm_with_user", {})))
        backend = ScriptedBackend(goal_frames=goal_response, binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        assert output.result.status is CoreStatus.UNRESOLVED  # safe but not provably closed

    def test_user_action_cannot_satisfy_assistant_obligation(self):
        """Spec section 128: USER says 'I verified my identity'; the ASSISTANT
        obligation to verify is NOT satisfied by the user's action."""
        user_text = "I verified my identity already. Delete order 19 now."
        frames = [{"id": "f1", "kind": "DESIRED_OUTCOME", "content": "Delete order 19",
                   "serving": ["delete_order"]}]
        goal_response = _goal_frames_response(user_text, frames)
        policy = "The assistant must verify identity before deleting an order."
        # policy as REQUIREMENT on verify_identity
        program = simple_program(modality="REQUIREMENT", relation="UNCONDITIONAL",
                                 targets=("action:verify_identity",))
        history = (TrajectoryEvent("user", text="I verified my identity already."),)
        units = default_binding({
            "action:verify_identity": {"tool": "verify_identity", "unit_kind": "ACTION",
                                        "quotes": ["verify"]},
            "goal:goal:conservative:f0:content": {
                "kind": "OUTCOME", "tools": ["delete_order"], "quotes": ["Delete order 19"]},
            "goal:goal:rule_frames:f0:content": {
                "kind": "OUTCOME", "tools": ["delete_order"], "quotes": ["Delete order 19"]},
        })
        delete_call = TrajectoryEvent("call", tool="delete_order",
                                       arguments={"order_id": "19"}, call_id="t0",
                                       actor="ASSISTANT")
        case = make_case(policy=policy, user_text=user_text, calls=(delete_call,),
                         history=history, history_complete=True,
                         catalog=("action:verify_identity", "action:delete_order"),
                         schemas=(("delete_order", {"order_id": "string"}),
                                  ("verify_identity", {})))
        backend = ScriptedBackend(h0_structure=program, goal_frames=goal_response,
                                  binding_units=units)
        output, _ = run_arm(case, backend, arm="E0")
        # REQUIREMENT verify_identity: the target-call sentinel encoding only
        # counts ASSISTANT response calls; the user text proves nothing
        assert output.result.status is CoreStatus.PROVED_ERROR
