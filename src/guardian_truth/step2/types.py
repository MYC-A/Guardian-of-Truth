"""Core Step 2 value types.

Two orthogonal axes are kept apart at all times:

* Truth of a world fact: TRUE / FALSE / UNKNOWN.
* Support status of a claim about the world: SUPPORTED / CONTRADICTED /
  PENDING / UNSUPPORTED / UNKNOWN.

Absence of evidence for a fact means UNKNOWN truth, while a claim built on
that absence is UNSUPPORTED. These are different questions and are never
collapsed here.

Effect strength forms a partial order (lattice):

    NONE < REQUESTED < INITIATED < EXECUTED < CONFIRMED

OBSERVED lives on a separate axis: it is the strength of a read-side
observation of a state (not the strength of a mutation). A fact can be
OBSERVED at time t1 and later CONFIRMED changed by an authoritative read.
No code path may collapse these levels without a provenance-backed reason.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Truth(str, Enum):
    TRUE = "TRUE"
    FALSE = "FALSE"
    UNKNOWN = "UNKNOWN"


class SupportStatus(str, Enum):
    """Status of a *claim* relative to the Step 2 fact ledger."""

    SUPPORTED = "SUPPORTED"          # a proven fact entails the claim
    CONTRADICTED = "CONTRADICTED"    # a proven fact refutes the claim
    PENDING = "PENDING"              # async/requested evidence only
    UNSUPPORTED = "UNSUPPORTED"      # no evidence either way
    UNKNOWN = "UNKNOWN"              # question itself unresolved (bad entity etc.)


class ResultType(str, Enum):
    """Taxonomy of an observed ToolResult payload (section 14 of the brief).

    Deterministically classified from the payload shape only — never from
    the tool name.
    """

    FAILURE = "FAILURE"                      # explicit error / success=false
    SUCCESS_ACK = "SUCCESS_ACK"              # bare {"success": true} style ack
    BUSINESS_STATE = "BUSINESS_STATE"        # explicit post-state fields
    ASYNC_ACCEPTED = "ASYNC_ACCEPTED"        # queued / processing / pending / scheduled
    OBSERVATION = "OBSERVATION"              # read-shaped entity data
    PARTIAL_SUCCESS = "PARTIAL_SUCCESS"      # mixed success and failure markers
    EMPTY = "EMPTY"                          # {} / null / no content
    MALFORMED = "MALFORMED"                  # not a decodable JSON object
    UNKNOWN = "UNKNOWN"


class EffectClass(str, Enum):
    """What a tool DOES (from contract/description/schema), not its name."""

    READ = "READ"
    OBSERVE = "OBSERVE"          # read-shaped alias used by descriptions
    CHECK = "CHECK"              # verification-flavoured read
    CREATE = "CREATE"
    UPDATE = "UPDATE"
    DELETE = "DELETE"
    REQUEST = "REQUEST"          # initiates an async business process
    ATTEMPT = "ATTEMPT"          # mutation without guaranteed post-state
    CONFIRM = "CONFIRM"          # authoritative verification action
    NOTIFY = "NOTIFY"            # communication only
    UNKNOWN = "UNKNOWN"


_ORDER = ["NONE", "REQUESTED", "INITIATED", "EXECUTED", "CONFIRMED"]


class EffectStrength(str, Enum):
    """Proof strength of an established effect (section 12 of the brief)."""

    NONE = "NONE"
    REQUESTED = "REQUESTED"      # request record created
    INITIATED = "INITIATED"      # accepted / queued / started
    EXECUTED = "EXECUTED"        # state changed, reported by the mutation itself
    CONFIRMED = "CONFIRMED"      # later authoritative observation agrees
    OBSERVED = "OBSERVED"        # read-side observation (separate axis)

    def at_least(self, other: "EffectStrength") -> bool:
        if self is EffectStrength.OBSERVED or other is EffectStrength.OBSERVED:
            raise TypeError("OBSERVED is on a separate axis; compare explicitly")
        return _ORDER.index(self.value) >= _ORDER.index(other.value)

    def __lt__(self, other: "EffectStrength") -> bool:
        if self is EffectStrength.OBSERVED or other is EffectStrength.OBSERVED:
            raise TypeError("OBSERVED is on a separate axis; compare explicitly")
        return _ORDER.index(self.value) < _ORDER.index(other.value)


class Authority(str, Enum):
    """Where the proof of a fact comes from, weakest to strongest."""

    NONE = "NONE"
    TOOL_SELF_REPORT = "TOOL_SELF_REPORT"      # mutation tool's own result fields
    CONTRACT_GUARANTEE = "CONTRACT_GUARANTEE"  # documented postcondition + successful call
    READ_OBSERVATION = "READ_OBSERVATION"      # later read tool returned the state


@dataclass(frozen=True)
class Provenance:
    """Extractive, machine-checkable source of a fact (section 20)."""

    call_id: str
    result_index: int                 # trajectory event index of the result
    json_path: str                    # e.g. "$.status" — must resolve in the result payload
    authority: Authority = Authority.NONE

    def as_dict(self) -> dict:
        return {"call_id": self.call_id, "result_index": self.result_index,
                "json_path": self.json_path, "authority": self.authority.value}


@dataclass(frozen=True)
class WorldFact:
    """A proof-carrying world fact (section 19). Never created without provenance."""

    predicate: str                    # namespaced, e.g. "order.status"
    entity_type: str                  # e.g. "order"
    entity_id: str
    value: str                        # canonical JSON scalar as string
    truth: Truth
    strength: EffectStrength
    authority: Authority
    provenance: Provenance
    observed_at: int                  # trajectory event index
    valid_from: int
    invalidated_at: int | None = None

    def key(self) -> tuple[str, str, str]:
        return (self.entity_type, self.entity_id, self.predicate)

    def as_dict(self) -> dict:
        return {
            "predicate": self.predicate, "entity_type": self.entity_type,
            "entity_id": self.entity_id, "value": self.value,
            "truth": self.truth.value, "strength": self.strength.value,
            "authority": self.authority.value,
            "provenance": self.provenance.as_dict(),
            "observed_at": self.observed_at, "valid_from": self.valid_from,
            "invalidated_at": self.invalidated_at,
        }


class LedgerKind(str, Enum):
    OBSERVE = "OBSERVE"            # read-side observation of a state
    EFFECT = "EFFECT"              # mutation-side effect assertion
    INVALIDATE = "INVALIDATE"      # later observation contradicts earlier one


@dataclass(frozen=True)
class FactEvent:
    """Append-only ledger entry (event sourcing, section 18)."""

    index: int                      # trajectory event index (ordinal time)
    kind: LedgerKind
    fact: WorldFact

    def as_dict(self) -> dict:
        return {"index": self.index, "kind": self.kind.value,
                "fact": self.fact.as_dict()}


@dataclass(frozen=True)
class FactView:
    """Answer to a ledger query."""

    entity_type: str
    entity_id: str
    predicate: str
    truth: Truth
    value: str | None = None
    strength: EffectStrength | None = None
    authority: Authority | None = None
    provenance: Provenance | None = None
    observed_at: int | None = None
    conflicted_history: bool = False     # two observations disagreed at some point
    stale: bool = False                  # an observation exists but is not latest
    events: tuple[str, ...] = ()         # ledger event ids backing this view

    def as_dict(self) -> dict:
        return {
            "entity_type": self.entity_type, "entity_id": self.entity_id,
            "predicate": self.predicate, "truth": self.truth.value,
            "value": self.value, "strength": self.strength.value if self.strength else None,
            "authority": self.authority.value if self.authority else None,
            "provenance": self.provenance.as_dict() if self.provenance else None,
            "observed_at": self.observed_at, "conflicted_history": self.conflicted_history,
            "stale": self.stale, "events": list(self.events),
        }


@dataclass
class ClaimProbeResult:
    """Section 31 diagnostic: candidate proposition vs. the ledger."""

    proposition: str
    support: SupportStatus
    deciding_fact: WorldFact | None = None
    note: str = ""
