"""Explicit external product policies. UNKNOWN/UNRESOLVED is never safety proof."""

from dataclasses import dataclass
from enum import Enum

from .decision import CertifiedCoreResult
from .types import CoreStatus


class AdapterMode(str, Enum):
    AUDIT = "audit"
    SAFETY_FIRST = "safety-first"
    COMPETITION = "competition-required-binary"


@dataclass(frozen=True)
class ProductDecision:
    core_status: CoreStatus
    binary_label: int | None
    mode: AdapterMode
    mapping_version: str
    used_fallback: bool


def adapt(result: CertifiedCoreResult, *, mode: AdapterMode = AdapterMode.AUDIT) -> ProductDecision:
    if not isinstance(result, CertifiedCoreResult) or not isinstance(mode, AdapterMode):
        raise TypeError("external adapter requires checked Core result and explicit mode")
    status = result.status
    if status is CoreStatus.PROVED_ERROR:
        label, fallback = 1, False
    elif status is CoreStatus.PROVED_NO_ERROR:
        label, fallback = 0, False
    else:
        fallback = True
        label = None if mode is AdapterMode.AUDIT else 1 if mode is AdapterMode.SAFETY_FIRST else int(status is CoreStatus.INCONSISTENT)
    return ProductDecision(status, label, mode, "guardian-vnext-product-mapping-v1", fallback)
