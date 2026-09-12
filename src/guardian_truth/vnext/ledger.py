"""Append-only ledger and deterministic indexes. No guessed business facts."""

from __future__ import annotations

from bisect import bisect_left, bisect_right
from collections import defaultdict
from dataclasses import dataclass
from types import MappingProxyType

from .integrity import canonical, digest
from .types import EffectRecord, EntityRef, LedgerEvent, Observation


@dataclass(frozen=True)
class CandidateSet:
    event_ids: tuple[str, ...]
    candidate_set_complete: bool
    completeness_scope: str
    searched_indexes: tuple[str, ...]
    unresolved_selectors: tuple[str, ...] = ()


def observations(events: tuple[LedgerEvent, ...]) -> tuple[Observation, ...]:
    rows = []

    def flatten(value, path=()):
        if isinstance(value, dict):
            for key, item in sorted(value.items()):
                yield from flatten(item, (*path, key))
        elif isinstance(value, list):
            for i, item in enumerate(value):
                yield from flatten(item, (*path, str(i)))
        else:
            yield path, value

    for event in events:
        # Assistant/user assertions and call arguments are not observed state.
        if event.kind != "result" or event.payload_json is None:
            continue
        for path, value in flatten(event.payload):
            if path:
                rows.append(Observation(f"obs:{event.event_id}:{digest(path)}", event.event_id, event.index,
                                        event.actor, ".".join(path), canonical(value).decode("utf-8"),
                                        event.source, event.entity_refs, call_id=event.call_id))
    return tuple(rows)


@dataclass(frozen=True)
class EvidenceLedger:
    events: tuple[LedgerEvent, ...]
    observations: tuple[Observation, ...]
    # Completeness is relative to the supplied trace, never all external reality.
    history_complete: bool = False
    completeness_basis: str | None = None
    effects: tuple[EffectRecord, ...] = ()

    def __post_init__(self):
        if self.history_complete and not self.completeness_basis:
            raise ValueError("explicit trace completeness basis required")
        if ([event.index for event in self.events] != list(range(len(self.events)))
                or len({event.event_id for event in self.events}) != len(self.events)):
            raise ValueError("unique contiguous append-only events required")
        events_by_id = {event.event_id: event for event in self.events}
        if len({item.evidence_id for item in self.observations}) != len(self.observations):
            raise ValueError("unique observation IDs required")
        for item in self.observations:
            event = events_by_id.get(item.event_id)
            if event is None or event.index != item.index or event.kind != "result":
                raise ValueError("observation must reference actual result")
        if self.observations != observations(self.events):
            raise ValueError("observation fields must be exactly reconstructed from source results")
        for effect in self.effects:
            event = events_by_id.get(effect.event_id)
            if event is None or event.kind != "result" or event.call_id != effect.call_id:
                raise ValueError("effect must reference an identity-matched result")

    @classmethod
    def from_events(cls, events: tuple[LedgerEvent, ...], *, history_complete=False, completeness_basis=None):
        return cls(events, observations(events), history_complete, completeness_basis)

    def append(self, events: tuple[LedgerEvent, ...]) -> EvidenceLedger:
        # New snapshot shares immutable old events; caller cannot rewrite prefix.
        combined = self.events + events
        return EvidenceLedger(combined, self.observations + observations(events),
                              False, None, self.effects)  # extending invalidates old complete-history certificate

    def history(self, entity: EntityRef) -> tuple[LedgerEvent, ...]:
        return tuple(event for event in self.events if entity in event.entity_refs)

    def events_between(self, t1: int, t2: int) -> tuple[LedgerEvent, ...]:
        return tuple(event for event in self.events if t1 <= event.index <= t2)

    def known_at(self, fact: Observation, time: int) -> bool:
        return fact in self.observations and fact.index <= time

    def state_at(self, entity: EntityRef, time: int, *, predicate: str | None = None) -> tuple[Observation, ...]:
        """Only observations at this time. Old observations do not prove persistence."""
        return tuple(item for item in self.observations if entity in item.entity_refs and item.index == time
                     and (predicate is None or item.predicate == predicate))

    def latest_confirmed_state(self, entity: EntityRef, before: int, *, predicate: str | None = None) -> tuple[Observation, ...]:
        """Latest SOURCE observations <= boundary, not guaranteed current business state."""
        candidates = [item for item in self.observations if entity in item.entity_refs and item.index <= before
                      and (predicate is None or item.predicate == predicate)]
        latest = {}
        for item in candidates:
            latest[item.predicate] = max(latest.get(item.predicate, item.index), item.index)
        return tuple(item for item in candidates if item.index == latest[item.predicate])

    def calls_of(self, tool: str | None = None, entity: EntityRef | None = None) -> tuple[LedgerEvent, ...]:
        return tuple(event for event in self.events if event.kind == "call"
                     and (tool is None or event.tool and event.tool.name == tool)
                     and (entity is None or entity in event.entity_refs))

    def results_of(self, call_id: str) -> tuple[LedgerEvent, ...]:
        return tuple(event for event in self.events if event.kind == "result" and event.call_id == call_id)

    def effects_of(self, event_id: str) -> tuple[EffectRecord, ...]:
        return tuple(effect for effect in self.effects if effect.event_id == event_id)


