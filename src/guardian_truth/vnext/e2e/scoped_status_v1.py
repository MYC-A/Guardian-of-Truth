"""E2E-agent-1 causal repair A1: scoped claim-UNKNOWN status composition.

THE REPAIRED DEFECT (E2E V1 world integration): claim-channel uncertainty
(CLAIM_UNTYPED, ENTITY_UNBOUND, SOURCE_UNBOUND, TIME_UNBOUND, claim-graph
failures) entered `hard_reasons` and from there EVERY world's unresolved
markers, and the baseline solver short-circuits a markered world's error
value to UNKNOWN — so a *certified independent* Policy/Goal/factual
violation was masked by an *unrelated* claim UNKNOWN and the case collapsed
to UNRESOLVED.

THE REPAIRED ALGEBRA (user spec section 3):

    FALSE and UNKNOWN = FALSE        (a proven violation dominates unrelated
                                      uncertainty in the safety conjunction)
    NOT(FALSE)       = ERROR         (all worlds certainly violated)
    TRUE and UNKNOWN = UNKNOWN       (uncertainty blocks proved safety)
    NOT(UNKNOWN)     = UNKNOWN       (never certify safety over unknowns)

Implementation: per world, a safety conjunct is CERTIFIABLE when the axis
that contributed it is enumeration-complete (its candidate space is closed).
A world is certainly-in-error when at least one certifiable conjunct is
FALSE.  Soundness under completion of incomplete axes: a hypothetical
completion can only ADD conjuncts (and markers) to a world — the complete
axes' conjuncts are fixed by the Cartesian product — and the safety
conjunction is monotone, so a certifiable FALSE conjunct keeps the completed
world in error.  Hence:

    PROVED_ERROR      every enumerated world has >= 1 certifiable FALSE
                      conjunct (and the worlds exhaust the axes product);
    PROVED_NO_ERROR   the full baseline requirements (complete space, no
                      markers, every world's safety TRUE) — strictly
                      unchanged, `false_certified_NO_ERROR = 0` preserved;
    UNRESOLVED        otherwise (including any marker with all-TRUE
                      certifiable conjuncts, and uncertifiable allegations).

Markers therefore: (a) act as an UNKNOWN safety conjunct, (b) block
PROVED_NO_ERROR, (c) never block an independent certifiable violation, and
(d) never create an ERROR by themselves.  A claim-dependent ERROR still
requires that claim's own axis to be complete (an untyped/unbound claim
contributes no conjunct at all, so it can only leave the case UNRESOLVED).

When every axis is complete this composition coincides EXACTLY with the
plain four-valued algebra (conjunction + negation without the short-circuit);
the extra conservatism applies only when some axis is open.

The baseline `solve()` is NOT modified: this module composes the E2E status
from the solver's world proofs (same primitives, same safety values), and
the certificate checker re-derives it with the SAME functions (tamper-
evident).  Everything here is deterministic: no LLM, no network, no clock.
"""
from __future__ import annotations

from dataclasses import dataclass

from ..proof_records import ProofProblem, SolverResult, WorldProof, conjunction, negate
from ..types import CoreStatus, Truth

FACTUAL_HYPOTHESIS = "GUARDIAN_FACTUAL_CONSISTENCY_V1"


@dataclass(frozen=True)
class RepairConfig:
    """Causal-repair arm configuration (all flags default off = exact A0).

    scoped_unknown   A1: scoped claim-UNKNOWN status composition (this module)
    value_anchoring  A2: deterministic claim value anchoring (claim_adapter_v2)
    catalog_binding  A3: source-backed catalog-identity binding of unexercised
                     semantic atoms (binding_repair_v1)
    """

    scoped_unknown: bool = False
    value_anchoring: bool = False
    catalog_binding: bool = False

    def arm_label(self) -> str:
        if not self.scoped_unknown and not self.value_anchoring and not self.catalog_binding:
            return "A0"
        if self.scoped_unknown and not self.value_anchoring and not self.catalog_binding:
            return "A1"
        if self.scoped_unknown and self.value_anchoring and not self.catalog_binding:
            return "A2"
        if self.scoped_unknown and self.value_anchoring and self.catalog_binding:
            return "A3"
        return "A-mixed(%s%s%s)" % ("S" if self.scoped_unknown else "-",
                                    "V" if self.value_anchoring else "-",
                                    "C" if self.catalog_binding else "-")


@dataclass(frozen=True)
class ScopedComposition:
    """Result of the scoped status composition over the solver's world proofs."""

    status: CoreStatus
    world_values: tuple[Truth, ...]              # scoped error value per world
    certifying_witnesses: tuple[tuple[str, str], ...]  # (world_id, obligation_id)
    rationale: tuple[str, ...]


def axis_completeness(problem: ProofProblem) -> dict[str, bool]:
    """Axis name -> enumeration completeness (from the hashed problem)."""
    return {axis.name: axis.enumeration_complete is True for axis in problem.axes}


def obligation_axis(obligation) -> str | None:
    """Which interpretation axis contributed this obligation.

    Claim obligations name their claim axis via `claim_id`; policy and goal
    lowering use the reading/contract id (policy:*/goal:*) as hypothesis_id.
    Bind-combo policy choices keep the reading prefix (the |bind[...] suffix
    lives on the CHOICE id, not on the obligations)."""
    if obligation.hypothesis_id == FACTUAL_HYPOTHESIS:
        return obligation.claim_id
    if obligation.hypothesis_id.startswith("policy:"):
        return "policy"
    if obligation.hypothesis_id.startswith("goal:"):
        return "goal"
    return None


