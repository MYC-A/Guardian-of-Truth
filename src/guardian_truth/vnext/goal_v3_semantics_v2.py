"""Goal v3/v2 experimental calculus over *proposed* typed source worlds.

This module cannot certify natural-language meaning. It deliberately returns
local candidates, never CoreStatus or a proof certificate. A separate source
authority adapter must replay every decisive atom before promotion.
"""

from dataclasses import dataclass
from enum import Enum

from .types import Truth


class GoalLocalStatusV2(str, Enum):
    ERROR = "ERROR_CANDIDATE"
    NO_ERROR = "NO_ERROR_CANDIDATE"
    UNRESOLVED = "UNRESOLVED"
    INCONSISTENT = "INCONSISTENT"


class GoalAlignmentV2(str, Enum):
    DIRECT = "DIRECT_GOAL"
    AUXILIARY = "PERMITTED_AUXILIARY"
    OUT_OF_SCOPE = "PROVED_OUT_OF_SCOPE"
    AMBIGUOUS = "AMBIGUOUS_ALIGNMENT"


class ObligationKindV2(str, Enum):
    PREREQUISITE = "PREREQUISITE"
    CONDITIONAL = "CONDITIONAL"
    DEADLINE = "DEADLINE"


@dataclass(frozen=True)
class GoalObligationV2:
    rule_id: str
    kind: ObligationKindV2
    applies: Truth
    due_now: Truth
    satisfied: Truth
    source_id: str

    def __post_init__(self):
        if (not isinstance(self.rule_id, str) or not self.rule_id
                or not isinstance(self.source_id, str) or not self.source_id
                or not isinstance(self.kind, ObligationKindV2)
                or any(not isinstance(value, Truth) for value in
                    (self.applies, self.due_now, self.satisfied))):
            raise ValueError("obligation needs rule and source identifiers")


@dataclass(frozen=True)
class GoalUnknownV2:
    premise_id: str
    decisive_for_no_error: bool

    def __post_init__(self):
        if (not isinstance(self.premise_id, str) or not self.premise_id
                or type(self.decisive_for_no_error) is not bool):
            raise ValueError("unknown premise needs an ID and explicit relevance")


@dataclass(frozen=True)
class GoalWorldV2:
    world_id: str
    alignment: GoalAlignmentV2
    scope_violation: Truth
    prohibition_violation: Truth
    obligations: tuple[GoalObligationV2, ...]
    unknowns: tuple[GoalUnknownV2, ...]
    authorization_closed: bool
    history_complete: bool

    def __post_init__(self):
        if (not isinstance(self.world_id, str) or not self.world_id
                or not isinstance(self.alignment, GoalAlignmentV2)
                or not isinstance(self.scope_violation, Truth)
                or not isinstance(self.prohibition_violation, Truth)
                or type(self.obligations) is not tuple
                or any(not isinstance(item, GoalObligationV2) for item in self.obligations)
                or type(self.unknowns) is not tuple
                or any(not isinstance(item, GoalUnknownV2) for item in self.unknowns)
                or type(self.authorization_closed) is not bool
                or type(self.history_complete) is not bool):
            raise ValueError("world needs an ID and explicit closure flags")
        if len({item.rule_id for item in self.obligations}) != len(self.obligations):
            raise ValueError("duplicate obligation rule IDs")
        if len({item.premise_id for item in self.unknowns}) != len(self.unknowns):
            raise ValueError("duplicate unknown premise IDs")


@dataclass(frozen=True)
class GoalWorldResultV2:
    world_id: str
    status: GoalLocalStatusV2
    alignment: GoalAlignmentV2
    violated_rule_ids: tuple[str, ...]
    inconsistent_rule_ids: tuple[str, ...]
    unresolved_rule_ids: tuple[str, ...]
    pending_rule_ids: tuple[str, ...]
    nondecisive_unknown_ids: tuple[str, ...]


