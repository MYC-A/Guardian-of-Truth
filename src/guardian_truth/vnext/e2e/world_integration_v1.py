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

Cycle-3 conservative state semantics (semantics.conservative_state, B1),
soundness-audit revision B4h-sound-v1 (pre-benchmark audit, SND-01..SND-09):
* Only trusted fresh state reads (T1 contract declaring no writes and
  fresh-read freshness, contract preconditions held) and verified trusted
  effects are STATE evidence for CURRENT-state atoms. Rows extracted from
  mutation results, uncontracted tools or failed reads are operation
  outcomes, never entity-state refutations.
* Observation rows bind to an entity only within their own JSON object
  scope (output-path entity alignment): an envelope field never refutes a
  nested entity's state, and a scope naming two distinct entities is not
  attributable at all (SND-03).
* Cross-time support + refutation are HISTORICAL observations. A CURRENT
  contradiction (BOTH) exists ONLY for a same-position (single-event
  snapshot) contradiction. Absence of intervening assistant mutations NEVER
  proves persistence - external actors are admissible - so a cross-time
  pair is decided by the freshest trusted evidence, never reported as a
  contradiction (SND-01).
* Staleness is symmetric (SND-02): ANY attempted mutation (non-pure-reader
  call) whose position is AFTER the latest trusted evidence makes the
  current state UNKNOWN, for support and refutation alike.
* A claim value token NEVER opens an evidence channel on a same-named
  boolean predicate: enum<->flag equivalence requires an explicit trusted
  declaration, which the current representation does not carry (SND-04).
* Historical (PAST/ALL_HISTORY) existentials are TRUE when any trusted
  evidence showed the value and UNKNOWN otherwise: refuting 'was never X'
  would require the complete state timeline, and history_complete certifies
  only the supplied trace (SND-06).
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
from ..tools import ContractRegistry, conditions_hold
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

def _pure_reader_event(event, index: LedgerIndex, registry: ContractRegistry) -> bool:
    """A result event is a trusted fresh state read when its tool carries a T1
    contract that declares NO writes at all and fresh-read freshness, AND the
    contract's preconditions held for this invocation (SND-05: a failed read
    did not observe anything; its payload is an operation outcome - the same
    trusted rule evaluate_t1 already applies to effects). Every row such a
    call emits then observes entity state at read time."""
    if event.tool is None or event.call_id is None or event.pairing_issue:
        return False
    contract = registry.lookup(event.tool)
    if contract is None or contract.writes != () or contract.freshness != "fresh-read":
        return False
    calls = [item for item in index.events_by_call.get(event.call_id, ()) if item.kind == "call"]
    if len(calls) != 1 or calls[0].tool != event.tool or calls[0].payload_json is None or event.payload_json is None:
        return False
    if event.call_candidates != (event.call_id,):
        return False
    sources = {"arguments": calls[0].payload, "result": event.payload, "prior_state": {}}
    return conditions_hold(contract.preconditions, sources)


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


def _object_scope(path: tuple[str, ...] | str) -> tuple[str, ...]:
    """JSON object scope of a dotted predicate/ref-key path: all segments
    except the leaf. Rows and entity refs from the same object share it."""
    parts = tuple(path.split(".")) if isinstance(path, str) else tuple(path)
    return tuple(parts[:-1]) if len(parts) > 1 else ()


def _row_binds_entity(row_predicate: str, row_refs, entity) -> bool:
    """SND-03: an observation row is entity-bound only within its own JSON
    object scope. The entity ref must be extracted from the same object as
    the row (output-path alignment, not event-level coincidence), and the
    scope must not name TWO distinct entities (such a row is not
    attributable to either: same predicate name does not mean same entity
    state)."""
    scope = _object_scope(row_predicate)
    in_scope = [ref for ref in row_refs if _object_scope(ref.key) == scope]
    return (entity in in_scope
            and len({(ref.namespace, ref.key, ref.value) for ref in in_scope}) <= 1)


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


def prove_e2e_atom(atom: ProofAtom, ledger: EvidenceLedger, index: LedgerIndex,
                   registry: ContractRegistry,
                   semantics: E2ESemantics = FULL_SEMANTICS) -> PrimitiveProof:
    """Deterministic primitive proofs. Atoms in the reserved 'e2e' entity
    namespace use the deterministic prerequisite/existential evaluator:
    assistant-call search by exact tool name and entity-value overlap, with
    absence proven ONLY under a complete supplied history and no
    unknown-actor/unpaired events; under conservative state semantics its
    observation fallback only consults TRUSTED state evidence (SND-09).
    OBSERVED_STATE atoms with LATEST semantics use the cycle-3 conservative
    state semantics (which fully replaces the baseline observation proof for
    those atoms). Everything else delegates to the baseline prove_atom
    (shared by solver and checker)."""
    if atom.entity.namespace in {"e2e", "e2e-state"} and atom.kind in {AtomKind.CALL_ATTEMPTED, AtomKind.HISTORICAL_ACTION}:
        return _prove_deterministic_action_atom(atom, ledger, index, registry, semantics)
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