def world_space_enumerated(problem: ProofProblem) -> bool:
    """Structural product coverage WITHOUT the all-axes-complete requirement.

    Scoped PROVED_ERROR needs the enumerated worlds to exhaust the axes
    product (an unenumerated world could be safe), but it does NOT need
    every axis to be enumeration-complete: open axes only add conjuncts and
    markers in completions, which cannot un-violate a certifiable conjunct."""
    if (len({axis.name for axis in problem.axes}) != len(problem.axes)
            or any(not axis.choice_ids or len(set(axis.choice_ids)) != len(axis.choice_ids)
                   for axis in problem.axes)):
        return False
    import itertools
    expected_set = set(itertools.product(*(axis.choice_ids for axis in problem.axes)))
    actual = [world.choices for world in problem.worlds]
    return (bool(problem.worlds)
            and len({world.world_id for world in problem.worlds}) == len(problem.worlds)
            and len(actual) == len(set(actual)) and set(actual) == expected_set)


def scoped_world_value(world, proof: WorldProof, completeness: dict[str, bool]):
    """Scoped error value of ONE world + the certifying FALSE conjuncts.

    Returns (value, certifying_obligation_ids).  The value is TRUE only via
    a FALSE conjunct contributed by a COMPLETE axis (an uncertifiable FALSE
    — a violation alleged under an open reading — is an UNKNOWN allegation,
    never a certificate)."""
    certifying = []
    for obligation in world.obligations:
        axis = obligation_axis(obligation)
        if axis is None or not completeness.get(axis, False):
            continue
        for obligation_id, value in proof.obligation_safety:
            if obligation_id == obligation.obligation_id and value is Truth.FALSE:
                certifying.append(obligation_id)
                break
    if certifying:
        return Truth.TRUE, tuple(certifying)
    values = tuple(value for _, value in proof.obligation_safety)
    if world.unresolved_reasons:
        # markers act as an UNKNOWN conjunct: TRUE ^ UNKNOWN = UNKNOWN, but a
        # FALSE conjunct was already handled above (FALSE ^ UNKNOWN = FALSE).
        return Truth.UNKNOWN, ()
    full = negate(conjunction(values))
    if full is Truth.TRUE:
        # a violation under this world that is NOT certifiable (its axis is
        # open): an allegation, not a certificate.
        return Truth.UNKNOWN, ()
    return full, ()


def scoped_composition(problem: ProofProblem, solver_result: SolverResult,
                       *, material_space_complete: bool) -> ScopedComposition:
    """Compose the E2E status under the scoped algebra from world proofs."""
    proofs = {proof.world_id: proof for proof in solver_result.world_proofs}
    completeness = axis_completeness(problem)
    values, witnesses, rationale = [], [], []
    inconsistent = False
    for world in problem.worlds:
        proof = proofs.get(world.world_id)
        if proof is None:
            return ScopedComposition(CoreStatus.UNRESOLVED, (), (),
                                     ("MISSING_WORLD_PROOF:" + world.world_id,))
        # proof contradictions (BOTH) stay baseline-terminal
        full_values = tuple(value for _, value in proof.obligation_safety)
        if negate(conjunction(full_values)) is Truth.BOTH or any(
                value is Truth.BOTH for value in full_values):
            inconsistent = True
        value, certifying = scoped_world_value(world, proof, completeness)
        values.append(value)
        witnesses.extend((world.world_id, obligation_id) for obligation_id in certifying)
    if inconsistent:
        return ScopedComposition(CoreStatus.INCONSISTENT, tuple(values), tuple(witnesses),
                                 ("SCOPED_INCONSISTENT_EVIDENCE",))
    if not values:
        return ScopedComposition(CoreStatus.UNRESOLVED, (), (), ("NO_WORLDS",))
    if world_space_enumerated(problem) and all(value is Truth.TRUE for value in values):
        return ScopedComposition(
            CoreStatus.PROVED_ERROR, tuple(values), tuple(witnesses),
            tuple(f"certified_violation:{world}:{obligation}"
                  for world, obligation in witnesses))
    if (material_space_complete and not any(world.unresolved_reasons for world in problem.worlds)
            and all(value is Truth.FALSE for value in values)):
        return ScopedComposition(CoreStatus.PROVED_NO_ERROR, tuple(values), (),
                                 ("certified_safe_all_worlds",))
    if any(value is Truth.TRUE for value in values) and not all(
            value is Truth.TRUE for value in values):
        rationale = ("MIXED_CERTIFIED_AND_SAFE_WORLDS",)
    elif any(world.unresolved_reasons for world in problem.worlds):
        rationale = ("SCOPED_UNKNOWN_MARKERS",)
    return ScopedComposition(CoreStatus.UNRESOLVED, tuple(values),
                             tuple(witnesses), tuple(rationale) or ("SCOPED_UNRESOLVED",))


def scoped_world_proofs(solver_result: SolverResult, problem: ProofProblem):
    """Rebuild the solver's world proofs carrying the SCOPED error values
    (same primitives and safety witnesses — only the verdict is composed)."""
    from ..proof_records import WorldProof
    completeness = axis_completeness(problem)
    rebuilt = []
    for proof in solver_result.world_proofs:
        world = next((w for w in problem.worlds if w.world_id == proof.world_id), None)
        if world is None:
            rebuilt.append(proof)
            continue
        value, _ = scoped_world_value(world, proof, completeness)
        rebuilt.append(WorldProof(proof.world_id, proof.choices, value,
                                  proof.obligation_safety, proof.primitives))
    return tuple(rebuilt)
