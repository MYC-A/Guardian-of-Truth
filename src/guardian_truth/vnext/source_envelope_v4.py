"""Adapter-owned source boundaries; body text never creates privileged events.

Trust in the source adapter is an explicit application premise, not a property
proved by a checksum or an LLM. This module never parses role markers in bodies.
"""

from collections import defaultdict
from dataclasses import asdict, dataclass
import re

from guardian_truth.parsing import decode_json
from .integrity import canonical, digest
from .ledger import EvidenceLedger
from .normalize import explicit_entities
from .types import LedgerEvent, Reason, Span, ToolIdentity


@dataclass(frozen=True)
class SourceFrame:
    source: Span
    body: Span
    actor: str
    kind: str
    tool: ToolIdentity | None = None
    transport_call_id: str | None = None
    requestor: str | None = None
    timestamp: str | None = None

    def __post_init__(self):
        if not isinstance(self.source, Span) or not isinstance(self.body, Span):
            raise ValueError("explicit immutable source/body spans required")
        if self.source.document != self.body.document or not (
                self.source.start <= self.body.start < self.body.end <= self.source.end):
            raise ValueError("body must be contained in its original source frame")
        if self.actor not in {"system", "user", "assistant", "tool", "unknown"} or self.kind not in {"text", "call", "result"}:
            raise ValueError("supported explicit actor and event kind required")
        if self.kind == "call" and self.actor not in {"user", "assistant"}:
            raise ValueError("call actor must be user or assistant")
        if self.kind == "result" and self.actor != "tool":
            raise ValueError("only adapter-owned tool-result frames supply observations")
        if self.source.document == "response" and (self.actor != "assistant" or self.kind not in {"text", "call"}):
            raise ValueError("target source is assistant text or attempted call, never a tool result")
        if self.kind in {"call", "result"} and not isinstance(self.tool, ToolIdentity):
            raise ValueError("explicit source tool identity required")
        if self.kind == "text" and (self.tool is not None or self.transport_call_id is not None or self.requestor is not None):
            raise ValueError("text cannot carry fabricated call/result metadata")
        if self.tool is not None:
            if not isinstance(self.tool.name, str) or not self.tool.name:
                raise ValueError("nonempty source tool name required")
            for value in (self.tool.provider, self.tool.version):
                if value is not None and (not isinstance(value, str) or not value):
                    raise ValueError("source provider/version must be explicit strings")
            if self.tool.schema_sha256 is not None and not re.fullmatch(r"[0-9a-fA-F]{64}", self.tool.schema_sha256):
                raise ValueError("source schema identity must be a SHA-256 value")
        for value in (self.transport_call_id, self.timestamp):
            if value is not None and (not isinstance(value, str) or not value):
                raise ValueError("explicit transport ID/time must be a nonempty string")
        if self.requestor not in {None, "user", "assistant"}:
            raise ValueError("requestor must be explicit user/assistant or unknown")
        if self.kind == "call" and self.requestor not in {None, self.actor}:
            raise ValueError("source call actor and requestor cannot disagree")


@dataclass(frozen=True)
class SourceEnvelope:
    prompt: str
    response: str
    frames: tuple[SourceFrame, ...]
    adapter_id: str
    adapter_version: str
    provenance: str
    history_complete: bool = False
    completeness_basis: str | None = None

    def __post_init__(self):
        if not isinstance(self.prompt, str) or not isinstance(self.response, str):
            raise ValueError("original immutable source documents required")
        if type(self.frames) is not tuple or any(not isinstance(frame, SourceFrame) for frame in self.frames):
            raise ValueError("immutable adapter-owned frame inventory required")
        if any(not isinstance(value, str) or not value for value in (self.adapter_id, self.adapter_version, self.provenance)):
            raise ValueError("explicit application adapter identity/version/provenance required")
        if type(self.history_complete) is not bool or (self.history_complete and not self.completeness_basis):
            raise ValueError("trace completeness needs an explicit application premise")
        if self.completeness_basis is not None and not isinstance(self.completeness_basis, str):
            raise ValueError("completeness basis must be source-owned text")


