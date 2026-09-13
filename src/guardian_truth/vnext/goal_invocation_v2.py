"""Runnable Native Goal invocation path with explicit backend and source contract.

This does not pretend to compose policy/claim/effect worlds into the full Core.
"""

from dataclasses import asdict, dataclass, field, replace

from .goal_bindings_v2 import GoalBindingCandidates, generate_goal_bindings
from .goal_formula import compile_goal_clause
from .goal_native import NativeGoalParse, parse_native_goal
from .goal_progress_v2 import PlanActivation
from .goal_interfaces_v2 import declared_interface
from .goal_proof_records_v2 import GoalLayerDecision, GoalProofContext
from .goal_solver_v2 import decide_goal_layer
from .integrity import canonical
from .ledger import EvidenceLedger, LedgerIndex
from .normalize import normalize
from .tools import ContractRegistry, evaluate_t1
from .types import CoreStatus, Diagnostics, Reason, ToolIdentity


@dataclass(frozen=True)
class GoalInvocationInput:
    prompt: str
    response: str
    declared_goal: str
    ordered_plan: tuple[str, ...] = ()
    allowed_scope: dict = field(default_factory=dict)
    tool_metadata: tuple[ToolIdentity, ...] = ()
    tool_schemas: tuple[dict, ...] = ()
    history_complete: bool = False
    completeness_basis: str | None = None
    plan_activation: PlanActivation | None = None


@dataclass(frozen=True)
class GoalInvocationAnalysis:
    decision: GoalLayerDecision
    diagnostics: Diagnostics
    parsed: NativeGoalParse
    binding_candidates: GoalBindingCandidates
    context: GoalProofContext
    ledger: EvidenceLedger


def analyze_goal_invocation(data, backend, *, registry=None, max_worlds=4096):
    registry = registry if registry is not None else ContractRegistry(())
    identities = {identity.name: identity for identity in data.tool_metadata}
    if len(identities) != len(data.tool_metadata):
        raise ValueError("ambiguous per-name source versions require explicit source resolution, not last-wins T1 transfer")
    for schema in data.tool_schemas:
        interface = declared_interface(schema)
        if interface is not None:
            # Interface identity only; no provider/version/hash => never T1.
            identities.setdefault(interface["name"], ToolIdentity(interface["name"]))
    metadata = tuple(identities[name] for name in sorted(identities))
    ledger = EvidenceLedger.from_events(normalize(data.prompt, data.response, tool_identities=metadata),
        history_complete=data.history_complete, completeness_basis=data.completeness_basis)
    index, effects = LedgerIndex(ledger), []
    for result in ledger.events:
        if result.kind != "result" or result.call_id is None:
            continue
        calls = [event for event in index.events_by_call.get(result.call_id, ()) if event.kind == "call"]
        if len(calls) == 1:
            effects.extend(evaluate_t1(registry, calls[0], result).effects)
    ledger = replace(ledger, effects=tuple(effects))
    target_calls = [event for event in ledger.events if event.source.document == "response" and event.kind == "call"]
    target = ({"name": target_calls[0].tool.name, "args": target_calls[0].payload, "actor": target_calls[0].actor}
              if len(target_calls) == 1 and target_calls[0].tool else None)
    parsed = parse_native_goal(data.declared_goal, data.ordered_plan, backend, allowed_scope=data.allowed_scope,
        history=tuple(asdict(event) for event in ledger.events if event.source.document == "prompt"), target_action=target)
    bindings = generate_goal_bindings(parsed, ledger, backend, tool_schemas=data.tool_schemas,
        tool_metadata=metadata, plan_activation=data.plan_activation, max_worlds=max_worlds)
    context = GoalProofContext(data.declared_goal, data.ordered_plan, canonical(data.allowed_scope).decode("utf-8"),
        data.prompt, data.response, metadata, parsed, bindings.choices,
        "all retained narrow source-owned empirical binding candidates; not unrestricted NL closure",
        bindings.candidate_enumeration_complete, plan_activation=data.plan_activation)
    decision = decide_goal_layer(context, ledger, registry, max_worlds=max_worlds)
    reasons = tuple(dict.fromkeys([reason for _, reason in parsed.failures] + [reason for _, reason in bindings.failures]
                                 + list(decision.reasons)))
    reading_by_id = {reading.reading_id: reading for reading in parsed.readings}
    unbound_roles = tuple(term for choice in bindings.choices
        for clause in reading_by_id[choice.reading_id].clauses
        for term in compile_goal_clause(clause, {(binding.source_id, binding.role): binding.atom
            for binding in choice.bindings}).unresolved_terms)
    missing_primitives = tuple("missing_primitive:" + primitive.atom.atom_id
        for world in decision.world_proofs for primitive in world.primitives if primitive.value.value == "UNKNOWN")
    missing = tuple(dict.fromkeys((*bindings.unresolved_terms, *decision.certificate_errors, *unbound_roles, *missing_primitives)))
    unresolved = decision.status in {CoreStatus.UNRESOLVED, CoreStatus.INCONSISTENT}
    diagnostics = Diagnostics(reasons[0] if reasons else None, reasons, (),
        tuple(reading.reading_id for reading in parsed.readings) if unresolved else (), missing, ())
    return GoalInvocationAnalysis(decision, diagnostics, parsed, bindings, context, ledger)
