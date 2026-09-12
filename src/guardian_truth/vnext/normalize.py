"""Deterministic lossless normalization, with no semantic-effect inference."""

from __future__ import annotations

from collections import defaultdict
import re

from guardian_truth.parsing import MARKER, parse_events
from .integrity import canonical
from .types import EntityRef, LedgerEvent, Span, ToolIdentity


ATTR = re.compile(r'\b([A-Za-z_][A-Za-z0-9_]*)="([^"\n]*)"')


def explicit_entities(payload) -> tuple[EntityRef, ...]:
    """Only exact source IDs/names; no semantic resolution or guessed aliases."""
    found = []

    def visit(value, prefix=""):
        if isinstance(value, dict):
            for key, item in sorted(value.items()):
                path = prefix + key
                if (key in {"id", "name"} or key.endswith("_id")) and type(item) in {str, int}:
                    found.append(EntityRef(path, str(item)))
                if isinstance(item, (dict, list)):
                    visit(item, path + ".")
        elif isinstance(value, list):
            for i, item in enumerate(value):
                visit(item, prefix + str(i) + ".")

    visit(payload)
    return tuple(found)


def normalize(prompt: str, response: str, *, tool_identities: tuple[ToolIdentity, ...] = ()) -> tuple[LedgerEvent, ...]:
    # Supplied identities are deterministic metadata, never inferred from names.
    identities = defaultdict(list)
    for identity in tool_identities:
        identities[identity.name].append(identity)
    documents = {"prompt": prompt, "response": response}
    events = []
    calls = {}
    transport_ids = defaultdict(list)
    pending = set()
    for parsed in (*parse_events(prompt, "prompt"), *parse_events(response, "response")):
        index = len(events)
        eid = f"e{index}"
        raw = documents[parsed.source.document][parsed.source.start:parsed.source.end]
        marker = MARKER.match(raw)
        attributes = dict(ATTR.findall(marker.group() if marker else ""))
        payload_json = canonical(parsed.value).decode("utf-8") if parsed.json_valid else None
        tool = None
        if parsed.name:
            matches = identities[parsed.name]
            tool = matches[0] if len(matches) == 1 else ToolIdentity(parsed.name)
            explicit = ToolIdentity(parsed.name, attributes.get("provider"), attributes.get("version"),
                                    attributes.get("schema_sha256"))
            # Header metadata wins; missing fields can be populated only by unique metadata.
            tool = ToolIdentity(parsed.name, explicit.provider or tool.provider,
                                explicit.version or tool.version, explicit.schema_sha256 or tool.schema_sha256)
        call_id, candidates, issue = None, (), None
        tid = attributes.get("call_id") or attributes.get("request_id")
        requestor = parsed.role if parsed.kind in {"call", "result"} else None
        if parsed.kind == "call":
            call_id = f"call:{eid}"
            calls[call_id] = (parsed.role, tool)
            pending.add(call_id)
            if tid:
                transport_ids[tid].append(call_id)
        elif parsed.kind == "result":
            if tid:
                # An explicit unknown/mismatched ID is never repaired by FIFO.
                eligible = list(transport_ids.get(tid, ()))
            else:
                eligible = sorted(pending)
            eligible = [cid for cid in eligible if calls[cid] == (parsed.role, tool)]
            candidates = tuple(eligible)
            if len(eligible) == 1 and parsed.role != "unknown":
                call_id = eligible[0]
                pending.discard(call_id)
            else:
                issue = "AMBIGUOUS_CALL_IDENTITY" if eligible else "UNMATCHED_CALL_IDENTITY"
        events.append(LedgerEvent(eid, index, "tool" if parsed.kind == "result" else parsed.role,
                                 parsed.kind, Span(parsed.source.document, parsed.source.start, parsed.source.end),
                                 raw, payload_json, tool, call_id, candidates, requestor,
                                 attributes.get("timestamp") or attributes.get("time") or attributes.get("created_at"),
                                 explicit_entities(parsed.value) if parsed.json_valid else (), issue))
    return tuple(events)


def tool_identity(name: str, schema: dict, *, provider: str | None = None,
                  version: str | None = None) -> ToolIdentity:
    from .integrity import digest
    return ToolIdentity(name, provider, version, digest(schema))
