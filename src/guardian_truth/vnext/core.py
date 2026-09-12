"""One auditable frontend -> evidence -> all-world proof -> adapter entry point.

No implicit API client is constructed here. Supply a semantic backend explicitly.
Unsupported semantic lowering remains terminal UNRESOLVED, not binary safety.
"""

from dataclasses import dataclass, field, replace
from itertools import product
from math import prod

from .adapters import AdapterMode, ProductDecision, adapt
from .binder import ClaimBinding, bind_claim
from .certificates import AuthoritativeAxis, CertificateContext
from .claims import ClaimGraph, build_claim_graph
from .decision import CertifiedCoreResult, decide
from .escalation import EscalationState, escalate
from .goals import GoalPlanHypotheses, parse_goal_plan
from .grounding import bind_evaluation_hypothesis
from .integrity import canonical, digest
from .ledger import EvidenceLedger, LedgerIndex
from .normalize import normalize
from .operational_records import OperationalBindings
from .policy import ClosedUniverse, PolicyHypotheses, parse_policy
from .proof_records import AtomKind, InterpretationAxis, Obligation, ProofAtom, ProofProblem, TimeMode, WorldPlan
from .semantic import SemanticBackend
from .tools import ContractRegistry, ToolSemantics, evaluate_t1, propose_t2
from .types import ClaimKind, CoverageStatus, Disposition, Reason, ToolIdentity


@dataclass(frozen=True)
class AnalysisInput:
    prompt: str
    response: str
    policy: str = ""
    declared_goal: str = ""
    ordered_plan: tuple[str, ...] = ()
    allowed_scope: dict = field(default_factory=dict)
    history: tuple[dict, ...] = ()
    target_action: dict | None = None
    tool_metadata: tuple[ToolIdentity, ...] = ()
    tool_schemas: tuple[dict, ...] = ()
    history_complete: bool = False
    completeness_basis: str | None = None


@dataclass(frozen=True)
class CoreAnalysis:
    result: CertifiedCoreResult
    product_decision: ProductDecision
    ledger: EvidenceLedger
    claim_graph: ClaimGraph
    policy: PolicyHypotheses | None
    goal_plan: GoalPlanHypotheses | None
    operational_bindings: tuple[OperationalBindings, ...]
    claim_bindings: tuple[ClaimBinding, ...]
    tool_semantics: tuple[tuple[str, ToolSemantics], ...]
    problem: ProofProblem
    context: CertificateContext
    terminal_unresolved: bool
    world_count_required: int


