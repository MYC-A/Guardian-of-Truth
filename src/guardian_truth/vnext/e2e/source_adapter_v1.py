"""E2E V1 source adapter (Phase 2).

Composes the trajectory documents, normalizes them with the trusted marker
transport (authority comes from transport markers, never from body text) and
splits the target assistant output into TEXT_VIEW (natural-language
assertions, used by claim extraction) and ACTION_VIEW (attempted tool calls,
used by policy/goal operational evaluation). The goal firewall source is the
user request only: frontends never see history, target action or results.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical, digest
from ..normalize import normalize
from ..types import LedgerEvent, ToolIdentity


def _tool_identities(metadata: tuple[dict, ...]) -> tuple[ToolIdentity, ...]:
    return tuple(ToolIdentity(item.get("name"), item.get("provider"), item.get("version"),
                               item.get("schema_sha256")) for item in metadata if item.get("name"))


@dataclass(frozen=True)
class SourceProjection:
    """TEXT_VIEW / ACTION_VIEW projection of the target assistant output."""
    text_events: tuple[LedgerEvent, ...]      # assistant text assertions (prompt+response docs)
    call_events: tuple[LedgerEvent, ...]      # attempted calls in the target response only
    invariant_note: str = (
        "A JSON argument value is not an assistant text assertion; ACTION_VIEW "
        "arguments never enter claim extraction and TEXT_VIEW never proves an action.")


@dataclass(frozen=True)
class E2ESource:
    case_id: str
    prompt: str                # system policy + user request + history events
    response: str              # target assistant output (text + attempted calls)
    goal_firewall_source: str  # ONLY the user request (PASS-1 goal input)
    policy_normative_text: str
    tool_metadata: tuple[ToolIdentity, ...]
    tool_schemas: tuple[dict, ...]
    tool_catalog_complete: bool
    tool_universe_closed: bool               # source-established CLOSED_TOOL_UNIVERSE
    object_fields_closed: bool               # source-established OBJECT_CLOSED
    events: tuple[LedgerEvent, ...]
    projection: SourceProjection
    history_complete: bool
    completeness_basis: str | None
    source_sha256: str


POLICY_SCOPE_SUFFIX = "\nPOLICY_STATE_CONSTRAINTS="


def build_source(case, *, state_contract: dict | None = None) -> E2ESource:
    """case: E2ECaseInput. Deterministic composition; no LLM, no inference.

    The policy text is wrapped in an explicit SYSTEM transport marker so the
    normalized event carries actor=system (authority from the transport, never
    from body text). Unmarked leading text would normalize as actor=unknown,
    which correctly blocks absence proofs in the prefix.
    """
    state = state_contract if state_contract is not None else (case.state_contract or {})
    policy_text = case.system_policy
    if state:
        policy_text = policy_text + POLICY_SCOPE_SUFFIX + canonical(dict(sorted(state.items()))).decode("utf-8")
    if case.raw_prompt is not None:
        if state:
            raise ValueError("raw competition prompt cannot be rewritten with a state contract")
        prompt = case.raw_prompt
    else:
        prompt_parts = ["⟦SYSTEM⟧\n" + policy_text] if policy_text else []
        if case.user_request:
            prompt_parts.append("⟦USER⟧\n" + case.user_request)
        for event_text in case.history:
            if event_text:
                prompt_parts.append(event_text)
        prompt = "\n".join(prompt_parts)
    response = case.target_response
    metadata = _tool_identities(case.tool_metadata)
    events = normalize(prompt, response, tool_identities=metadata)
    text_events = tuple(event for event in events if event.kind == "text" and event.actor == "assistant"
                        and event.source.document == "response")
    call_events = tuple(event for event in events if event.kind == "call" and event.source.document == "response")
    projection = SourceProjection(text_events, call_events)
    return E2ESource(case.case_id, prompt, response, case.user_request, policy_text, metadata,
                     tuple(case.tool_schemas), bool(case.tool_catalog_complete),
                     bool(case.tool_universe_closed), bool(case.object_fields_closed),
                     events, projection,
                     bool(case.history_complete), case.completeness_basis,
                     # Competition id is logging/joining metadata only.  It
                     # must not alter the content-bound source identity.
                     digest({"prompt": prompt, "response": response}))


def target_calls(source: E2ESource) -> tuple[LedgerEvent, ...]:
    """ACTION_VIEW: attempted calls in the target response (attempt, not effect)."""
    return source.projection.call_events


def tool_catalog(source: E2ESource) -> tuple[str, ...]:
    schemas = {schema["name"] for schema in source.tool_schemas if isinstance(schema.get("name"), str)}
    names = {identity.name for identity in source.tool_metadata}
    names |= {event.tool.name for event in source.events if event.tool}
    return tuple(sorted(schemas | names))


def declared_tool_catalog(source: E2ESource) -> tuple[str, ...]:
    """Only source-declared interfaces; observed invocations add no capabilities."""
    schemas = {schema["name"] for schema in source.tool_schemas if isinstance(schema.get("name"), str)}
    names = {identity.name for identity in source.tool_metadata}
    return tuple(sorted(schemas | names))