def _collect_state_rows(atom, ledger, index, registry, semantics):
    """Trusted state evidence rows for the atom: (position, evidence_id,
    value_json) from pure-reader observations and verified effects on the
    field channel (predicate must equal the atom predicate exactly; the
    claim's value token opens no other channel, SND-04). Observation rows
    additionally bind to the atom entity only within their own JSON object
    scope (SND-03)."""
    rows = []
    for eid in index.search(entity=atom.entity, time_range=(0, atom.time_index)).event_ids:
        event = index.events_by_id[eid]
        if not _pure_reader_event(event, index, registry):
            continue
        for item in index.observations_by_event.get(eid, ()):
            if item.predicate != atom.predicate:
                continue
            if not _row_binds_entity(item.predicate, item.entity_refs, atom.entity):
                continue
            rows.append((event.index, item.evidence_id, item.value_json))
    for effect in index.effects_by_entity.get(atom.entity, ()):
        if index.positions[effect.event_id] > atom.time_index:
            continue
        if effect.predicate == atom.predicate and effect_is_verified(effect, ledger, index, registry):
            rows.append((index.positions[effect.event_id], effect.effect_id, effect.value_json))
    return rows


def _conservative_state_proof(atom, ledger, index, registry, semantics):
    """Conservative CURRENT-state semantics, soundness-audit revision
    (B4h-sound-v1; see module docstring). Fully replaces the baseline proof
    for OBSERVED_STATE@LATEST atoms: no trusted state evidence at all means
    UNKNOWN (an operation-status row, an uncontracted tool's output or a
    failed read never refutes an entity-state claim).

    Decision procedure:
    1. same-position support + refutation -> BOTH (one event, one material
       snapshot - a genuinely contradictory trusted read);
    2. any attempted mutation positioned AFTER the latest trusted evidence
       -> UNKNOWN (its effect on this predicate is unproven; staleness is
       symmetric for support and refutation, SND-02);
    3. otherwise the freshest trusted evidence decides the CURRENT claim
       (historical support/refutation on the other side is superseded, never
       a contradiction - SND-01)."""
    expected_json = atom.expected_json
    rows = _collect_state_rows(atom, ledger, index, registry, semantics)
    support, refute, positions = [], [], {}
    for position, evidence_id, value_json in rows:
        positions[evidence_id] = position
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
    if latest_support and latest_refute:
        # contradictory trusted rows inside ONE event (one material snapshot)
        return PrimitiveProof(atom, Truth.BOTH, tuple(latest_support), tuple(latest_refute))
    mutations = _mutation_call_positions(ledger, registry, atom.time_index)
    if mutations and latest < max(mutations):
        # the last attempted mutation's effect on this predicate is unproven
        # and no trusted evidence supersedes it: the current state is unknown.
        return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.TEMPORAL_AMBIGUITY,))
    if latest_refute:
        # freshest trusted evidence refutes; earlier support is a historical
        # observation (external actors are admissible; no persistence premise)
        return PrimitiveProof(atom, Truth.FALSE, (), tuple(latest_refute))
    # freshest trusted evidence supports; earlier refutations are historical
    return PrimitiveProof(atom, Truth.TRUE, tuple(latest_support), ())


def _historical_state_proof(atom, ledger, index, registry, semantics):
    """Historical existential state claim ('the status WAS cancelled'):
    TRUE when ANY trusted state evidence in the prefix shows the value.
    FALSE is NOT reachable in this representation (SND-06): refuting a past
    existential requires the COMPLETE STATE TIMELINE - every mutation of
    the entity, including external actors - while history_complete
    certifies only the completeness of the supplied trace (ledger.py:
    'relative to the supplied trace, never all external reality'). An
    exclusive-writer premise would be needed and none is representable."""
    expected_json = atom.expected_json
    rows = _collect_state_rows(atom, ledger, index, registry, semantics)
    support = []
    for _position, evidence_id, value_json in rows:
        supports, _refutes = _typed_value_match(value_json, expected_json)
        if supports:
            support.append(evidence_id)
    if support:
        return PrimitiveProof(atom, Truth.TRUE, tuple(support), ())
    return PrimitiveProof(atom, Truth.UNKNOWN, (), (), reasons=(Reason.EVIDENCE_INCOMPLETE,))


def _prove_deterministic_action_atom(atom: ProofAtom, ledger: EvidenceLedger,
                                      index: LedgerIndex | None = None,
                                      registry: ContractRegistry | None = None,
                                      semantics: E2ESemantics = FULL_SEMANTICS) -> PrimitiveProof:
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
    # (a stale observation never proves current state on its own). Under
    # conservative state semantics (SND-09) only TRUSTED state evidence
    # qualifies: pure-reader rows (contract, no writes, fresh-read,
    # preconditions held) and verified effects. Operation-status rows from
    # mutation results or uncontracted tools never resolve a gate.
    key_tokens = set(atom.predicate.split("_"))
    trusted = semantics.conservative_state and index is not None and registry is not None

    def _trusted_state_row(item) -> bool:
        if not trusted:
            return True
        event = index.events_by_id.get(item.event_id)
        if event is not None and _pure_reader_event(event, index, registry):
            return True
        return any(effect.event_id == item.event_id and effect_is_verified(effect, ledger, index, registry)
                   for effect in ledger.effects)

    observations = [item for item in ledger.observations
                    if (item.predicate == atom.predicate or item.predicate in key_tokens)
                    and item.index <= atom.time_index
                    and (atom.entity.value == "*" or atom.entity.value in {ref.value for ref in item.entity_refs})
                    and _trusted_state_row(item)]
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