def analyze(data: AnalysisInput, backend: SemanticBackend, *, registry: ContractRegistry | None = None,
            policy_universe: ClosedUniverse | None = None, enable_t2: bool = True,
            adapter_mode: AdapterMode = AdapterMode.AUDIT, max_worlds: int = 4096,
            escalation_callbacks: dict | None = None, max_escalation_steps: int = 0) -> CoreAnalysis:
    if type(max_worlds) is not int or max_worlds < 1:
        raise ValueError("positive material-world computation budget required")
    registry = registry if registry is not None else ContractRegistry(())
    ledger = EvidenceLedger.from_events(normalize(data.prompt, data.response, tool_identities=data.tool_metadata),
        history_complete=data.history_complete, completeness_basis=data.completeness_basis)
    source_index = LedgerIndex(ledger)
    semantics, effects = [], []
    schemas = {schema["name"]: schema for schema in data.tool_schemas if isinstance(schema.get("name"), str)}
    catalog = tuple(sorted(set(schemas) | {identity.name for identity in data.tool_metadata}
        | {event.tool.name for event in ledger.events if event.tool}))
    for result in ledger.events:
        if result.kind != "result" or not result.call_id:
            continue
        calls = [event for event in source_index.events_by_call.get(result.call_id, ()) if event.kind == "call"]
        if len(calls) != 1:
            continue
        call = calls[0]
        value = evaluate_t1(registry, call, result)
        if enable_t2 and call.tool and registry.lookup(call.tool) is None:
            value = propose_t2(call, result, backend, schema=schemas.get(call.tool.name, {}))
        effects.extend(value.effects)
        semantics.append((result.event_id, value))
    ledger = replace(ledger, effects=tuple(effects))
    index = LedgerIndex(ledger)
    graph = build_claim_graph(data.response, backend)
    policy = parse_policy(data.policy, backend, universe=policy_universe,
        context={"tool_schemas": list(data.tool_schemas)}) if data.policy else None
    goals = parse_goal_plan(data.declared_goal, data.ordered_plan, backend, history=data.history,
        target_action=data.target_action, allowed_scope=data.allowed_scope) if data.declared_goal or data.ordered_plan else None
    goal_text = data.declared_goal + "\n" + "\n".join(data.ordered_plan)
    if data.allowed_scope:
        goal_text += "\nEXPLICIT_ALLOWED_SCOPE=" + canonical(data.allowed_scope).decode("utf-8")
    hypotheses = (policy.hypotheses if policy else ()) + (
        tuple(reading.hypothesis for reading in goals.readings) if goals else ())
    operational, authorities, scopes = [], [], []
    # Each group is a semantic axis. Each option carries its obligations.
    groups = []
    reasons = [reason for _, reason in graph.failures]
    hard_reasons = list(reasons)
    for name, parsed, parent_hypotheses, text, scope in (
        ("policy", policy, policy.hypotheses if policy else (), data.policy, {}),
        ("goal_plan", goals, tuple(reading.hypothesis for reading in goals.readings) if goals else (), goal_text, data.allowed_scope)):
        if parsed is None:
            cid = name + ":not_present"
            groups.append((InterpretationAxis(name, (cid,), "explicit input: " + cid, True), {cid: ()}))
            authorities.append(AuthoritativeAxis(name, (cid,), "explicit input: " + cid, "EXPLICIT_STRUCTURED_ABSENCE"))
            continue
        component_reasons = list(parsed.failures)
        if parsed.coverage.status is CoverageStatus.OPEN_SEMANTICS:
            component_reasons.append(Reason.POLICY_OPEN_SEMANTICS if name == "policy" else Reason.GOAL_PLAN_AMBIGUOUS)
        options = {}
        for hyp in parent_hypotheses:
            scopes.append((hyp.hypothesis_id, canonical(scope).decode("utf-8")))
            binding = bind_evaluation_hypothesis(hyp, backend, normative_text=text, ledger=ledger,
                tool_catalog=catalog, allowed_scope=scope)
            operational.append(binding)
            component_reasons.extend(binding.failures)
            for choice in binding.choices:
                options[choice.choice_id] = tuple(Obligation(choice.choice_id + f":o{i}", choice.choice_id,
                    None, atom, choice.must_be_true) for i, atom in enumerate(choice.atoms))
        if not options:
            options[name + ":unbound"] = ()
        hard_reasons.extend(component_reasons)
        reasons.extend(component_reasons)
        source = "grounded finite semantic candidates:" + digest({"component": name, "options": list(options)})
        complete = not component_reasons
        groups.append((InterpretationAxis(name, tuple(options), source if complete else None, complete), options))
        if complete:
            # Even closed parent meaning does not authorize guessed tool/field aliases.
            authorities.append(AuthoritativeAxis(name, tuple(options), source, "EMPIRICAL_CANDIDATE_SET"))
    if policy is None and goals is None:
        hard_reasons.append(Reason.POLICY_NO_INTERPRETATION)
    bindings = []
    mapping = {ClaimKind.STATE: AtomKind.OBSERVED_STATE, ClaimKind.ATTRIBUTION: AtomKind.RESULT_FIELD,
        ClaimKind.ACTION_COMPLETED: AtomKind.ACTION_COMPLETED, ClaimKind.ABSENCE: AtomKind.HISTORICAL_ACTION}
    for claim in graph.claims:
        if claim.disposition is Disposition.NON_VERIFIABLE:
            continue
        if claim.disposition is Disposition.UNKNOWN_SEMANTICS or claim.kind not in mapping or claim.modality not in {"ASSERTED", "REPORTED"}:
            hard_reasons.append(Reason.CAUSALITY_UNPROVED if claim.kind is ClaimKind.CAUSAL_ATTRIBUTION else Reason.CLAIM_UNTYPED)
            continue
        binding = bind_claim(claim, ledger, index)
        bindings.append(binding)
        reasons.extend(binding.reasons)
        if not binding.alternatives:
            hard_reasons.append(Reason.ENTITY_UNBOUND)
        if Reason.SOURCE_UNBOUND in binding.reasons:
            hard_reasons.append(Reason.SOURCE_UNBOUND)
        action = claim.kind in {ClaimKind.ACTION_COMPLETED, ClaimKind.ABSENCE}
        if not action and binding.time_index is None or action and claim.time_anchor not in {"PAST", "ALL_HISTORY", "NOW"} and binding.time_index is None:
            hard_reasons.append(Reason.TIME_UNBOUND)
        options = {}
        for i, alternative in enumerate(binding.alternatives):
            cid = claim.claim_id + f":binding:{i}"
            time = binding.time_index if binding.time_index is not None else len(ledger.events) - 1
            atom = ProofAtom(claim.claim_id + f":atom:{i}", mapping[claim.kind], alternative.entity,
                claim.predicate, "false" if claim.polarity == "NEGATIVE" else "true", claim.actor,
                TimeMode.THROUGH if action and binding.time_index is None else TimeMode.AT, time)
            options[cid] = (Obligation(claim.claim_id + f":factual:{i}",
                "GUARDIAN_FACTUAL_CONSISTENCY_V1", claim.claim_id, atom, True),)
        if not options:
            options[claim.claim_id + ":unbound"] = ()
        source = "enumerated exact supplied-source identities:" + claim.claim_id
        complete = bool(binding.alternatives)
        groups.append((InterpretationAxis(claim.claim_id, tuple(options), source if complete else None, complete), options))
        if complete:
            authorities.append(AuthoritativeAxis(claim.claim_id, tuple(options), source, "EXPLICIT_SOURCE_IDENTITY"))
    # Possible effect proposals are retained as worlds but never inserted as facts.
    for eid, value in semantics:
        if not value.effects:
            continue
        alternatives = tuple(effect.effect_id for effect in value.effects if not effect.contract_sha256)
        if alternatives:
            name, source = "effect:" + eid, "nontrusted grounded T2 candidates:" + eid
            groups.append((InterpretationAxis(name, alternatives, source, True), {cid: () for cid in alternatives}))
            authorities.append(AuthoritativeAxis(name, alternatives, source, "EMPIRICAL_CANDIDATE_SET"))
    axes = tuple(axis for axis, _ in groups)
    required_worlds = prod(len(axis.choice_ids) for axis in axes)
    worlds = []
    if required_worlds <= max_worlds:
        for i, choices in enumerate(product(*(axis.choice_ids for axis in axes))):
            obligations = tuple(ob for (_, options), cid in zip(groups, choices) for ob in options[cid])
            worlds.append(WorldPlan(f"world:{i}", choices, obligations, tuple(dict.fromkeys(hard_reasons))))
    else:
        # No top-k truth: stop rather than evaluate an unrepresentative subset.
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    problem = ProofProblem(axes, tuple(worlds))
    context = CertificateContext(data.prompt, data.response, data.tool_metadata, graph.claims,
        tuple(authorities), hypotheses, data.policy, goal_text,
        tuple(choice for binding in operational for choice in binding.choices), catalog, tuple(scopes))
    result = decide(problem, ledger, registry, context=context, semantic_reasons=tuple(dict.fromkeys(reasons)),
        missing_evidence=(f"WORLD_BUDGET_EXCEEDED:{required_worlds}>{max_worlds}",) if required_worlds > max_worlds else ())
    outcome = escalate(EscalationState(problem, ledger, registry, context, result),
        escalation_callbacks or {}, max_steps=max_escalation_steps)
    state = outcome.state
    return CoreAnalysis(state.result, adapt(state.result, mode=adapter_mode), state.ledger, graph, policy, goals,
        tuple(operational), tuple(bindings), tuple(semantics), state.problem, state.context,
        outcome.terminal_unresolved, required_worlds)
