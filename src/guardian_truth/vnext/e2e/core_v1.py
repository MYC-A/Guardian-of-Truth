"""E2E V1 entry point: analyze_e2e_v1 (spec sections 109-110, 136-142).

Explicit dependency injection — no hidden API client, no hidden global state:

    analyze_e2e_v1(case_sources, deps, arm=..., max_worlds=..., adapter_mode=...)

Arms (spec sections 136-142, primary causal comparison):
    E0  Policy=H0        Goal=Conservative
    E1  Policy=GRS       Goal=Conservative
    E2  Policy=H0        Goal=RuleFrames+E5
    E3  Policy=GRS       Goal=RuleFrames+E5
    E4  Policy={H0,GRS}  Goal={Conservative,RuleFrames+E5}  (retained, deduped)

The frontend/binding/claim REQUESTS are arm-independent: the runner executes
each semantic pass once per case and the arms compose the sealed outputs
deterministically, isolating exactly the frontend substitution effect
(spec sections 136: 'do not mix historical baseline and causal comparison').

Binary 0/1 appears only in the adapter after the proof Core; UNRESOLVED is
never presented as proven safety (spec sections 108).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from ..adapters import AdapterMode, ProductDecision, adapt
from ..binder import bind_claim
from ..certificates import AuthoritativeAxis
from ..claims import build_claim_graph
from ..decision import CertifiedCoreResult
from ..grounding import bind_evaluation_hypothesis
from ..integrity import canonical, digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..normalize import normalize
from ..proof_records import ProofProblem
from ..solver import solve
from ..tools import ContractRegistry
from ..types import CoreStatus, CoverageStatus, Reason
from .certificate_context_v1 import (E2ECertificateContext, check_certificate_e2e,
                                     make_e2e_certificate)
from .goal_composition_v1 import compose_goal_contracts
from .goal_types_v1 import BindingRecord, GoalContract
from .policy_composition_v1 import (PolicyComposition, compose_policy_readings,
                                    compose_single_frontend)
from .semantic_binding_v1 import run_semantic_binding
from .source_adapter_v1 import (E2ECaseSources, render_prompt, render_response,
                                target_call_specs, trajectory_view, user_source_index)
from .world_integration_v1 import assemble_worlds, claim_axes, lower_goal_choices, lower_policy_choices

ARMS = ("E0", "E1", "E2", "E3", "E4")


@dataclass(frozen=True)
class E2EDependencies:
    """All injectable components (spec section 110)."""

    backend: object                                  # SemanticBackend for claims/binding
    h0_frontend: object                              # (policy_text, atom_catalog) -> H0Result
    grs_frontend: object                             # (policy_text, atom_catalog) -> GRSResult
    goal_conservative_frontend: object               # (sources dict, backend) -> (contract, telemetry)
    goal_rule_frames_frontend: object


@dataclass(frozen=True)
class E2ESemanticOutputs:
    """Arm-independent semantic pass outputs for one case (sealable)."""

    ledger: EvidenceLedger
    claim_graph: object
    h0_result: object
    grs_result: object
    conservative_contract: GoalContract
    rule_frames_contract: GoalContract
    binding: BindingRecord
    telemetry: dict


@dataclass(frozen=True)
class E2EAnalysisResult:
    arm: str
    case_id: str
    result: CertifiedCoreResult
    product_decision: ProductDecision
    problem: ProofProblem
    context: E2ECertificateContext
    required_worlds: int
    policy_composition: PolicyComposition
    goal_composition: object
    diagnostics: dict


def _serialize_binding(binding: BindingRecord) -> dict:
    from dataclasses import asdict

    def enc(obj):
        if hasattr(obj, "__dataclass_fields__"):
            return {key: enc(value) for key, value in asdict(obj).items()}
        if isinstance(obj, tuple):
            return [enc(item) for item in obj]
        if isinstance(obj, list):
            return [enc(item) for item in obj]
        return obj

    return {"atom_bindings": [[unit, [enc(candidate) for candidate in candidates]]
                              for unit, candidates in binding.atom_bindings],
            "outcome_bindings": [[unit, [enc(candidate) for candidate in candidates]]
                                 for unit, candidates in binding.outcome_bindings],
            "unbound_units": list(binding.unbound_units),
            "failures": list(binding.failures)}


def _serialize_contract(contract: GoalContract) -> dict:
    from dataclasses import asdict

    def proposition(item):
        if item is None:
            return None
        return {"text": item.text,
                "anchor": asdict(item.anchor), "resolution": item.resolution.value}

    return {"contract_id": contract.contract_id, "frontend": contract.frontend,
            "source_ids": list(contract.source_ids),
            "frames": [{
                "frame_id": frame.frame_id, "frontend": frame.frontend,
                "kind": frame.kind.value, "content": proposition(frame.content),
                "bearer": proposition(frame.bearer), "entity": proposition(frame.entity),
                "conditions": [proposition(item) for item in frame.conditions],
                "exceptions": [proposition(item) for item in frame.exceptions],
                "alternatives": [proposition(item) for item in frame.alternatives],
                "temporal": frame.temporal,
                "temporal_event": proposition(frame.temporal_event),
                "coordination": frame.coordination, "choice": frame.choice,
                "target_level": frame.target_level.value,
                "source_support": [asdict(item) for item in frame.source_support]}
                for frame in contract.frames],
            "rejected_frames": [list(item) for item in contract.rejected_frames],
            "unresolved_fields": list(contract.unresolved_fields)}


def _serialize_reading(reading) -> dict:
    return {"reading_id": reading.reading_id, "frontend": reading.frontend,
            "programs": [dict(program) for program in reading.programs],
            "equivalent_to": list(reading.equivalent_to)}


def run_semantic_passes(sources: E2ECaseSources, deps: E2EDependencies) -> E2ESemanticOutputs:
    """All arm-independent LLM passes for one case, in the frozen order."""
    prompt = render_prompt(sources)
    response = render_response(sources)
    events = normalize(prompt, response, tool_identities=sources.tool_metadata())
    ledger = EvidenceLedger.from_events(events, history_complete=sources.history_complete,
                                        completeness_basis=sources.completeness_basis)
    index = LedgerIndex(ledger)

    # claims (10 narrow passes over the target response only)
    graph = build_claim_graph(response, deps.backend)

    # policy frontends (frozen, byte-identical tasks)
    h0_result = deps.h0_frontend(sources.policy_text, sources.atom_catalog)
    grs_result = deps.grs_frontend(sources.policy_text, sources.atom_catalog)

    # goal frontends (firewall: user sources only)
    user_sources = user_source_index(sources)
    conservative_contract, _ = deps.goal_conservative_frontend(user_sources, deps.backend)
    rule_frames_contract, _ = deps.goal_rule_frames_frontend(user_sources, deps.backend)

    # shared semantic binding pass (PASS 2): catalog atoms + goal propositions
    units = [{"unit_id": atom, "unit_kind": atom.split(":", 1)[0].upper()}
             for atom in sources.atom_catalog]
    for contract in (conservative_contract, rule_frames_contract):
        for frame in contract.frames:
            if frame.content is not None:
                units.append({"unit_id": f"goal:{frame.frame_id}:content",
                              "unit_kind": "OUTCOME", "text": frame.content.text})
            for proposition in frame.conditions:
                units.append({"unit_id": f"goalcond:{proposition.text}",
                              "unit_kind": "STATE", "text": proposition.text})
            for proposition in frame.exceptions:
                units.append({"unit_id": f"goalexc:{proposition.text}",
                              "unit_kind": "STATE", "text": proposition.text})
            if frame.temporal_event is not None:
                units.append({"unit_id": f"goalevent:{frame.temporal_event.text}",
                              "unit_kind": "EVENT", "text": frame.temporal_event.text})
    # dedupe units by id, preserving order
    seen, unique_units = set(), []
    for unit in units:
        if unit["unit_id"] not in seen:
            seen.add(unit["unit_id"])
            unique_units.append(unit)
    schemas = {schema["name"]: schema.get("arguments", {}) for schema in sources.tool_schemas}
    trajectory = trajectory_view(sources)
    normative_texts = {"policy": sources.policy_text,
                       **{source.source_id: source.text for source in sources.user_sources}}
    binding, binding_telemetry = run_semantic_binding(
        unique_units, sources.tool_names, schemas, trajectory, normative_texts, deps.backend)

    return E2ESemanticOutputs(ledger, graph, h0_result, grs_result,
                              conservative_contract, rule_frames_contract, binding,
                              {"binding": binding_telemetry})


def analyze_e2e_v1(sources: E2ECaseSources, semantic: E2ESemanticOutputs,
                   arm: str, *, max_worlds: int = 4096,
                   adapter_mode: AdapterMode = AdapterMode.AUDIT) -> E2EAnalysisResult:
    """Deterministic arm composition: no LLM, no escalation (spec section 158)."""
    if arm not in ARMS:
        raise ValueError("unknown arm: " + arm)
    use_grs = arm in {"E1", "E3", "E4"}
    use_h0 = arm in {"E0", "E2", "E4"}
    use_rule_frames = arm in {"E2", "E3", "E4"}

    ledger = semantic.ledger
    index = LedgerIndex(ledger)
    registry = ContractRegistry(sources.t1_contracts)
    hard_reasons, reasons = [], []

    # ---- policy axis ----
    # Arm semantics (spec sections 136-142): a SINGLE-frontend arm's policy
    # space is that frontend's readings (empirically complete when the
    # frontend is VALID); only E4 composes both frontends, where one invalid
    # frontend keeps the valid readings with OPEN coverage (spec section 52).
    h0 = semantic.h0_result
    grs = semantic.grs_result
    if use_h0 and use_grs:
        policy_comp = compose_policy_readings(h0, grs, sources.atom_catalog)
    elif use_h0:
        policy_comp = compose_single_frontend(h0, None, sources.atom_catalog)
    else:
        policy_comp = compose_single_frontend(None, grs, sources.atom_catalog)
    policy_space_open = policy_comp.unresolved_reason is not None

    # ---- goal axis ----
    conservative = semantic.conservative_contract
    rule_frames = semantic.rule_frames_contract if use_rule_frames else semantic.conservative_contract
    goal_comp = compose_goal_contracts(conservative, rule_frames)
    goal_space_open = goal_comp.unresolved_reason is not None

    # ---- lowering ----
    from .policy_lowering_v1 import LoweringContext
    target_calls = target_call_specs(ledger.events)
    all_calls = tuple({"event_id": event.event_id, "index": event.index,
                       "call_id": event.call_id,
                       "tool": event.tool.name if event.tool else None,
                       "arguments": event.payload, "actor": event.actor,
                       "document": event.source.document}
                      for event in ledger.events if event.kind == "call")
    context = LoweringContext(target_calls, len(ledger.events) - 1, all_calls)
    policy_choices = lower_policy_choices(policy_comp.readings, semantic.binding, context)
    goal_choices = lower_goal_choices(goal_comp.contracts, semantic.binding, context)
    if not policy_choices and not goal_choices:
        hard_reasons.append(Reason.POLICY_NO_INTERPRETATION)

    # ---- closure vs empirical completeness (spec sections 101-102, 153) ----
    # An axis is COMPLETE when its candidate space was fully enumerated by the
    # selected frontends (empirical completeness, baseline semantics); it is
    # CLOSED only under an authoritative universe/contract declaration
    # (PROVED_NO_ERROR requires closure, PROVED_ERROR requires completeness).
    policy_closed = False
    policy_source = None
    if (sources.policy_universe is not None and policy_comp.readings
            and not policy_space_open and _universe_covers(policy_comp, sources)):
        policy_closed = True
        policy_source = getattr(sources.policy_universe, "source_id", "authoritative-universe")
    policy_complete = bool(policy_comp.readings) and not policy_space_open
    goal_closed = (sources.goal_closure is not None and not goal_space_open
                   and _goal_closure_covers(goal_comp, sources))
    goal_complete = bool(goal_comp.contracts) and not goal_space_open

    # ---- claim axes (baseline machinery) ----
    authorities = []
    groups, bindings = claim_axes(semantic.claim_graph, ledger, index, hard_reasons,
                                  reasons, authorities)
    for failure_reason in (reason for _, reason in semantic.claim_graph.failures):
        hard_reasons.append(failure_reason)

    policy_axis_source = (policy_source if policy_closed else
                          "grounded finite policy readings:" + digest(
                              [_serialize_reading(r) for r in policy_comp.readings])
                          if policy_complete else None)
    goal_axis_source = ("authoritative-goal-closure" if goal_closed else
                        "grounded finite goal contracts:" + digest(
                            [_serialize_contract(c) for c in goal_comp.contracts])
                        if goal_complete else None)
    axes, worlds, required_worlds = assemble_worlds(
        policy_choices, goal_choices, groups, hard_reasons, max_worlds,
        policy_complete, goal_complete, policy_axis_source, goal_axis_source)
    if required_worlds > max_worlds:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    problem = ProofProblem(tuple(axes), tuple(worlds))

    # ---- solve + certificate ----
    solver_result = solve(problem, ledger, registry)
    if policy_closed:
        authorities.append(AuthoritativeAxis("policy",
            tuple(choice.choice_id for choice in policy_choices), policy_source,
            "AUTHORITATIVE_CLOSED_UNIVERSE"))
    elif policy_complete:
        authorities.append(AuthoritativeAxis("policy",
            tuple(choice.choice_id for choice in policy_choices),
            "grounded finite policy readings:" + digest([_serialize_reading(r) for r in policy_comp.readings]),
            "EMPIRICAL_CANDIDATE_SET"))
    if goal_closed:
        authorities.append(AuthoritativeAxis("goal",
            tuple(choice.choice_id for choice in goal_choices), "authoritative-goal-closure",
            "AUTHORITATIVE_CLOSED_UNIVERSE"))
    elif goal_complete:
        authorities.append(AuthoritativeAxis("goal",
            tuple(choice.choice_id for choice in goal_choices),
            "grounded finite goal contracts:" + digest([_serialize_contract(c) for c in goal_comp.contracts]),
            "EMPIRICAL_CANDIDATE_SET"))
    from ..types import EvaluationHypothesis
    hypotheses = tuple(
        EvaluationHypothesis(choice.choice_id, "policy" if choice.choice_id.startswith("policy:") else "goal",
                             "PROHIBITION", "assistant", choice.choice_id, None, (), (),
                             ()) for choice in (*policy_choices, *goal_choices))[:0]  # e2e choices are not baseline hypotheses
    prompt = render_prompt(sources)
    response = render_response(sources)
    context_cert = E2ECertificateContext(
        prompt, response, sources.tool_metadata(), semantic.claim_graph.claims,
        tuple(authorities), hypotheses, sources.policy_text,
        "\n".join(source.text for source in sources.user_sources), (), sources.tool_names,
        (), e2e_policy_readings=tuple(_serialize_reading(reading) for reading in policy_comp.readings),
        e2e_goal_contracts=tuple(_serialize_contract(contract) for contract in goal_comp.contracts),
        e2e_binding=_serialize_binding(semantic.binding),
        e2e_lowering_inputs={"target_calls": [dict(call) for call in target_calls],
                             "all_calls": [dict(call) for call in all_calls],
                             "end_index": len(ledger.events) - 1},
        e2e_arm=arm, e2e_case_id=sources.case_id,
        e2e_choice_audits=tuple((choice.choice_id, choice.audit)
                                for choice in (*policy_choices, *goal_choices)))
    certificate = make_e2e_certificate(solver_result, problem, ledger, registry,
                                       context=context_cert)
    checked = check_certificate_e2e(certificate, context_cert, problem, ledger, registry) \
        if certificate else None
    status = solver_result.status
    merged_reasons = tuple(dict.fromkeys((*reasons, *solver_result.reasons)))
    missing = (f"WORLD_BUDGET_EXCEEDED:{required_worlds}>{max_worlds}",) if required_worlds > max_worlds else ()
    if checked and not checked.valid:
        status = CoreStatus.UNRESOLVED
        merged_reasons = (*merged_reasons, Reason.EVIDENCE_INCOMPLETE)
        missing = (*missing, *checked.errors)
        certificate = None
    from ..types import Diagnostics
    if status is CoreStatus.UNRESOLVED and not merged_reasons:
        merged_reasons = (Reason.EVIDENCE_INCOMPLETE,)
    diagnostics = Diagnostics(merged_reasons[0] if merged_reasons else None,
                              merged_reasons[1:], (), (), missing)
    result = CertifiedCoreResult(status, solver_result.world_proofs, certificate, checked, diagnostics)
    decision = adapt(result, mode=adapter_mode)
    return E2EAnalysisResult(arm, sources.case_id, result, decision, problem, context_cert,
                             required_worlds, policy_comp, goal_comp,
                             {"policy_agreement": policy_comp.agreement,
                              "goal_agreement": goal_comp.agreement,
                              "policy_choices": len(policy_choices),
                              "goal_choices": len(goal_choices),
                              "target_calls": len(target_calls)})


def _universe_covers(policy_comp: PolicyComposition, sources: E2ECaseSources) -> bool:
    """Closure premise: every retained reading composes to exactly the
    authoritative closed program list's behavior on the combined
    distinguishing-world surface (spec sections 101-102)."""
    from .policy_composition_v1 import _equivalence_surface, _reading_verdicts
    universe = sources.policy_universe
    if universe is None:
        return False
    universe_programs = list(getattr(universe, "programs", ()) or ())
    if not universe_programs:
        return False
    readings = list(policy_comp.readings)
    surface = _equivalence_surface(
        [type("R", (), {"programs": tuple(universe_programs), "reading_id": "universe"})]
        + readings, sources.atom_catalog)
    universe_verdicts = _reading_verdicts(tuple(universe_programs), surface)
    for reading in readings:
        if _reading_verdicts(reading.programs, surface) != universe_verdicts:
            return False
    return True


def _goal_closure_covers(goal_comp, sources: E2ECaseSources) -> bool:
    """Goal closure premise: an authoritative goal contract is supplied and
    every retained contract is behaviorally identical to it (spec §153)."""
    closure = sources.goal_closure
    if closure is None:
        return False
    from .goal_composition_v1 import _obligation_surface
    try:
        closure_surface = _obligation_surface(closure)
    except Exception:
        return False
    return all(_obligation_surface(contract) == closure_surface
               for contract in goal_comp.contracts)
