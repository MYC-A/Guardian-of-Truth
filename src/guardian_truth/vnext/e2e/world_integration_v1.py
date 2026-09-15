"""E2E world integration (spec 91-101): axes, exact Cartesian worlds, per-world
local verdicts and all-world aggregation.

Semantics fixed by the E2E V1 contract:
* A certified FALSE safety witness in a world makes that world ERROR even when
  unrelated obligations are UNKNOWN (spec 96, 100) - an independent proved
  violation is never masked by unrelated uncertainty.
* Any UNKNOWN safety conjunct (unresolved marker, unbound reading part,
  unknown prerequisite) blocks PROVED_NO_ERROR but never manufactures an error
  (spec 97, 101).
* PROVED_NO_ERROR additionally requires closure premises in the certificate.
* Exact Cartesian product over the material axes; world budget exceeded means
  UNRESOLVED, never a top-k subset (spec 92, 93).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from math import prod

from ..integrity import canonical, digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..proof_evidence import prove_atom
from ..proof_records import (AtomKind, InterpretationAxis, PrimitiveProof, ProofAtom, ProofProblem,
                             TimeMode, WorldPlan, WorldProof, conjunction, disjunction, negate)
from ..solver import world_space_complete
from ..tools import ContractRegistry
from ..types import CoreStatus, Reason, Truth, consensus
from .e2e_types_v1 import DisjunctiveGroup, ReadingOption, UnresolvedMarker

WORLD_INTEGRATION_VERSION = "world_integration_e2e_v1"


@dataclass(frozen=True)
class Component:
    """One material interpretation axis and its options."""
    axis: InterpretationAxis
    options: dict


@dataclass(frozen=True)
class E2EWorld:
    world_id: str
    choices: tuple[str, ...]
    obligations: tuple
    groups: tuple[DisjunctiveGroup, ...]
    markers: tuple[UnresolvedMarker, ...]


@dataclass(frozen=True)
class E2EProblem:
    axes: tuple[InterpretationAxis, ...]
    worlds: tuple[E2EWorld, ...]
    problems: tuple[WorldPlan, ...]          # certificate-facing projection (regular obligations)
    side_sha256: str                         # hash of groups+markers per world

    def as_problem(self) -> ProofProblem:
        return ProofProblem(self.axes, self.problems)


@dataclass(frozen=True)
class E2ESolverResult:
    status: CoreStatus
    world_proofs: tuple[WorldProof, ...]
    reasons: tuple[Reason, ...]
    required_worlds: int
    budget_exceeded: bool


def prove_e2e_atom(atom: ProofAtom, ledger: EvidenceLedger, index: LedgerIndex,
                   registry: ContractRegistry) -> PrimitiveProof:
    """Deterministic primitive proofs. Atoms in the reserved 'e2e' entity
    namespace use the deterministic prerequisite/existential evaluator:
    assistant-call search by exact tool name and entity-value overlap, with
    absence proven ONLY under a complete supplied history and no
    unknown-actor/unpaired events. Everything else delegates to the baseline
    prove_atom (shared by solver and checker), with one deterministic E2E
    refinement for state atoms: when trusted evidence for the same predicate
    both supports and refutes the expectation with NO attempted call between
    the two evidence points, the atom is BOTH (a trusted contradiction in one
    material scope, spec 103) instead of silently resolving to the latest."""
    if atom.entity.namespace in {"e2e", "e2e-state"} and atom.kind in {AtomKind.CALL_ATTEMPTED, AtomKind.HISTORICAL_ACTION}:
        return _prove_deterministic_action_atom(atom, ledger)
    proof = prove_atom(atom, ledger, index, registry, ())
    if (atom.kind in {AtomKind.OBSERVED_STATE, AtomKind.RESULT_FIELD}
            and atom.time_mode is TimeMode.LATEST_OBSERVATION
            and proof.value in {Truth.TRUE, Truth.FALSE}):
        return _both_aware_state_proof(atom, ledger, index, registry, proof)
    return proof


def _both_aware_state_proof(atom, ledger, index, registry, proof):
    from ..proof_evidence import effect_is_verified
    matching = [item for eid in index.search(entity=atom.entity, time_range=(0, atom.time_index)).event_ids
                for item in index.observations_by_event.get(eid, ())
                if atom.entity in item.entity_refs and item.predicate == atom.predicate]
    matching_effects = [effect for effect in index.effects_by_entity.get(atom.entity, ())
                        if index.positions[effect.event_id] <= atom.time_index
                        and effect.predicate == atom.predicate
                        and effect_is_verified(effect, ledger, index, registry)]
    support, refute = [], []
    for item in matching:
        try:
            actual = json.loads(item.value_json)
        except (ValueError, TypeError):
            continue
        expected = _expected(atom)
        if type(actual) is type(expected):
            (support if actual == expected else refute).append(item.evidence_id)
    for effect in matching_effects:
        (support if effect.value_json == atom.expected_json else refute).append(effect.effect_id)
    evidence_indexes = sorted({*(item.index for item in matching),
                               *(index.positions[effect.event_id] for effect in matching_effects)})
    if len(evidence_indexes) < 2 or not support or not refute:
        return proof
    low, high = evidence_indexes[0], evidence_indexes[-1]
    if any(low < event.index < high and event.kind == "call" for event in ledger.events):
        return proof  # a later attempted call may legitimately have changed the state
    return PrimitiveProof(atom, Truth.BOTH, tuple(support), tuple(refute))


def _parses(value_json):
    try:
        json.loads(value_json)
        return True
    except (ValueError, TypeError):
        return False


def _expected(atom):
    try:
        return json.loads(atom.expected_json)
    except (ValueError, TypeError):
        return None


def _prove_deterministic_action_atom(atom: ProofAtom, ledger: EvidenceLedger) -> PrimitiveProof:
    try:
        expected = json.loads(atom.expected_json)
    except (ValueError, TypeError):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.CLAIM_UNTYPED,))
    if type(expected) is not bool or atom.time_index < 0 or atom.time_index >= len(ledger.events):
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.TIME_UNBOUND,))
    calls = [event for event in ledger.events
             if event.kind == "call" and event.tool and event.tool.name == atom.predicate
             and event.actor == atom.actor and event.index <= atom.time_index]
    if atom.entity.value != "*":
        calls = [event for event in calls
                 if atom.entity.value in {ref.value for ref in event.entity_refs}]
    if calls:
        ids = tuple(event.event_id for event in calls)
        value = Truth.TRUE if expected else Truth.FALSE
        return PrimitiveProof(atom, value, ids if expected else (), () if expected else ids)
    # State-condition semantics: no call matches and the predicate matches an
    # observation field -> evaluate against the LATEST matching observation
    # (a stale observation never proves current state on its own).
    key_tokens = set(atom.predicate.split("_"))
    observations = [item for item in ledger.observations
                    if (item.predicate == atom.predicate or item.predicate in key_tokens)
                    and item.index <= atom.time_index
                    and (atom.entity.value == "*" or atom.entity.value in {ref.value for ref in item.entity_refs})]
    if observations:
        latest = max(item.index for item in observations)
        support, refute = [], []
        for item in [observation for observation in observations if observation.index == latest]:
            try:
                actual = json.loads(item.value_json)
            except (ValueError, TypeError):
                return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
            if type(actual) is type(expected):
                (support if actual == expected else refute).append(item.evidence_id)
        if support and refute:
            return PrimitiveProof(atom, Truth.BOTH, tuple(support), tuple(refute))
        if support:
            return PrimitiveProof(atom, Truth.TRUE, tuple(support), ())
        if refute:
            return PrimitiveProof(atom, Truth.FALSE, (), tuple(refute))
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    # No matching call and no matching observation. Absence of an ATTEMPT is
    # provable only for ACTION conditions (call semantics, namespace 'e2e')
    # on a complete supplied history with no unknown-actor/unpaired events;
    # STATE conditions stay UNKNOWN (an unobserved state is not a proven
    # false state).
    if atom.entity.namespace != "e2e":
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    for event in ledger.events[:atom.time_index + 1]:
        if event.actor == "unknown" or event.pairing_issue:
            return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    if not ledger.history_complete:
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    # Absence of an assistant attempt for this tool/entity within the prefix.
    return PrimitiveProof(atom, Truth.FALSE if expected else Truth.TRUE, (), ("absence:complete-history:" + atom.atom_id,))


def solve_world(world: E2EWorld, ledger: EvidenceLedger, index: LedgerIndex,
                registry: ContractRegistry) -> WorldProof:
    safety, primitives = [], []
    for obligation in world.obligations:
        condition_proofs = tuple(prove_e2e_atom(atom, ledger, index, registry)
                                 for atom in obligation.conditions)
        atom_proof = prove_e2e_atom(obligation.atom, ledger, index, registry)
        primitives.extend((*condition_proofs, atom_proof))
        antecedent = conjunction(tuple(proof.value for proof in condition_proofs))
        required = atom_proof.value if obligation.must_be_true else negate(atom_proof.value)
        safety.append((obligation.obligation_id, disjunction((negate(antecedent), required))))
    for group in world.groups:
        for event_id, atoms in group.per_call_atoms:
            proofs = tuple(prove_e2e_atom(atom, ledger, index, registry) for atom in atoms)
            primitives.extend(proofs)
            safety.append((f"{group.group_id}:{event_id}", disjunction(tuple(proof.value for proof in proofs))))
    for marker in world.markers:
        safety.append((marker.marker_id, Truth.UNKNOWN))
    error = negate(conjunction(tuple(value for _, value in safety)))
    return WorldProof(world.world_id, world.choices, error, tuple(safety), tuple(primitives))


def build_worlds(components: tuple[Component, ...], *, max_worlds: int) -> tuple[tuple[E2EWorld, ...], int, bool]:
    axes = tuple(component.axis for component in components)
    required = prod(len(axis.choice_ids) for axis in axes) if axes else 1
    if required > max_worlds or required == 0:
        return (), required, required > max_worlds
    worlds = []
    for i, choices in enumerate(product(*(component.axis.choice_ids for component in components))):
        obligations, groups, markers = [], [], []
        for component, choice in zip(components, choices):
            option = component.options[choice]
            obligations.extend(option.obligations)
            groups.extend(option.disjunctive_groups)
            markers.extend(option.unresolved_markers)
        worlds.append(E2EWorld(f"world:{i}", choices, tuple(obligations), tuple(groups),
                               tuple(dict.fromkeys(markers))))
    return tuple(worlds), required, False


def make_problem(components: tuple[Component, ...], worlds: tuple[E2EWorld, ...]) -> E2EProblem:
    axes = tuple(component.axis for component in components)
    plans = tuple(WorldPlan(world.world_id, world.choices, world.obligations) for world in worlds)
    side = [{"world_id": world.world_id,
             "groups": [[group.group_id, group.rule_id, group.must_be_true,
                         [[event_id, [canonical_atom(atom) for atom in atoms]]
                          for event_id, atoms in group.per_call_atoms]]
                        for group in world.groups],
             "markers": [[marker.marker_id, marker.reason] for marker in world.markers]}
            for world in worlds]
    return E2EProblem(axes, worlds, plans, digest(side))


def canonical_atom(atom: ProofAtom) -> dict:
    from dataclasses import asdict
    return asdict(atom)


def solve_e2e(problem: E2EProblem, ledger: EvidenceLedger, registry: ContractRegistry) -> E2ESolverResult:
    index = LedgerIndex(ledger)
    proofs = tuple(solve_world(world, ledger, index, registry) for world in problem.worlds)
    complete = world_space_complete(problem.as_problem()) if problem.worlds else False
    reasons = []
    if not problem.worlds:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    status = consensus(tuple(proof.error_value for proof in proofs), material_space_complete=complete)
    if status is CoreStatus.UNRESOLVED and not reasons:
        reasons.append(Reason.POLICY_AMBIGUOUS)
    return E2ESolverResult(status, proofs, tuple(dict.fromkeys(reasons)),
                           len(problem.worlds), False)
