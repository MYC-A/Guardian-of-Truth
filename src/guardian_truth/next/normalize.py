"""Deterministic trace normalisation with explicit attempted/result boundaries."""

from __future__ import annotations

from collections import defaultdict, deque
import re
from typing import Any, Iterable

from guardian_truth.parsing import parse_events

from .records import EvidenceRecord, EvidenceStatus, FourValue, Span, ToolEffectContract
from .trace_records import (
    CompletenessCertificateRecord,
    EvidenceLedger,
    StateValidityRecord,
    StateValidityStatus,
    TraceEvent,
)


def _source(source) -> Span:
    return Span(source.document, source.start, source.end)


_HEADER_ATTRIBUTE = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)="([^"]*)"')


def _raw_payload(raw_text: str, parsed_text: str, kind: str) -> str:
    if kind == "text":
        return raw_text
    # Tool-event sources contain their marker.  Retain every character after
    # the header delimiter, including leading/trailing whitespace.
    close_marker = "\u27e7"
    close = raw_text.find(close_marker)
    if close >= 0:
        return raw_text[close + len(close_marker):]
    # Legacy arrow traces have a colon delimiter.  The parser's body is still
    # losslessly locatable in the source slice in all non-empty cases.
    at = raw_text.find(parsed_text) if parsed_text else -1
    return raw_text[at:] if at >= 0 else raw_text


def _header_attributes(raw_text: str) -> dict[str, str]:
    header_end = raw_text.find("\n")
    header = raw_text if header_end < 0 else raw_text[:header_end]
    return dict(_HEADER_ATTRIBUTE.findall(header))