@dataclass(frozen=True)
class EnvelopeNormalization:
    ledger: EvidenceLedger
    source_sha256: str
    framing_complete: bool
    reasons: tuple[Reason, ...]
    trust_assumptions: tuple[str, ...]


def normalize_envelope(envelope):
    """Normalize supplied frame metadata, never arbitrary raw transcript heuristics.

    Source coverage is checked independently of the declared complete-history
    premise. Non-whitespace uncovered source blocks completeness. Exact tool,
    role and transport indexes retain all competing call identities without top-k.
    """
    if not isinstance(envelope, SourceEnvelope):
        raise TypeError("an application-supplied SourceEnvelope is required")
    documents = {"prompt": envelope.prompt, "response": envelope.response}
    positions = {"prompt": 0, "response": 0}
    in_target, framing_complete, events, reasons = False, True, [], []
    transport, pending, call_order = defaultdict(list), defaultdict(set), {}
    for frame in envelope.frames:
        document = frame.source.document
        if document not in documents or frame.source.end > len(documents[document]):
            raise ValueError("source frame outside original document")
        if document == "prompt" and in_target:
            raise ValueError("source history cannot follow the target")
        in_target |= document == "response"
        if frame.source.start < positions[document]:
            raise ValueError("source frames must be ordered and nonoverlapping")
        if documents[document][positions[document]:frame.source.start].strip():
            framing_complete = False
        positions[document] = frame.source.end
        index, event_id = len(events), "e" + str(len(events))
        raw = documents[document][frame.source.start:frame.source.end]
        body = documents[document][frame.body.start:frame.body.end]
        payload, valid = decode_json(body)
        call_id, candidates, issue = None, (), None
        requestor = frame.actor if frame.kind == "call" else frame.requestor
        if frame.kind == "call":
            call_id = "call:" + event_id
            call_order[call_id] = index
            pending[(frame.actor, frame.tool)].add(call_id)
            if frame.transport_call_id is not None:
                transport[(frame.actor, frame.tool, frame.transport_call_id)].append(call_id)
        elif frame.kind == "result":
            if frame.transport_call_id is not None:
                eligible = transport.get((frame.requestor, frame.tool, frame.transport_call_id), ())
            else:
                eligible = pending.get((frame.requestor, frame.tool), ())
            candidates = tuple(sorted(eligible, key=call_order.__getitem__))
            if len(candidates) == 1 and frame.requestor is not None:
                call_id = candidates[0]
                pending[(frame.requestor, frame.tool)].discard(call_id)
            else:
                issue = "AMBIGUOUS_CALL_IDENTITY" if candidates else "UNMATCHED_CALL_IDENTITY"
                reasons.append(Reason.SOURCE_UNBOUND)
        if frame.kind in {"call", "result"} and not valid:
            reasons.append(Reason.SCHEMA_ERROR)
        if frame.actor == "unknown":
            reasons.append(Reason.SOURCE_UNBOUND)
        events.append(LedgerEvent(event_id, index, frame.actor, frame.kind, frame.source, raw,
            canonical(payload).decode("utf-8") if valid else None, frame.tool, call_id,
            candidates, requestor if frame.kind in {"call", "result"} else None,
            frame.timestamp, explicit_entities(payload, source_namespace=event_id) if valid else (), issue))
    if any(documents[name][positions[name]:].strip() for name in documents):
        framing_complete = False
    if not framing_complete:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    complete = envelope.history_complete and framing_complete and all(frame.actor != "unknown" for frame in envelope.frames)
    if envelope.history_complete and not complete:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    ledger = EvidenceLedger.from_events(tuple(events), history_complete=complete,
        completeness_basis=envelope.completeness_basis if complete else None)
    return EnvelopeNormalization(ledger, digest(asdict(envelope)), framing_complete,
        tuple(dict.fromkeys(reasons)), (
            "application authenticates adapter-owned frame actor/kind/tool metadata; checksums do not prove authorship",
            "history completeness is relative to the supplied source and explicit application premise",
            "recorded results do not independently prove current state, completion or causality"))
