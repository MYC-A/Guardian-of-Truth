"""Step-type router: tool calls go to the formal prover, prose to the prose channel.

The policy prover reasons about API calls (arguments, preconditions, effects).
Free prose has no arguments to bind, so sending it to the prover yields a
guaranteed UNKNOWN. The router makes the modality explicit at the entry point.
"""
from dataclasses import dataclass, field

TOOL_CALL, PROSE, MIXED, EMPTY = 'TOOL_CALL', 'PROSE', 'MIXED', 'EMPTY'


@dataclass(frozen=True)
class Route:
    kind: str
    call_source_ids: tuple = ()
    prose_source_ids: tuple = ()
    malformed_call_source_ids: tuple = ()
    channels: tuple = field(default=())


def route_step(store):
    """Classify the assistant step under evaluation (``store.target_events``)."""
    calls, prose, malformed = [], [], []
    for i, event in enumerate(store.target_events):
        sid = 't' + str(i)
        if event.role != 'assistant': continue
        if event.kind == 'call':
            (calls if event.json_valid and isinstance(event.value, dict) else malformed).append(sid)
        elif event.kind == 'text' and event.text.strip():
            prose.append(sid)
    has_calls = bool(calls or malformed)
    kind = MIXED if has_calls and prose else TOOL_CALL if has_calls else PROSE if prose else EMPTY
    channels = tuple(c for c, on in (('policy_prover', has_calls), ('prose_verifier', bool(prose))) if on)
    return Route(kind, tuple(calls), tuple(prose), tuple(malformed), channels)
