"""E2E V1 world integration: axes -> exact Cartesian worlds -> ProofProblem.

Worlds are the full Cartesian product over (spec sections 90-93):
  policy axis  (retained policy readings x atom-binding combos)
  goal axis    (retained goal contracts)
  claim axes   (per-claim binding alternatives, baseline machinery)
No top-k: budget overflow -> WORLD_BUDGET_EXCEEDED -> UNRESOLVED.

Obligations of a world = the union of the chosen options' obligations.
Unresolved markers of a world = the chosen options' markers + global hard
reasons (claim failures, unbound claims, policy/goal component failures).
An independent certified violation in a world survives unrelated UNKNOWN
markers (baseline solver conjunction semantics — spec section 96).

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from dataclasses import dataclass
from itertools import product
from math import prod

from ..proof_records import InterpretationAxis, Obligation, ProofProblem, WorldPlan
from ..types import ClaimKind, Disposition, Reason
from .goal_types_v1 import BindingRecord
from .policy_lowering_v1 import LoweredChoice, LoweringContext, lower_policy_reading
from .goal_lowering_v1 import lower_goal_contract


@dataclass(frozen=True)
class E2EAxisChoice:
    """One choice on the policy or goal axis: a lowered obligation set."""

    choice_id: str
    obligations: tuple[Obligation, ...]
    unresolved_reasons: tuple[Reason, ...]
    audit: tuple[tuple[str, str], ...]


@dataclass(frozen=True)
class E2EWorldAssembly:
    problem: ProofProblem
    required_worlds: int
    policy_choices: tuple[E2EAxisChoice, ...]
    goal_choices: tuple[E2EAxisChoice, ...]
    claim_choice_map: dict


def binding_combos(binding: BindingRecord, relevant_atoms: tuple[str, ...]) -> tuple[dict, ...]:
    """Candidate-index combinations over the relevant catalog atoms.
    Most atoms have exactly one candidate; only genuine ambiguities branch."""
    axes = [(atom, tuple(range(len(binding.atom_candidates(atom)))))
            for atom in relevant_atoms if len(binding.atom_candidates(atom)) > 1]
    if not axes:
        return ({},)
    combos = []
    for combination in product(*(options for _, options in axes)):
        combos.append({atom: combination[i] for i, (atom, _) in enumerate(axes)})
    return tuple(combos)


def combo_binding_view(binding: BindingRecord, combo: dict) -> BindingRecord:
    """A single-candidate view of the binding record for one combo."""
    from .goal_types_v1 import AtomBindingCandidate, BindingRecord as _BR
    pairs = []
    for unit, candidates in binding.atom_bindings:
        if unit in combo:
            pairs.append((unit, (candidates[combo[unit]],)))
        else:
            pairs.append((unit, candidates))
    return _BR(tuple(pairs), binding.outcome_bindings, binding.unbound_units,
               binding.failures)


def lower_policy_choices(readings, binding: BindingRecord, context: LoweringContext
                         ) -> tuple[E2EAxisChoice, ...]:
    """Flatten (reading x binding-combo) into policy axis choices."""
    relevant = tuple(dict.fromkeys(
        atom for reading in readings
        for program in reading.programs
        for clause in program["target_clauses"]
        for literal in clause
        for atom in (literal[1:] if literal.startswith("!") else literal,)))
    relevant = tuple(atom for atom in relevant
                     if len(binding.atom_candidates(atom)) > 1)
    choices = []
    for reading in readings:
        for combo in binding_combos(binding, relevant):
            view = combo_binding_view(binding, combo)
            lowered = lower_policy_reading(reading, view, context)
            signature = "|".join(f"{atom}:{index}" for atom, index in sorted(combo.items()))
            choice_id = reading.reading_id + (f"|bind[{signature}]" if signature else "")
            choices.append(E2EAxisChoice(choice_id, lowered.obligations,
                                         lowered.unresolved_reasons, lowered.audit))
    return tuple(choices)


def lower_goal_choices(contracts, binding: BindingRecord, context: LoweringContext
                       ) -> tuple[E2EAxisChoice, ...]:
    choices = []
    for contract in contracts:
        lowered = lower_goal_contract(contract, binding, context)
        choices.append(E2EAxisChoice(contract.contract_id, lowered.obligations,
                                     lowered.unresolved_reasons, lowered.audit))
    return tuple(choices)


def claim_axes(graph, ledger, index, hard_reasons, reasons, authorities):
    """Per-claim binding axes — the baseline core machinery, replicated
    verbatim in behavior (factual-consistency obligations + completeness
    flags + EXPLICIT_SOURCE_IDENTITY authorities for closed bindings)."""
    from ..binder import bind_claim
    from ..certificates import AuthoritativeAxis
    from ..proof_records import AtomKind, ProofAtom, TimeMode

    mapping = {ClaimKind.STATE: AtomKind.OBSERVED_STATE, ClaimKind.ATTRIBUTION: AtomKind.RESULT_FIELD,
               ClaimKind.ACTION_COMPLETED: AtomKind.ACTION_COMPLETED, ClaimKind.ABSENCE: AtomKind.HISTORICAL_ACTION}
    bindings, groups = [], []
    for claim in graph.claims:
        if claim.disposition is Disposition.NON_VERIFIABLE:
            continue
        if (claim.disposition is Disposition.UNKNOWN_SEMANTICS or claim.kind not in mapping
                or claim.modality not in {"ASSERTED", "REPORTED"}):
            hard_reasons.append(Reason.CAUSALITY_UNPROVED if claim.kind is ClaimKind.CAUSAL_ATTRIBUTION
                                else Reason.CLAIM_UNTYPED)
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
                             claim.predicate, "false" if claim.polarity == "NEGATIVE" else "true",
                             claim.actor, TimeMode.THROUGH if action and binding.time_index is None else TimeMode.AT, time)
            options[cid] = (Obligation(claim.claim_id + f":factual:{i}",
                                       "GUARDIAN_FACTUAL_CONSISTENCY_V1", claim.claim_id,
                                       atom, True),)
        if not options:
            options[claim.claim_id + ":unbound"] = ()
        source = "enumerated exact supplied-source identities:" + claim.claim_id
        complete = bool(binding.alternatives)
        groups.append((InterpretationAxis(claim.claim_id, tuple(options),
                                          source if complete else None, complete), options))
        if complete:
            authorities.append(AuthoritativeAxis(claim.claim_id, tuple(options), source,
                                                 "EXPLICIT_SOURCE_IDENTITY"))
    return groups, bindings


def assemble_worlds(policy_choices, goal_choices, claim_groups, hard_reasons,
                    max_worlds: int, policy_complete: bool, goal_complete: bool,
                    policy_source: str | None, goal_source: str | None):
    """Exact Cartesian product over all axes; budget overflow is terminal."""
    axes, options_by_group = [], []
    if policy_choices:
        axis = InterpretationAxis("policy", tuple(choice.choice_id for choice in policy_choices),
                                  policy_source, policy_complete)
        axes.append(axis)
        options_by_group.append({choice.choice_id: choice.obligations for choice in policy_choices})
    if goal_choices:
        axis = InterpretationAxis("goal", tuple(choice.choice_id for choice in goal_choices),
                                  goal_source, goal_complete)
        axes.append(axis)
        options_by_group.append({choice.choice_id: choice.obligations for choice in goal_choices})
    for axis, options in claim_groups:
        axes.append(axis)
        options_by_group.append(options)

    required_worlds = prod(len(axis.choice_ids) for axis in axes) if axes else 1
    worlds = []
    if required_worlds <= max_worlds:
        for i, choices in enumerate(product(*(axis.choice_ids for axis in axes))):
            obligations, markers = [], []
            for options, cid in zip(options_by_group, choices):
                obligations.extend(options[cid])
            # choice-level unresolved markers travel with the chosen options
            for group_choices, cid in zip(options_by_group, choices):
                for choice in (*policy_choices, *goal_choices):
                    if choice.choice_id == cid and choice.unresolved_reasons:
                        markers.extend(choice.unresolved_reasons)
            worlds.append(WorldPlan(f"world:{i}", choices, tuple(obligations),
                                    tuple(dict.fromkeys((*hard_reasons, *markers)))))
    return axes, worlds, required_worlds
