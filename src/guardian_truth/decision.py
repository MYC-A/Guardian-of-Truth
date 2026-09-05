"""Explicit classification policy; model confidence is not a proof/probability."""

from dataclasses import dataclass
import math


@dataclass(frozen=True)
class Decision:
    label: int
    reason: str
    used_fallback: bool
    score: float | None = None


def decide(review, *, threshold=0.5, use_semantic=False, unknown_label=0):
    if type(threshold) not in (int,float) or not math.isfinite(threshold) or not 0 <= threshold <= 1:
        raise ValueError('Threshold must be between 0 and 1')
    if type(unknown_label) is not int or unknown_label not in (0,1):
        raise ValueError('Unknown label must be binary')
    if review.status == 'violation':
        return Decision(1, 'mechanical_violation', False)
    score = review.semantic_score
    if use_semantic and score is not None:
        if type(score) not in (int,float) or not math.isfinite(score) or not 0 <= score <= 1:
            return Decision(unknown_label, 'invalid_score_fallback', True)
        return Decision(int(score >= threshold), 'uncalibrated_semantic_threshold', False, score)
    return Decision(unknown_label, 'unknown_fallback', True)
