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

Cycle-3 conservative state semantics (semantics.conservative_state, B1):
* Only trusted fresh state reads (T1 contract declaring no writes and
  fresh-read freshness) and verified trusted effects are STATE evidence for
  CURRENT-state atoms. Rows extracted from mutation results or uncontracted
  tools are operation outcomes, never entity-state refutations.
* support + refutation across time are HISTORICAL observations: a CURRENT
  contradiction (BOTH) exists only when the evidence refers to one material
  snapshot - same time, or only proven non-mutating calls in between (trusted
  persistence). When an attempted mutation with unproven effect separates the
  evidence points, the temporal relation is unknown -> UNKNOWN, never a
  definitive refutation (absence of an attempted mutation never proves state
  persistence without a trusted contract).
* A refutation that strictly precedes the last attempted mutation and is not
  superseded by later state evidence is stale -> UNKNOWN.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from itertools import product
from math import prod

from ..integrity import canonical, digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..proof_evidence import effect_is_verified, prove_atom
from ..proof_records import (AtomKind, InterpretationAxis, PrimitiveProof, ProofAtom, ProofProblem,
                             TimeMode, WorldPlan, WorldProof, conjunction, disjunction, negate)
from ..solver import world_space_complete
from ..tools import ContractRegistry
from ..types import CoreStatus, Reason, Truth, consensus
from .e2e_types_v1 import FULL_SEMANTICS, DisjunctiveGroup, E2ESemantics, ReadingOption, UnresolvedMarker

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


# ------------------------------------------------------- tool classification

def _pure_reader_event(event, registry: ContractRegistry) -> bool:
    """A result event is a trusted fresh state read when its tool carries a T1
    contract that declares NO writes at all and fresh-read freshness: every
    row it emits then observes entity state at read time. Mutation results
    (writers) and uncontracted tools are operation outcomes, not state reads."""
    if event.tool is None:
        return False
    contract = registry.lookup(event.tool)
    return (contract is not None and contract.writes == ()
            and contract.freshness == "fresh-read")


def _mutation_call_positions(ledger: EvidenceLedger, registry: ContractRegistry,
                             upto: int) -> list[int]:
    """Positions of ATTEMPTED MUTATIONS up to `upto`: any call whose tool is
    not a proven pure reader (a writer contract, an uncontracted tool, or an
    unparsed call) may have changed entity state; its effect is unproven
    unless a verified trusted effect supersedes it."""
    positions = []
    for event in ledger.events[:upto + 1]:
        if event.kind != "call":
            continue
        if event.tool is not None:
            contract = registry.lookup(event.tool)
            if contract is not None and contract.writes == ():
                continue  # a declared read-only tool cannot mutate
        positions.append(event.index)
    return positions


def _typed_value_match(actual_json: str, expected_json: str) -> tuple[bool, bool]:
    """(supports, refutes) of one evidence row against the atom expectation.

    Baseline rule: rows whose JSON type differs from the expectation carry no
    evidence about this atom. One representation-preserving literal coercion
    (claim_typing): an anchored string literal that is exactly the canonical
    JSON encoding of the observed number/boolean still supports/mismatches -
    a format repair that changes no semantic value."""
    if actual_json == expected_json:
        return True, False
    try:
        actual = json.loads(actual_json)
        expected = json.loads(expected_json)
    except (ValueError, TypeError):
        return False, False
    if type(actual) is type(expected):
        return actual == expected, actual != expected
    if isinstance(expected, str) and isinstance(actual, (int, float, bool)):
        encoded = canonical(actual).decode("utf-8")
        if expected == encoded:
            return True, False
        # a well-formed literal of the same type family still mismatches
        if isinstance(actual, bool) and expected in {"true", "false"}:
            return False, True
        if isinstance(actual, (int, float)) and _is_number_literal(expected):
            return False, True
    return False, False


def _is_number_literal(text: str) -> bool:
    try:
        json.loads(text)
        return True
    except (ValueError, TypeError):
        return False


def _expected_value(atom: ProofAtom):
    try:
        return json.loads(atom.expected_json)
    except (ValueError, TypeError):
        return None


def prove_e2e_atom(atom: ProofAtom, ledger: EvidenceLedger, index: LedgerIndex,
                   registry: ContractRegistry,
                   semantics: E2ESemantics = FULL_SEMANTICS) -> PrimitiveProof:
    """Deterministic primitive proofs. Atoms in the reserved 'e2e' entity
    namespace use the deterministic prerequisite/existential evaluator:
    assistant-call search by exact tool name and entity-value overlap, with
    absence proven ONLY under a complete supplied history and no
    unknown-actor/unpaired events. OBSERVED_STATE atoms with LATEST semantics
    use the cycle-3 conservative state semantics (which fully replaces the
    baseline observation proof for those atoms). Everything else delegates
    to the baseline prove_atom (shared by solver and checker)."""
    if atom.entity.namespace in {"e2e", "e2e-state"} and atom.kind in {AtomKind.CALL_ATTEMPTED, AtomKind.HISTORICAL_ACTION}:
        return _prove_deterministic_action_atom(atom, ledger)
    proof = prove_atom(atom, ledger, index, registry, ())
    if (semantics.conservative_state
            and atom.kind is AtomKind.OBSERVED_STATE
            and atom.time_mode is TimeMode.LATEST_OBSERVATION):
        return _conservative_state_proof(atom, ledger, index, registry, semantics)
    if (semantics.conservative_state
            and atom.kind is AtomKind.OBSERVED_STATE
            and atom.time_mode is TimeMode.THROUGH):
        return _historical_state_proof(atom, ledger, index, registry, semantics)
    return proof


