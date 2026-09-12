"""Grounded candidate meaning. These records are NOT observed facts."""

from dataclasses import dataclass

from .proof_records import ProofAtom
from .types import Reason


@dataclass(frozen=True)
class OperationalChoice:
    choice_id: str
    parent_hypothesis_id: str
    atoms: tuple[ProofAtom, ...]
    must_be_true: bool
    covered_clauses: tuple[str, ...]
    source_quotes: tuple[str, ...]
    field_clause_ids: tuple[str, ...] = ()


@dataclass(frozen=True)
class OperationalBindings:
    choices: tuple[OperationalChoice, ...]
    required_clauses: tuple[str, ...]
    failures: tuple[Reason, ...]
    discarded: tuple[tuple[str, str], ...] = ()
