"""Append-only fact ledger with temporal queries (sections 18-19).

The ledger stores FactEvents (OBSERVE / EFFECT / INVALIDATE) rather than a
mutable state map. All queries take an `as_of` trajectory index so that a
later ToolResult can never retroactively justify an earlier claim:

    evidence_time <= claim/action_time

Queries:

* LATEST(entity, predicate, as_of)  — value of the latest observation
* PRIOR_TRUE(predicate, entity, as_of) — was the fact ever established before
* AT_TIME(entity, predicate, index, known_at) — observation valid at that index and
  observed no later than known_at (default index)

Frame assumption policy: observations are returned with their observed_at
index and a staleness flag. Persistence of an observation is EXPOSED, never
assumed — the caller (Step 1/3) decides whether its source guarantees
persistence. Mutation effects are never extended by time alone.
"""

from __future__ import annotations

from .types import (Authority, EffectStrength, FactEvent, FactView,
                    LedgerKind, Provenance, SupportStatus, Truth, WorldFact)


class LedgerQueryError(ValueError):
    pass


def _fact_from_event(event: FactEvent) -> WorldFact:
    return event.fact


class FactLedger:
    """Append-only event log. One instance per trajectory."""

    def __init__(self) -> None:
        self.events: list[FactEvent] = []
        self._by_key: dict[tuple[str, str, str], list[FactEvent]] = {}
        self._event_ids: set[str] = set()

    # ------------------------------------------------------------------ build
    def append(self, event: FactEvent) -> str:
        if not isinstance(event, FactEvent):
            raise TypeError("FactEvent required")
        fact = event.fact
        if fact.provenance is None or not fact.provenance.json_path:
            raise LedgerQueryError("refusing to append a fact without provenance")
        if fact.observed_at != event.index:
            raise LedgerQueryError("event index must equal fact observed_at")
        event_id = f"e{len(self.events):04d}"
        self.events.append(event)
        self._by_key.setdefault(fact.key(), []).append(event)
        return event_id

    # ---------------------------------------------------------------- queries
    def _ordered(self, entity_type: str, entity_id: str, predicate: str) -> list[FactEvent]:
        return sorted(self._by_key.get((entity_type, entity_id, predicate), []),
                      key=lambda e: e.index)

    def latest(self, entity_type: str, entity_id: str, predicate: str,
               *, as_of: int | None = None) -> FactView:
        """Latest observation of (entity, predicate) at or before `as_of`."""
        events = [e for e in self._ordered(entity_type, entity_id, predicate)
                  if as_of is None or e.index <= as_of]
        if not events:
            return FactView(entity_type, entity_id, predicate, Truth.UNKNOWN)
        top = events[-1]
        values = [e.fact.value for e in events if e.fact.value is not None]
        conflicted = len(set(values)) > 1
        fact = top.fact
        backing = tuple(
            f"e{i:04d}" for i, e in enumerate(self.events)
            if e.fact.key() == (entity_type, entity_id, predicate)
            and (as_of is None or e.index <= as_of))
        return FactView(
            entity_type=entity_type, entity_id=entity_id, predicate=predicate,
            truth=fact.truth, value=fact.value, strength=fact.strength,
            authority=fact.authority, provenance=fact.provenance,
            observed_at=fact.observed_at,
            conflicted_history=conflicted,
            events=backing,
        )

    def prior_true(self, entity_type: str, entity_id: str, predicate: str,
                   value: str, *, before: int) -> FactView:
        """Was (entity, predicate) ever observed equal to `value` strictly
        before index `before`? Never infers FALSE from silence."""
        events = [e for e in self._ordered(entity_type, entity_id, predicate)
                  if e.index < before and e.fact.value == value
                  and e.fact.truth is Truth.TRUE]
        if not events:
            return FactView(entity_type, entity_id, predicate, Truth.UNKNOWN)
        first = events[0].fact
        return FactView(
            entity_type=entity_type, entity_id=entity_id, predicate=predicate,
            truth=Truth.TRUE, value=value, strength=first.strength,
            authority=first.authority, provenance=first.provenance,
            observed_at=first.observed_at,
        )

    def at_time(self, entity_type: str, entity_id: str, predicate: str,
                index: int, *, known_at: int | None = None,
                allow_late_observation: bool = False) -> FactView:
        """Observation valid (world time) at `index` AND observed (evidence time)
        no later than `known_at` (default: `index`).

        Two clocks are kept apart: valid_from/invalidated_at describe world time;
        observed_at/event.index describe when the evidence became available.
        Admissibility of an action needs evidence available before it, so a fact
        observed after `known_at` is ignored even if its valid_from is retroactive.
        `allow_late_observation=True` is an explicit retrospective-factual contract
        (e.g. an immutable attribute later read back); it must never be used to let
        a later approval satisfy an earlier mandatory process.
        """
        horizon = index if known_at is None else known_at
        candidates = [e for e in self._ordered(entity_type, entity_id, predicate)
                      if e.fact.valid_from <= index
                      and (e.fact.invalidated_at is None or e.fact.invalidated_at > index)
                      and (allow_late_observation or e.index <= horizon)]
        if not candidates:
            return FactView(entity_type, entity_id, predicate, Truth.UNKNOWN)
        fact = candidates[-1].fact
        return FactView(
            entity_type=entity_type, entity_id=entity_id, predicate=predicate,
            truth=fact.truth, value=fact.value, strength=fact.strength,
            authority=fact.authority, provenance=fact.provenance,
            observed_at=fact.observed_at,
        )

    def all_facts(self) -> list[WorldFact]:
        return [event.fact for event in self.events]

    def conflicts(self) -> list[tuple[WorldFact, WorldFact]]:
        """Pairs of same-key observations with different truth values."""
        out = []
        for key, events in self._by_key.items():
            true_vals = [e for e in sorted(events, key=lambda x: x.index)
                         if e.fact.truth is Truth.TRUE and e.fact.value is not None]
            seen: dict[str, WorldFact] = {}
            for e in true_vals:
                if e.fact.value in seen:
                    out.append((seen[e.fact.value], e.fact))
                else:
                    seen[e.fact.value] = e.fact
        return out

    # ------------------------------------------------------- claim probe (§31)
    def probe(self, proposition: "Proposition") -> "ProbeAnswer":
        """Small diagnostic: is a candidate proposition supported by the ledger?

        The proposition supplies its own comparison semantics; this helper
        only looks up LATEST as of the proposition's time.
        """
        view = self.latest(proposition.entity_type, proposition.entity_id,
                           proposition.predicate, as_of=proposition.as_of)
        if view.truth is Truth.UNKNOWN:
            return ProbeAnswer(SupportStatus.UNKNOWN if proposition.entity_id is None
                               else SupportStatus.UNSUPPORTED, view,
                               "no proven fact for this entity/predicate")
        if view.value is None:
            return ProbeAnswer(SupportStatus.UNSUPPORTED, view, "fact has no scalar value")
        if proposition.expected_value is None:
            return ProbeAnswer(SupportStatus.SUPPORTED, view, "a proven fact exists")
        if view.value == proposition.expected_value:
            if view.strength in (EffectStrength.REQUESTED, EffectStrength.INITIATED):
                return ProbeAnswer(SupportStatus.PENDING, view,
                                   f"only {view.strength.value}-strength evidence")
            return ProbeAnswer(SupportStatus.SUPPORTED, view, "value matches proven fact")
        return ProbeAnswer(SupportStatus.CONTRADICTED, view,
                           f"proven value {view.value} != claimed {proposition.expected_value}")


class Proposition:
    """A candidate factual proposition for the §31 diagnostic probe."""

    def __init__(self, entity_type: str, entity_id: str, predicate: str,
                 expected_value: str | None = None, as_of: int | None = None):
        self.entity_type = entity_type
        self.entity_id = entity_id
        self.predicate = predicate
        self.expected_value = expected_value
        self.as_of = as_of


class ProbeAnswer:
    def __init__(self, support: SupportStatus, view: FactView, note: str = ""):
        self.support = support
        self.view = view
        self.note = note

    def as_dict(self) -> dict:
        return {"support": self.support.value, "note": self.note,
                "fact": self.view.as_dict()}