class LedgerIndex:
    """Exact candidate retrieval with no top-k cap. Semantic expansion is explicit."""

    def __init__(self, ledger: EvidenceLedger):
        self.ledger = ledger
        indexes = {key: defaultdict(list) for key in ("entity", "actor", "tool", "call", "source", "type")}
        for event in ledger.events:
            for entity in event.entity_refs:
                indexes["entity"][entity].append(event.event_id)
            indexes["actor"][event.actor].append(event.event_id)
            if event.tool:
                indexes["tool"][event.tool.name].append(event.event_id)
            if event.call_id:
                indexes["call"][event.call_id].append(event.event_id)
            indexes["source"][event.source.document].append(event.event_id)
            indexes["type"][event.kind].append(event.event_id)
        self.indexes = MappingProxyType({key: MappingProxyType({value: tuple(ids) for value, ids in index.items()})
                                        for key, index in indexes.items()})
        self.times = tuple(event.index for event in ledger.events)
        self.event_ids = tuple(event.event_id for event in ledger.events)
        self.positions = MappingProxyType({event.event_id: event.index for event in ledger.events})
        self.events_by_id = MappingProxyType({event.event_id: event for event in ledger.events})
        self.events_by_call = MappingProxyType({cid: tuple(self.events_by_id[eid] for eid in ids)
                                               for cid, ids in self.indexes["call"].items()})
        obs_by_event, effects_by_entity = defaultdict(list), defaultdict(list)
        for observation in ledger.observations:
            obs_by_event[observation.event_id].append(observation)
        for effect in ledger.effects:
            effects_by_entity[effect.entity].append(effect)
        self.observations_by_event = MappingProxyType({eid: tuple(items) for eid, items in obs_by_event.items()})
        self.effects_by_entity = MappingProxyType({entity: tuple(items) for entity, items in effects_by_entity.items()})
        value_entities = defaultdict(set)
        for event in ledger.events:
            for entity in event.entity_refs:
                value_entities[entity.value].add(entity)
        for effect in ledger.effects:
            value_entities[effect.entity.value].add(effect.entity)
        self.value_entities = MappingProxyType({value: tuple(sorted(entities, key=lambda e: (e.namespace, e.key, e.value)))
                                              for value, entities in value_entities.items()})

    def search(self, *, entity: EntityRef | None = None, actor: str | None = None,
               tool: str | None = None, call: str | None = None, source: str | None = None,
               event_type: str | None = None, time_range: tuple[int, int] | None = None,
               unresolved_selectors: tuple[str, ...] = ()) -> CandidateSet:
        selectors = {"entity": entity, "actor": actor, "tool": tool, "call": call,
                     "source": source, "type": event_type}
        selected = None
        searched = []
        for key, value in selectors.items():
            if value is not None:
                searched.append(key)
                ids = set(self.indexes[key].get(value, ()))
                selected = ids if selected is None else selected & ids
        if time_range is not None:
            searched.append("time")
            lower, upper = time_range
            ids = set(self.event_ids[bisect_left(self.times, lower):bisect_right(self.times, upper)])
            selected = ids if selected is None else selected & ids
        if selected is None:
            selected = set(self.event_ids)
            searched.append("full_trace")
        # Complete only for exact selectors on the certified supplied trace.
        complete = self.ledger.history_complete and not unresolved_selectors
        return CandidateSet(tuple(sorted(selected, key=self.positions.__getitem__)), complete,
                            self.ledger.completeness_basis or "UNCERTIFIED_SUPPLIED_TRACE",
                            tuple(searched), unresolved_selectors)
