"""Offline utilities for competing policy-semantic interpretations.

This module operates on trace-independent :class:`PolicyMeaning` proposals.
It does not compile obligations, inspect trajectories, call a model, or emit a
Guardian label.  In particular, oracle and mutation results produced here are
development diagnostics, not evidence that live P4--P6 arms have passed.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from enum import Enum
import hashlib
from typing import Callable, Iterable

from .records import (
    PolicyMeaning,
    PolicyModality,
    PolicyQuantification,
    Span,
    TemporalConstraint,
)


@dataclass(frozen=True)
class PolicyInterpretation:
    """One complete candidate interpretation Phi for a policy segment."""

    id: str
    meanings: tuple[PolicyMeaning, ...]
    unknown_spans: tuple[Span, ...]
    generator: str
    rank: int


@dataclass(frozen=True)
class PolicyCandidatePool:
    policy_hash: str
    candidates: tuple[PolicyInterpretation, ...]
    frozen: bool = True


def _meaning_signature(meaning: PolicyMeaning) -> tuple:
    """Canonical semantic content, excluding IDs, ranks, and source offsets."""
    conditions = tuple(sorted(item.text for item in meaning.conditions))
    exceptions = tuple(sorted(item.text for item in meaning.exceptions))
    identities = tuple(sorted(
        (item.entity_type, item.key, item.relation, item.value)
        for item in meaning.identity_constraints
    ))
    return (
        meaning.modality.value,
        meaning.subject.kind,
        meaning.subject.identifier,
        meaning.regulated.kind.value,
        meaning.regulated.predicate,
        meaning.regulated.object,
        conditions,
        exceptions,
        meaning.temporal.relation,
        meaning.temporal.anchor,
        meaning.temporal.duration,
        identities,
        meaning.quantification.kind,
        meaning.quantification.amount,
        meaning.uncertainty.value,
        meaning.unsupported_reason,
    )


def interpretation_signature(interpretation: PolicyInterpretation) -> tuple:
    """Order-independent exact semantic signature for offline comparisons."""
    return (
        tuple(sorted(_meaning_signature(item) for item in interpretation.meanings)),
        tuple(sorted((span.document, span.start, span.end) for span in interpretation.unknown_spans)),
    )


def _validate_span(span: Span, policy_text: str, *, expected: str | None = None) -> None:
    if span.document != "prompt" or not (0 <= span.start < span.end <= len(policy_text)):
        raise ValueError("semantic source span is outside the policy segment")
    if expected is not None and policy_text[span.start:span.end] != expected:
        raise ValueError("semantic source span does not reproduce its exact quote")


def validate_interpretation(interpretation: PolicyInterpretation, policy_text: str) -> None:
    """Validate provenance and identity without judging semantic correctness."""
    if not interpretation.id or not interpretation.generator or interpretation.rank < 0:
        raise ValueError("invalid interpretation metadata")
    if not interpretation.meanings and not interpretation.unknown_spans:
        raise ValueError("empty interpretation must preserve an unknown source span")
    meaning_ids: set[str] = set()
    for meaning in interpretation.meanings:
        if not meaning.id or meaning.id in meaning_ids:
            raise ValueError("duplicate meaning id within interpretation")
        meaning_ids.add(meaning.id)
        if not meaning.provenance.extractor or meaning.provenance.occurrence < 0:
            raise ValueError("invalid semantic provenance metadata")
        _validate_span(meaning.provenance.source, policy_text, expected=meaning.provenance.quote)
        starts = []
        cursor = 0
        while True:
            start = policy_text.find(meaning.provenance.quote, cursor)
            if start < 0:
                break
            starts.append(start)
            cursor = start + 1
        if (meaning.provenance.occurrence >= len(starts)
                or starts[meaning.provenance.occurrence] != meaning.provenance.source.start):
            raise ValueError("semantic provenance occurrence does not match its source span")
        for qualifier in (*meaning.conditions, *meaning.exceptions):
            _validate_span(qualifier.source, policy_text, expected=qualifier.text)
    for span in interpretation.unknown_spans:
        _validate_span(span, policy_text)


def build_candidate_pool(
    policy_text: str, candidates: Iterable[PolicyInterpretation],
) -> PolicyCandidatePool:
    """Freeze a ranked, duplicate-free candidate set before trace evaluation."""
    candidates = tuple(candidates)
    if not candidates:
        raise ValueError("candidate pool cannot be empty")
    if [item.rank for item in candidates] != list(range(len(candidates))):
        raise ValueError("candidate ranks must be contiguous and match pool order")
    ids: set[str] = set()
    signatures: set[tuple] = set()
    for candidate in candidates:
        validate_interpretation(candidate, policy_text)
        if candidate.id in ids:
            raise ValueError("duplicate candidate id")
        ids.add(candidate.id)
        signature = interpretation_signature(candidate)
        if signature in signatures:
            raise ValueError("duplicate semantic candidate")
        signatures.add(signature)
    return PolicyCandidatePool(
        policy_hash=hashlib.sha256(policy_text.encode("utf-8")).hexdigest(),
        candidates=candidates,
    )


@dataclass(frozen=True)
class OraclePoint:
    k: int
    hit: bool


@dataclass(frozen=True)
class OracleAtKResult:
    points: tuple[OraclePoint, ...]
    first_match_rank: int | None
    comparator: str
    execution_mode: str = "OFFLINE_DEVELOPMENT_DIAGNOSTIC"


def oracle_at_k(
    pool: PolicyCandidatePool,
    gold_interpretations: Iterable[PolicyInterpretation],
    *,
    ks: Iterable[int] = (1, 3, 5),
    equivalent: Callable[[PolicyInterpretation, PolicyInterpretation], bool] | None = None,
) -> OracleAtKResult:
    """Report pool recall under a supplied oracle; never selects a deployable arm."""
    gold = tuple(gold_interpretations)
    if not gold:
        raise ValueError("at least one gold interpretation is required")
    requested = tuple(sorted(set(ks)))
    if not requested or requested[0] <= 0:
        raise ValueError("oracle k values must be positive")
    if equivalent is None:
        equivalent = lambda left, right: interpretation_signature(left) == interpretation_signature(right)
        comparator = "exact_semantic_signature"
    else:
        comparator = "caller_supplied"
    first = next((
        candidate.rank
        for candidate in pool.candidates
        if any(equivalent(candidate, reference) for reference in gold)
    ), None)
    return OracleAtKResult(
        points=tuple(OraclePoint(k, first is not None and first < k) for k in requested),
        first_match_rank=first,
        comparator=comparator,
    )


class PairwiseOutcome(str, Enum):
    LEFT = "left"
    RIGHT = "right"
    TIE = "tie"
    ABSTAIN = "abstain"


@dataclass(frozen=True)
class PairwiseDecision:
    left_id: str
    right_id: str
    outcome: PairwiseOutcome
    reason: str
    evaluator: str


@dataclass(frozen=True)
class PairwiseScore:
    candidate_id: str
    wins: int
    ties: int
    losses: int
    abstentions: int
    score: float


@dataclass(frozen=True)
class PairwiseSelection:
    selected_id: str
    scores: tuple[PairwiseScore, ...]
    compared_pairs: int
    required_pairs: int
    complete: bool
    execution_mode: str = "OFFLINE_DETERMINISTIC_AGGREGATION"


def select_pairwise(
    pool: PolicyCandidatePool, decisions: Iterable[PairwiseDecision],
) -> PairwiseSelection:
    """Validate external pair judgments and aggregate them deterministically."""
    decisions = tuple(decisions)
    candidate_ids = {item.id for item in pool.candidates}
    rank = {item.id: item.rank for item in pool.candidates}
    counters = {item.id: {"wins": 0, "ties": 0, "losses": 0, "abstentions": 0}
                for item in pool.candidates}
    seen: set[frozenset[str]] = set()
    for decision in decisions:
        if (decision.left_id not in candidate_ids or decision.right_id not in candidate_ids
                or decision.left_id == decision.right_id):
            raise ValueError("pairwise decision references invalid candidates")
        if not isinstance(decision.outcome, PairwiseOutcome):
            raise ValueError("invalid pairwise outcome")
        if not decision.reason.strip() or not decision.evaluator.strip():
            raise ValueError("pairwise decision requires reason and evaluator provenance")
        pair = frozenset((decision.left_id, decision.right_id))
        if pair in seen:
            raise ValueError("duplicate pairwise comparison")
        seen.add(pair)
        left, right = counters[decision.left_id], counters[decision.right_id]
        if decision.outcome is PairwiseOutcome.LEFT:
            left["wins"] += 1
            right["losses"] += 1
        elif decision.outcome is PairwiseOutcome.RIGHT:
            right["wins"] += 1
            left["losses"] += 1
        elif decision.outcome is PairwiseOutcome.TIE:
            left["ties"] += 1
            right["ties"] += 1
        else:
            left["abstentions"] += 1
            right["abstentions"] += 1
    scores = tuple(PairwiseScore(
        candidate_id=candidate.id,
        wins=counters[candidate.id]["wins"],
        ties=counters[candidate.id]["ties"],
        losses=counters[candidate.id]["losses"],
        abstentions=counters[candidate.id]["abstentions"],
        score=counters[candidate.id]["wins"] + 0.5 * counters[candidate.id]["ties"],
    ) for candidate in pool.candidates)
    selected = min(scores, key=lambda item: (-item.score, rank[item.candidate_id], item.candidate_id))
    required = len(pool.candidates) * (len(pool.candidates) - 1) // 2
    return PairwiseSelection(
        selected_id=selected.candidate_id,
        scores=scores,
        compared_pairs=len(seen),
        required_pairs=required,
        complete=len(seen) == required,
    )


@dataclass(frozen=True)
class SemanticMutant:
    id: str
    parent_interpretation_id: str
    operator: str
    target_meaning_id: str
    interpretation: PolicyInterpretation


def _mutated_quantification(value: PolicyQuantification) -> PolicyQuantification:
    if value.kind == "all":
        return PolicyQuantification("any")
    if value.kind == "any":
        return PolicyQuantification("all")
    if value.kind == "none":
        return PolicyQuantification("any")
    if value.kind == "unspecified":
        return PolicyQuantification("all")
    if value.kind == "exactly":
        return PolicyQuantification("exactly", (value.amount or 0) + 1)
    if value.kind == "at_least":
        return PolicyQuantification("at_most", value.amount)
    return PolicyQuantification("at_least", value.amount)


def generate_semantic_mutants(interpretation: PolicyInterpretation) -> tuple[SemanticMutant, ...]:
    """Generate single-change semantic mutants without claiming they are valid policy readings."""
    mutants: list[SemanticMutant] = []

    def add(index: int, operator: str, meaning: PolicyMeaning) -> None:
        changed = list(interpretation.meanings)
        changed[index] = meaning
        mutant_id = f"{interpretation.id}::mutant:{index}:{operator}"
        candidate = PolicyInterpretation(
            id=mutant_id,
            meanings=tuple(changed),
            unknown_spans=interpretation.unknown_spans,
            generator=f"semantic_mutant:{operator}",
            rank=len(mutants),
        )
        mutants.append(SemanticMutant(
            id=mutant_id,
            parent_interpretation_id=interpretation.id,
            operator=operator,
            target_meaning_id=meaning.id,
            interpretation=candidate,
        ))

    modality_flip = {
        PolicyModality.PERMISSION: PolicyModality.REQUIREMENT,
        PolicyModality.PROHIBITION: PolicyModality.PERMISSION,
        PolicyModality.REQUIREMENT: PolicyModality.PERMISSION,
    }
    for index, meaning in enumerate(interpretation.meanings):
        if meaning.modality in modality_flip:
            add(index, "flip_modality", replace(meaning, modality=modality_flip[meaning.modality]))
        if meaning.conditions:
            add(index, "drop_conditions", replace(meaning, conditions=()))
        if meaning.exceptions:
            add(index, "drop_exceptions", replace(meaning, exceptions=()))
        if meaning.temporal.relation != "unspecified":
            add(index, "drop_temporal", replace(
                meaning, temporal=TemporalConstraint("unspecified"),
            ))
        if meaning.identity_constraints:
            add(index, "drop_identity", replace(meaning, identity_constraints=()))
        add(index, "alter_quantifier", replace(
            meaning, quantification=_mutated_quantification(meaning.quantification),
        ))
    return tuple(mutants)


class SemanticOutcome(str, Enum):
    APPLIES = "applies"
    DOES_NOT_APPLY = "does_not_apply"
    UNRESOLVED = "unresolved"
    INCONSISTENT = "inconsistent"


@dataclass(frozen=True)
class DistinguishingWorld:
    id: str
    facts: frozenset[str]
    description: str


@dataclass(frozen=True)
class MutantWorldResult:
    mutant_id: str
    world_id: str
    reference_outcome: SemanticOutcome
    mutant_outcome: SemanticOutcome
    distinguishes: bool


@dataclass(frozen=True)
class DistinguishingWorldReport:
    results: tuple[MutantWorldResult, ...]
    killed_mutant_ids: tuple[str, ...]
    surviving_mutant_ids: tuple[str, ...]
    mutation_score: float
    execution_mode: str = "OFFLINE_SCAFFOLD_ONLY_NOT_P4_P6_EVIDENCE"


def evaluate_distinguishing_worlds(
    reference: PolicyInterpretation,
    mutants: Iterable[SemanticMutant],
    worlds: Iterable[DistinguishingWorld],
    evaluator: Callable[[PolicyInterpretation, DistinguishingWorld], SemanticOutcome],
) -> DistinguishingWorldReport:
    """Measure whether caller-supplied worlds distinguish synthetic mutations."""
    mutants, worlds = tuple(mutants), tuple(worlds)
    if not mutants or not worlds:
        raise ValueError("at least one mutant and one distinguishing world are required")
    if any(mutant.parent_interpretation_id != reference.id for mutant in mutants):
        raise ValueError("mutant does not belong to the reference interpretation")
    if len({mutant.id for mutant in mutants}) != len(mutants):
        raise ValueError("mutant ids must be unique")
    if (len({world.id for world in worlds}) != len(worlds)
            or any(not world.id or not world.description for world in worlds)):
        raise ValueError("distinguishing worlds require unique ids and descriptions")
    reference_outcomes = {}
    for world in worlds:
        outcome = evaluator(reference, world)
        if not isinstance(outcome, SemanticOutcome):
            raise ValueError("world evaluator returned an invalid outcome")
        reference_outcomes[world.id] = outcome
    results = []
    killed: set[str] = set()
    for mutant in mutants:
        for world in worlds:
            outcome = evaluator(mutant.interpretation, world)
            if not isinstance(outcome, SemanticOutcome):
                raise ValueError("world evaluator returned an invalid outcome")
            distinguishes = outcome is not reference_outcomes[world.id]
            if distinguishes:
                killed.add(mutant.id)
            results.append(MutantWorldResult(
                mutant_id=mutant.id,
                world_id=world.id,
                reference_outcome=reference_outcomes[world.id],
                mutant_outcome=outcome,
                distinguishes=distinguishes,
            ))
    mutant_ids = tuple(mutant.id for mutant in mutants)
    return DistinguishingWorldReport(
        results=tuple(results),
        killed_mutant_ids=tuple(item for item in mutant_ids if item in killed),
        surviving_mutant_ids=tuple(item for item in mutant_ids if item not in killed),
        mutation_score=len(killed) / len(mutants),
    )
