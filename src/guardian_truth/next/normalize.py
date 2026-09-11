"""Deterministic trace normalisation with explicit attempted/result boundaries."""

from __future__ import annotations

from collections import defaultdict, deque
from typing import Any, Iterable

from guardian_truth.parsing import parse_events

from .records import EvidenceRecord, EvidenceStatus, NormalizedEvent, Span


def _source(source) -> Span:
    return Span(source.document, source.start, source.end)


def normalize_trace(prompt: str, response: str) -> list[NormalizedEvent]:
    raw = parse_events(prompt, "prompt") + parse_events(response, "response")
    pending: dict[str, deque[str]] = defaultdict(deque)
    events: list[NormalizedEvent] = []
    for index, event in enumerate(raw):
        event_id = f"e{index}"
        call_id = None
        if event.kind == "call":
            call_id = f"call:{index}"
            if event.name:
                pending[event.name].append(call_id)
        elif event.kind == "result" and event.name and pending[event.name]:
            call_id = pending[event.name].popleft()
        events.append(NormalizedEvent(
            id=event_id,
            index=index,
            role=event.role,
            kind=event.kind,
            name=event.name,
            value=event.value if event.json_valid else event.text,
            json_valid=event.json_valid,
            source=_source(event.source),
            call_id=call_id,
        ))
    return events


def _entities(value: Any) -> tuple[tuple[str, Any], ...]:
    if not isinstance(value, dict):
        return ()
    return tuple(sorted(
        ((key, item) for key, item in value.items()
         if (key == "id" or key.endswith("_id")) and type(item) in (str, int)),
        key=lambda pair: pair[0],
    ))


def _flatten(value: Any, prefix: tuple[str, ...] = ()) -> Iterable[tuple[tuple[str, ...], Any]]:
    if isinstance(value, dict):
        for key in sorted(value):
            yield from _flatten(value[key], prefix + (key,))
    elif isinstance(value, list):
        for index, item in enumerate(value):
            yield from _flatten(item, prefix + (str(index),))
    else:
        yield prefix, value


def _failed(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("success") is False or value.get("ok") is False:
        return True
    status = value.get("status")
    return isinstance(status, str) and status.lower() in {"failed", "failure", "error", "rejected"}


def build_evidence(events: list[NormalizedEvent]) -> list[EvidenceRecord]:
    """Create append-only evidence.  Failure never implies confirmed no-effect."""
    records: list[EvidenceRecord] = []
    for event in events:
        if event.kind == "call":
            records.append(EvidenceRecord(
                id=f"ev:{len(records)}",
                event_id=event.id,
                subject=event.call_id or event.id,
                predicate="call_attempted",
                object=event.name,
                status=EvidenceStatus.ATTEMPTED,
                source=event.source,
                entities=_entities(event.value),
                freshness=event.index,
            ))
        elif event.kind == "result":
            failed = _failed(event.value)
            records.append(EvidenceRecord(
                id=f"ev:{len(records)}",
                event_id=event.id,
                subject=event.call_id or event.id,
                predicate="call_result",
                object="failed" if failed else "returned",
                status=EvidenceStatus.FAILED if failed else EvidenceStatus.OBSERVED,
                source=event.source,
                entities=_entities(event.value),
                freshness=event.index,
            ))
            if event.json_valid:
                entities = _entities(event.value)
                for path, value in _flatten(event.value):
                    if not path:
                        continue
                    records.append(EvidenceRecord(
                        id=f"ev:{len(records)}",
                        event_id=event.id,
                        subject=event.name or "tool_result",
                        predicate=".".join(path),
                        object=value,
                        status=EvidenceStatus.OBSERVED,
                        source=event.source,
                        entities=entities,
                        freshness=event.index,
                    ))
    return records
