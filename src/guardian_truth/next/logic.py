"""Small four-valued logic used by the deterministic decision layer."""

from __future__ import annotations

from .records import FourValue


def negate(value: FourValue) -> FourValue:
    return {
        FourValue.TRUE: FourValue.FALSE,
        FourValue.FALSE: FourValue.TRUE,
        FourValue.BOTH: FourValue.BOTH,
        FourValue.UNKNOWN: FourValue.UNKNOWN,
    }[value]


def conjunction(left: FourValue, right: FourValue) -> FourValue:
    true = left in {FourValue.TRUE, FourValue.BOTH} and right in {FourValue.TRUE, FourValue.BOTH}
    false = left in {FourValue.FALSE, FourValue.BOTH} or right in {FourValue.FALSE, FourValue.BOTH}
    if true and false:
        return FourValue.BOTH
    if true:
        return FourValue.TRUE
    if false:
        return FourValue.FALSE
    return FourValue.UNKNOWN


def disjunction(left: FourValue, right: FourValue) -> FourValue:
    true = left in {FourValue.TRUE, FourValue.BOTH} or right in {FourValue.TRUE, FourValue.BOTH}
    false = left in {FourValue.FALSE, FourValue.BOTH} and right in {FourValue.FALSE, FourValue.BOTH}
    if true and false:
        return FourValue.BOTH
    if true:
        return FourValue.TRUE
    if false:
        return FourValue.FALSE
    return FourValue.UNKNOWN
