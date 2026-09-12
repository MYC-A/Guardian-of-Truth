"""Bounded post-UNRESOLVED escalation. No fact rewrite or desired-verdict loop."""

from __future__ import annotations

from dataclasses import asdict, dataclass, replace
from enum import Enum
from typing import Callable

from .certificates import CertificateContext
from .decision import CertifiedCoreResult, decide
from .integrity import canonical
from .ledger import EvidenceLedger
from .proof_records import ProofProblem
from .tools import ContractRegistry
from .types import CoreStatus, EffectStatus


class EscalationStep(str, Enum):
    NARROW_REPARSE = "NARROW_REPARSE"
    EXPAND_SEARCH = "EXPAND_SEARCH"
    INDEPENDENT_CHALLENGER = "INDEPENDENT_CHALLENGER"


@dataclass(frozen=True)
class EscalationState:
    problem: ProofProblem
    ledger: EvidenceLedger
    registry: ContractRegistry
    context: CertificateContext
    result: CertifiedCoreResult


@dataclass(frozen=True)
class EscalationOutcome:
    state: EscalationState
    attempts: tuple[str, ...]
    terminal_unresolved: bool


def check_monotonic_update(old: EscalationState, new: EscalationState) -> None:
    if (new.ledger.events[:len(old.ledger.events)] != old.ledger.events
            or new.ledger.observations[:len(old.ledger.observations)] != old.ledger.observations):
        raise ValueError("escalation may not rewrite or remove immutable observations/events")
    old_trusted = {canonical(asdict(effect)) for effect in old.ledger.effects if effect.status is EffectStatus.TRUSTED_EFFECT}
    new_trusted = {canonical(asdict(effect)) for effect in new.ledger.effects if effect.status is EffectStatus.TRUSTED_EFFECT}
    if not old_trusted <= new_trusted:
        raise ValueError("escalation may not overwrite trusted effects")
    old_contracts = {contract.sha256 for contract in old.registry.contracts}
    if not old_contracts <= {contract.sha256 for contract in new.registry.contracts}:
        raise ValueError("escalation may add authoritative contracts but cannot rewrite trusted contracts")
    new_axes = {axis.name: axis for axis in new.problem.axes}
    for axis in old.problem.axes:
        # An unparsed failure placeholder with no universe is not an admitted reading.
        if axis.universe_source is not None and (
                axis.name not in new_axes or not set(axis.choice_ids) <= set(new_axes[axis.name].choice_ids)):
            raise ValueError("escalation may not discard admitted interpretations to obtain a desired verdict")
    old_hypotheses = {hyp.hypothesis_id: canonical(asdict(hyp)) for hyp in old.context.hypotheses}
    new_hypotheses = {hyp.hypothesis_id: canonical(asdict(hyp)) for hyp in new.context.hypotheses}
    if any(new_hypotheses.get(hid) != value for hid, value in old_hypotheses.items()):
        raise ValueError("escalation may not rewrite an admitted reading while retaining its identifier")


def escalate(initial: EscalationState, callbacks: dict[EscalationStep, Callable[[EscalationState], EscalationState | None]], *,
              max_steps: int = 3) -> EscalationOutcome:
    if type(max_steps) is not int or not 0 <= max_steps <= 3:
        raise ValueError("bounded escalation budget must be 0..3")
    if initial.result.status is not CoreStatus.UNRESOLVED:
        return EscalationOutcome(initial, (), False)
    current, attempts = initial, []
    for step in tuple(EscalationStep)[:max_steps]:
        callback = callbacks.get(step)
        attempts.append(step.value)
        candidate = callback(current) if callback else None
        if candidate is not None:
            check_monotonic_update(current, candidate)
            # Do not trust a callback's supplied result; independently certify it.
            result = decide(candidate.problem, candidate.ledger, candidate.registry, context=candidate.context,
                            attempted_escalations=tuple(attempts))
            current = replace(candidate, result=result)
        if current.result.status is not CoreStatus.UNRESOLVED:
            return EscalationOutcome(current, tuple(attempts), False)
    diagnostics = replace(current.result.diagnostics, attempted_escalations=tuple(attempts))
    current = replace(current, result=replace(current.result, diagnostics=diagnostics))
    return EscalationOutcome(current, tuple(attempts), True)