def _flag_channel(atom: ProofAtom, semantics: E2ESemantics) -> str | None:
    """Flag-channel predicate for a value-anchored POSITIVE state claim: the
    business fact 'field P has value V' is equivalently encoded by this tool
    ecosystem as the boolean flag 'V is true' (T1 writes/observations use both
    encodings). Returns the flag predicate, or None when the expectation is
    not a single anchored literal token."""
    if not semantics.claim_typing:
        return None
    expected = _expected_value(atom)
    if not isinstance(expected, str) or not expected:
        return None
    token = expected.strip()
    if not token or " " in token or token.lower() in {"true", "false", "null"}:
        return None
    if token == atom.predicate:
        return None  # object merely echoes the predicate: no value information
    return token


def _collect_state_rows(atom, ledger, index, registry, semantics, flag_predicate):
    """Trusted state evidence rows for the atom: (position, evidence_id,
    value_json) from pure-reader observations and verified effects, on the
    field channel (predicate P) and, when enabled, the flag channel
    (predicate V, boolean value)."""
    rows = []
    seen_predicates = {atom.predicate}
    if flag_predicate is not None:
        seen_predicates.add(flag_predicate)
    for eid in index.search(entity=atom.entity, time_range=(0, atom.time_index)).event_ids:
        event = index.events_by_id[eid]
        if not _pure_reader_event(event, registry):
            continue
        for item in index.observations_by_event.get(eid, ()):
            if atom.entity in item.entity_refs and item.predicate in seen_predicates:
                rows.append((event.index, item.evidence_id, item.value_json,
                             item.predicate == flag_predicate if flag_predicate else False))
    for effect in index.effects_by_entity.get(atom.entity, ()):
        if index.positions[effect.event_id] > atom.time_index:
            continue
        if effect.predicate in seen_predicates and effect_is_verified(effect, ledger, index, registry):
            rows.append((index.positions[effect.event_id], effect.effect_id, effect.value_json,
                         effect.predicate == flag_predicate if flag_predicate else False))
    return rows


def _conservative_state_proof(atom, ledger, index, registry, semantics):
    """Cycle-3 conservative CURRENT-state semantics (see module docstring).
    Fully replaces the baseline proof for OBSERVED_STATE@LATEST atoms: no
    trusted state evidence at all means UNKNOWN (an operation-status row or
    an uncontracted tool's output never refutes an entity-state claim)."""
    expected_json = atom.expected_json
    flag_predicate = _flag_channel(atom, semantics)
    rows = _collect_state_rows(atom, ledger, index, registry, semantics, flag_predicate)
    support, refute, positions = [], [], {}
    for position, evidence_id, value_json, is_flag in rows:
        positions[evidence_id] = position
        if is_flag:
            supports, refutes = _flag_row_value(value_json)
        else:
            supports, refutes = _typed_value_match(value_json, expected_json)
        if supports:
            support.append(evidence_id)
        elif refutes:
            refute.append(evidence_id)
    if not support and not refute:
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))
    evidence_positions = sorted(set(positions.values()))
    latest = evidence_positions[-1]
    latest_support = [eid for eid in support if positions[eid] == latest]
    latest_refute = [eid for eid in refute if positions[eid] == latest]
    mutations = _mutation_call_positions(ledger, registry, atom.time_index)
    if latest_support and latest_refute:
        # same-time contradiction inside one material snapshot
        return PrimitiveProof(atom, Truth.BOTH, tuple(latest_support), tuple(latest_refute))
    if latest_refute:
        earlier_support = [eid for eid in support if positions[eid] < latest]
        if earlier_support:
            low = min(positions[eid] for eid in earlier_support)
            separating = [p for p in mutations if low < p < latest]
            if not separating:
                # only proven non-mutating calls between the evidence points:
                # trusted persistence - one material state, so BOTH
                return PrimitiveProof(atom, Truth.BOTH, tuple(support), tuple(refute))
            # an attempted mutation with unproven effect separates them: the
            # historical contradiction is explained; the freshest read wins.
            return PrimitiveProof(atom, Truth.FALSE, (), tuple(latest_refute))
        # no supporting evidence anywhere: a fresh refutation at the latest
        # evidence time is sound - unless it went stale behind the last
        # attempted mutation whose effect on this predicate is unproven.
        if mutations and latest < max(mutations):
            return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.TEMPORAL_AMBIGUITY,))
        return PrimitiveProof(atom, Truth.FALSE, (), tuple(latest_refute))
    # latest evidence supports the claim
    earlier_refute = [eid for eid in refute if positions[eid] < latest]
    if earlier_refute:
        low = min(positions[eid] for eid in earlier_refute)
        separating = [p for p in mutations if low < p < latest]
        if not separating:
            return PrimitiveProof(atom, Truth.BOTH, tuple(support), tuple(refute))
        # the mutation between explains the earlier refutation; the fresh
        # read at the latest position reports the current state.
        return PrimitiveProof(atom, Truth.TRUE, tuple(latest_support), ())
    return PrimitiveProof(atom, Truth.TRUE, tuple(latest_support), ())


