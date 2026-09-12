"""Lossless trace and ledger records.

The parser-facing trace schema deliberately keeps source bytes/characters apart
from decoded JSON.  Derived state intervals describe observation order only;
they are not claims about an external system's true current state.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Any

from .records import EvidenceRecord, Span


@dataclass(frozen=True)
class TraceEvent:
    id: str
    index: int
    document_index: int
    turn_id: str
    role: str
    kind: str
    name: str | None
    raw_text: str
    raw_payload: str
    parsed_value: Any
    json_valid: bool
    source: Span
    call_id: str | None = None
    result_id: str | None = None
    timestamp: str | None = None
    transport_call_id: str | None = None
    transport_result_id: str | None = None

    @property
    def value(self) -> Any:
        """Compatibility view; raw and parsed forms remain available separately."""
        return self.parsed_value if self.json_valid else self.raw_payload


class StateValidityStatus(str, Enum):
    ACTIVE_OBSERVATION = "active_observation"
    SUPERSEDED_OBSERVATION = "superseded_observation"


@dataclass(frozen=True)
class StateValidityRecord:
    id: str
    evidence_id: str
    subject: str
    predicate: str
    object: Any
    entities: tuple[tuple[str, Any], ...]
    valid_from_index: int
    valid_to_index: int | None
    supersedes: tuple[str, ...]
    superseded_by: str | None
    status: StateValidityStatus


@dataclass(frozen=True)
class CompletenessCertificateRecord:
    id: str
    evidence_id: str
    scope_subject: str
    scope_predicate: str
    scope_object: Any
    entities: tuple[tuple[str, Any], ...]
    valid_from_index: int
    valid_to_index: int | None
    exhaustive: bool
    basis: str
    source: Span
    provenance: str


@dataclass(frozen=True)
class EvidenceLedger:
    records: tuple[EvidenceRecord, ...]
    state_validity: tuple[StateValidityRecord, ...]
    completeness_certificates: tuple[CompletenessCertificateRecord, ...]