@dataclass(frozen=True)
class GoalCandidateDecisionV2:
    status: GoalLocalStatusV2
    alignment: GoalAlignmentV2
    worlds: tuple[GoalWorldResultV2, ...]
    complete_world_inventory: bool

    @property
    def certified(self) -> bool:
        return False

    @property
    def authority(self) -> str:
        return "NO_SOURCE_AUTHORITY_REPLAY"


def evaluate_world_v2(world: GoalWorldV2) -> GoalWorldResultV2:
    """One interpretation: independent witnessed ERROR beats unrelated UNKNOWN."""
    violations = []
    contradictions = []
    unresolved = []
    pending = []
    if world.scope_violation is Truth.TRUE:
        violations.append("SCOPE")
    elif world.scope_violation is Truth.BOTH:
        contradictions.append("SCOPE")
    elif world.scope_violation is Truth.UNKNOWN:
        unresolved.append("SCOPE")
    if world.prohibition_violation is Truth.TRUE:
        violations.append("PROHIBITION")
    elif world.prohibition_violation is Truth.BOTH:
        contradictions.append("PROHIBITION")
    elif world.prohibition_violation is Truth.UNKNOWN:
        unresolved.append("PROHIBITION")
    for rule in world.obligations:
        if rule.applies is Truth.FALSE:
            continue
        if rule.applies is Truth.BOTH or rule.due_now is Truth.BOTH or rule.satisfied is Truth.BOTH:
            contradictions.append(rule.rule_id)
        elif rule.satisfied is Truth.TRUE:
            # A satisfied prerequisite is safe even if its guard is unknown.
            continue
        elif rule.applies is Truth.UNKNOWN:
            unresolved.append(rule.rule_id)
        elif rule.due_now is Truth.FALSE:
            pending.append(rule.rule_id)
        elif rule.due_now is Truth.UNKNOWN or rule.satisfied is Truth.UNKNOWN:
            unresolved.append(rule.rule_id)
        elif rule.due_now is Truth.TRUE and rule.satisfied is Truth.FALSE:
            violations.append(rule.rule_id)
    nondecisive_unknowns = tuple(item.premise_id for item in world.unknowns
        if not item.decisive_for_no_error)
    unresolved.extend(item.premise_id for item in world.unknowns if item.decisive_for_no_error)
    if violations:
        status = GoalLocalStatusV2.ERROR
    elif contradictions:
        status = GoalLocalStatusV2.INCONSISTENT
    elif (unresolved or not world.authorization_closed or not world.history_complete
            or world.alignment is GoalAlignmentV2.AMBIGUOUS
            or world.alignment is GoalAlignmentV2.OUT_OF_SCOPE):
        status = GoalLocalStatusV2.UNRESOLVED
    else:
        status = GoalLocalStatusV2.NO_ERROR
    return GoalWorldResultV2(world.world_id, status, world.alignment,
        tuple(violations), tuple(contradictions), tuple(unresolved),
        tuple(pending), nondecisive_unknowns)


def aggregate_worlds_v2(worlds: tuple[GoalWorldV2, ...], *,
                        complete_world_inventory: bool) -> GoalCandidateDecisionV2:
    """No single best reading; require one outcome in every material world."""
    if not worlds or type(complete_world_inventory) is not bool:
        raise ValueError("nonempty worlds and explicit inventory completeness required")
    if len({world.world_id for world in worlds}) != len(worlds):
        raise ValueError("duplicate world IDs")
    evaluated = tuple(evaluate_world_v2(world) for world in worlds)
    statuses = {world.status for world in evaluated}
    status = (next(iter(statuses)) if complete_world_inventory and len(statuses) == 1
        else GoalLocalStatusV2.UNRESOLVED)
    alignments = {world.alignment for world in evaluated}
    alignment = next(iter(alignments)) if len(alignments) == 1 else GoalAlignmentV2.AMBIGUOUS
    return GoalCandidateDecisionV2(status, alignment, evaluated, complete_world_inventory)
