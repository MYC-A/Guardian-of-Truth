"""Goal composition V1 (spec sections 78-79).

Both goal frontends lower to the same canonical GoalContract form.  The
composition compares the two contracts DETERMINISTICALLY over their
obligation-bearing frames (DESIRED_OUTCOME / PROHIBITION / OBLIGATION —
AUTHORIZATION and GUARD frames emit no obligations and cannot distinguish
verdicts):

  - structurally identical obligation surfaces -> EQUIVALENT (dedupe);
  - otherwise -> RETAIN BOTH as separate goal interpretation choices
    (spec section 79: 'if proof equivalence impossible: retain both').

No winner selection, no voting, no confidence weighting (spec section 53).
Everything here is deterministic.
"""
from __future__ import annotations

from dataclasses import dataclass

from .goal_types_v1 import FrameKind, GoalContract

OBLIGATION_KINDS = {FrameKind.DESIRED_OUTCOME, FrameKind.PROHIBITION, FrameKind.OBLIGATION}


@dataclass(frozen=True)
class GoalComposition:
    contracts: tuple[GoalContract, ...]      # retained goal choices (deduped)
    agreement: str                           # EQUIVALENT | DIFFERENT | ONE_INVALID | BOTH_INVALID
    detail: dict
    unresolved_reason: str | None


def _frame_key(frame) -> tuple:
    return (frame.kind.value,
            frame.content.text if frame.content else None,
            frame.entity.text if frame.entity else None,
            tuple(condition.text for condition in frame.conditions),
            tuple(exception.text for exception in frame.exceptions),
            tuple(alternative.text for alternative in frame.alternatives),
            frame.temporal,
            frame.temporal_event.text if frame.temporal_event else None,
            frame.coordination, frame.choice, frame.target_level.value)


def _obligation_surface(contract: GoalContract) -> tuple:
    return tuple(sorted(_frame_key(frame) for frame in contract.frames
                        if frame.kind in OBLIGATION_KINDS))


def _contract_valid(contract: GoalContract) -> bool:
    # a frontend transport/schema failure is recorded as a rejected frame
    return not any(reason == "TRANSPORT_OR_SCHEMA_FAILURE"
                   for _, reason in contract.rejected_frames)


def compose_goal_contracts(conservative: GoalContract,
                           rule_frames: GoalContract) -> GoalComposition:
    conservative_valid = _contract_valid(conservative)
    rule_frames_valid = _contract_valid(rule_frames)
    if not conservative_valid and not rule_frames_valid:
        return GoalComposition((), "BOTH_INVALID",
                               {"conservative_frames": len(conservative.frames),
                                "rule_frames_frames": len(rule_frames.frames)},
                               "GOAL_NO_VALID_CONTRACT")
    if not conservative_valid or not rule_frames_valid:
        valid = conservative if conservative_valid else rule_frames
        return GoalComposition((valid,), "ONE_INVALID",
                               {"kept": valid.frontend},
                               "GOAL_SEMANTIC_COVERAGE_OPEN")
    if _obligation_surface(conservative) == _obligation_surface(rule_frames):
        return GoalComposition((conservative,), "EQUIVALENT",
                               {"frames": len(conservative.frames),
                                "obligation_frames": len(_obligation_surface(conservative))}, None)
    return GoalComposition((conservative, rule_frames), "DIFFERENT",
                           {"conservative_frames": len(conservative.frames),
                            "rule_frames_frames": len(rule_frames.frames),
                            "conservative_obligation_frames": len(_obligation_surface(conservative)),
                            "rule_frames_obligation_frames": len(_obligation_surface(rule_frames))},
                           None)