def normalize_trace(prompt: str, response: str) -> list[TraceEvent]:
    documents = {"prompt": prompt, "response": response}
    parsed_by_document = {
        "prompt": parse_events(prompt, "prompt"),
        "response": parse_events(response, "response"),
    }
    pending: dict[tuple[str, str], deque[str]] = defaultdict(deque)
    transport_calls: dict[str, str] = {}
    events: list[TraceEvent] = []
    document_indices = {"prompt": 0, "response": 0}
    raw = parsed_by_document["prompt"] + parsed_by_document["response"]
    for index, event in enumerate(raw):
        document_index = document_indices[event.source.document]
        document_indices[event.source.document] += 1
        event_id = f"e{index}"
        call_id = None
        result_id = None
        source = _source(event.source)
        exact = documents[event.source.document][source.start:source.end]
        attributes = _header_attributes(exact)
        transport_call_id = attributes.get("call_id") or attributes.get("request_id")
        transport_result_id = attributes.get("result_id")
        if event.kind == "call":
            call_id = f"call:{index}"
            if event.name:
                pending[(event.name, event.role)].append(call_id)
            if transport_call_id and transport_call_id not in transport_calls:
                transport_calls[transport_call_id] = call_id
        elif event.kind == "result":
            result_id = f"result:{index}"
            if transport_call_id:
                call_id = transport_calls.get(transport_call_id)
                queue = pending[(event.name or "", event.role)]
                if call_id in queue:
                    queue.remove(call_id)
            if call_id is None and event.name and pending[(event.name, event.role)]:
                call_id = pending[(event.name, event.role)].popleft()
        payload = _raw_payload(exact, event.text, event.kind)
        events.append(TraceEvent(
            id=event_id,
            index=index,
            document_index=document_index,
            turn_id=f"{event.source.document}:turn:{document_index}",
            role=event.role,
            kind=event.kind,
            name=event.name,
            raw_text=exact,
            raw_payload=payload,
            parsed_value=event.value,
            json_valid=event.json_valid,
            source=source,
            call_id=call_id,
            result_id=result_id,
            timestamp=(attributes.get("timestamp") or attributes.get("time")
                       or attributes.get("created_at")),
            transport_call_id=transport_call_id,
            transport_result_id=transport_result_id,
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


def _succeeded(value: Any) -> bool:
    if not isinstance(value, dict):
        return False
    if value.get("success") is True or value.get("ok") is True:
        return True
    status = value.get("status")
    return isinstance(status, str) and status.lower() in {"success", "succeeded", "completed", "ok"}


def _read_path(value: Any, path: str) -> Any:
    for part in path.split("."):
        if not isinstance(value, dict) or part not in value:
            return None
        value = value[part]
    return value


def _contract_succeeded(value: Any, contract: ToolEffectContract) -> bool:
    if not contract.success_predicate:
        return _succeeded(value)
    for clause in contract.success_predicate:
        path, separator, expected = clause.partition("=")
        if not separator or not path or _read_path(value, path) is None:
            return False
        actual = _read_path(value, path)
        rendered = str(actual).lower() if isinstance(actual, bool) else str(actual)
        if rendered.casefold() != expected.casefold():
            return False
    return True


def build_evidence(events: list[TraceEvent],
                   contracts: dict[str, ToolEffectContract] | None = None) -> list[EvidenceRecord]:
    """Create append-only evidence.  Failure never implies confirmed no-effect."""
    records: list[EvidenceRecord] = []
    calls: dict[str, TraceEvent] = {}
    for event in events:
        if event.kind == "call":
            if event.call_id:
                calls[event.call_id] = event
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
            contract = (contracts or {}).get(event.name or "")
            call = calls.get(event.call_id or "")
            if contract is not None and call is not None:
                call_entities = _entities(call.value)
                if _contract_succeeded(event.value, contract):
                    for effect in contract.guaranteed_effects:
                        records.append(EvidenceRecord(
                            id=f"ev:{len(records)}", event_id=event.id,
                            subject=event.call_id or event.id, predicate="effect_confirmed",
                            object=effect, status=EvidenceStatus.CONFIRMED, source=event.source,
                            entities=call_entities, freshness=event.index,
                            provenance=contract.provenance,
                        ))
                elif failed and contract.failure_no_effect is FourValue.TRUE:
                    for effect in contract.guaranteed_effects:
                        records.append(EvidenceRecord(
                            id=f"ev:{len(records)}", event_id=event.id,
                            subject=event.call_id or event.id, predicate="no_effect",
                            object=effect, status=EvidenceStatus.CONFIRMED, source=event.source,
                            entities=call_entities, freshness=event.index,
                            provenance=contract.provenance,
                            completeness_certificate=f"contract:{contract.tool}:failure_no_effect",
                        ))
    return records


def _state_validity(records: list[EvidenceRecord]) -> tuple[StateValidityRecord, ...]:
    """Derive non-destructive observation intervals for repeated scoped facts."""
    state_indices: list[int] = []
    grouped: dict[tuple[str, str, tuple[tuple[str, Any], ...]], list[int]] = defaultdict(list)
    for index, record in enumerate(records):
        if record.freshness is None or record.status is not EvidenceStatus.OBSERVED:
            continue
        if record.predicate in {"call_attempted", "call_result"}:
            continue
        try:
            key = (record.subject, record.predicate, record.entities)
            hash(key)
        except TypeError:
            continue
        state_indices.append(index)
        grouped[key].append(index)

    later: dict[int, int] = {}
    earlier: dict[int, tuple[int, ...]] = {}
    for indices in grouped.values():
        ordered = sorted(indices, key=lambda item: (records[item].freshness, item))
        for position, record_index in enumerate(ordered):
            if position + 1 < len(ordered):
                later[record_index] = ordered[position + 1]
            earlier[record_index] = tuple(ordered[:position])

    output: list[StateValidityRecord] = []
    for record_index in state_indices:
        record = records[record_index]
        next_index = later.get(record_index)
        next_record = records[next_index] if next_index is not None else None
        output.append(StateValidityRecord(
            id=f"state:{len(output)}",
            evidence_id=record.id,
            subject=record.subject,
            predicate=record.predicate,
            object=record.object,
            entities=record.entities,
            valid_from_index=record.freshness,
            valid_to_index=next_record.freshness if next_record is not None else None,
            supersedes=tuple(records[item].id for item in earlier[record_index]),
            superseded_by=next_record.id if next_record is not None else None,
            status=(StateValidityStatus.SUPERSEDED_OBSERVATION if next_record is not None
                    else StateValidityStatus.ACTIVE_OBSERVATION),
        ))
    return tuple(output)


def _completeness(records: list[EvidenceRecord]) -> tuple[CompletenessCertificateRecord, ...]:
    output: list[CompletenessCertificateRecord] = []
    for record in records:
        if not record.completeness_certificate or record.freshness is None:
            continue
        output.append(CompletenessCertificateRecord(
            id=f"certificate:{len(output)}",
            evidence_id=record.id,
            scope_subject=record.subject,
            scope_predicate=record.predicate,
            scope_object=record.object,
            entities=record.entities,
            valid_from_index=record.freshness,
            valid_to_index=None,
            exhaustive=True,
            basis=record.completeness_certificate,
            source=record.source,
            provenance=record.provenance,
        ))
    return tuple(output)


def build_evidence_ledger(events: list[TraceEvent],
                          contracts: dict[str, ToolEffectContract] | None = None) -> EvidenceLedger:
    records = build_evidence(events, contracts)
    return EvidenceLedger(
        records=tuple(records),
        state_validity=_state_validity(records),
        completeness_certificates=_completeness(records),
    )