def _historical_state_proof(atom, ledger, index, registry, semantics):
    """Historical existential state claim ('the status WAS cancelled'):
    TRUE when ANY trusted state evidence in the prefix shows the value;
    FALSE only when trusted evidence exists, NONE of it shows the value, and
    the supplied history is complete (an incomplete prefix can never refute
    a past state); UNKNOWN otherwise."""
    expected_json = atom.expected_json
    flag_predicate = _flag_channel(atom, semantics)
    rows = _collect_state_rows(atom, ledger, index, registry, semantics, flag_predicate)
    support, refute = [], []
    for _position, evidence_id, value_json, is_flag in rows:
        if is_flag:
            supports, _refutes = _flag_row_value(value_json)
        else:
            supports, _refutes = _typed_value_match(value_json, expected_json)
        if supports:
            support.append(evidence_id)
    if support:
        return PrimitiveProof(atom, Truth.TRUE, tuple(support), ())
    if rows and ledger.history_complete:
        return PrimitiveProof(atom, Truth.FALSE, (), tuple(evidence_id for _, evidence_id, _, _ in rows))
    return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))


def _flag_row_value(value_json: str) -> tuple[bool, bool]:
    """(supports, refutes) of a boolean flag row against a POSITIVE anchored
    claim: flag true supports, flag false refutes; non-boolean rows carry no
    evidence in the flag channel."""
    try:
        actual = json.loads(value_json)
    except (ValueError, TypeError):
        return False, False
    if type(actual) is bool:
        return actual, not actual
    return False, False


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
                registry: ContractRegistry,
                semantics: E2ESemantics = FULL_SEMANTICS) -> WorldProof:
    safety, primitives = [], []
    for obligation in world.obligations:
        condition_proofs = tuple(prove_e2e_atom(atom, ledger, index, registry, semantics)
                                 for atom in obligation.conditions)
        atom_proof = prove_e2e_atom(obligation.atom, ledger, index, registry, semantics)
        primitives.extend((*condition_proofs, atom_proof))
        antecedent = conjunction(tuple(proof.value for proof in condition_proofs))
        required = atom_proof.value if obligation.must_be_true else negate(atom_proof.value)
        value = disjunction((negate(antecedent), required))
        if (semantics.inconsistent_status and required is Truth.BOTH
                and antecedent is Truth.TRUE and value is Truth.TRUE):
            # contradictory trusted evidence about an applicable obligation:
            # the world verdict itself is BOTH, so consensus surfaces
            # INCONSISTENT instead of silently absorbing the contradiction
            # into a non-violation.
            value = Truth.BOTH
        safety.append((obligation.obligation_id, value))
    for group in world.groups:
        for event_id, atoms in group.per_call_atoms:
            proofs = tuple(prove_e2e_atom(atom, ledger, index, registry, semantics) for atom in atoms)
            primitives.extend(proofs)
            safety.append((f"{group.group_id}:{event_id}", disjunction(tuple(proof.value for proof in proofs))))
        if group.satisfaction_choices:
            choice_values = []
            for atoms in group.satisfaction_choices:
                proofs = tuple(prove_e2e_atom(atom, ledger, index, registry, semantics) for atom in atoms)
                primitives.extend(proofs)
                choice_values.append(conjunction(tuple(proof.value for proof in proofs)))
            safety.append((group.group_id, disjunction(tuple(choice_values))))
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
                          for event_id, atoms in group.per_call_atoms],
                         [[canonical_atom(atom) for atom in atoms]
                          for atoms in group.satisfaction_choices]]
                        for group in world.groups],
             "markers": [[marker.marker_id, marker.reason] for marker in world.markers]}
            for world in worlds]
    return E2EProblem(axes, worlds, plans, digest(side))


def canonical_atom(atom: ProofAtom) -> dict:
    from dataclasses import asdict
    return asdict(atom)


def solve_e2e(problem: E2EProblem, ledger: EvidenceLedger, registry: ContractRegistry,
              semantics: E2ESemantics = FULL_SEMANTICS) -> E2ESolverResult:
    index = LedgerIndex(ledger)
    proofs = tuple(solve_world(world, ledger, index, registry, semantics) for world in problem.worlds)
    complete = world_space_complete(problem.as_problem()) if problem.worlds else False
    reasons = []
    if not problem.worlds:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    status = consensus(tuple(proof.error_value for proof in proofs), material_space_complete=complete)
    if status is CoreStatus.UNRESOLVED and not reasons:
        reasons.append(Reason.POLICY_AMBIGUOUS)
    return E2ESolverResult(status, proofs, tuple(dict.fromkeys(reasons)),
                           len(problem.worlds), False)
