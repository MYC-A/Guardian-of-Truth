"""full_architecture_v1 — Invariant Guardrails comparator backend (§12/§20).

The INVARIANT backend normalizes NeutralCoreInput facts into a chat trace
and answers the TRACE-MATCHING subset of the evidence primitives through
Invariant's local analyzer:

  attempted(action)   -> ToolCall with function name == action
                         (trace-closed-world: presence only; Guardian's
                          absence-under-open-world is NOT expressible)
  completed(action)   -> a ToolOutput message paired to such a call exists
                         (NOTE: this is "result returned", NOT Guardian's
                          trusted-completion semantics — the difference is
                          the measurement)
  everything else     -> NOT_EXPRESSIBLE (abstention, never a guess)

The backend exists to measure WHICH parts of Guardian's custom event search
are redundant given Invariant (directive §12) — it is a comparator and never
authoritative for Guardian semantics.
"""

from __future__ import annotations

import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
for p in (str(_BAKEOFF),):
    if p not in sys.path:
        sys.path.insert(0, str(p))

from neutral_types import (  # noqa: E402
    BackendResult, NeutralAtom, NeutralCoreInput, PrimitiveResult,
)

NOT_EXPRESSIBLE = "NOT_EXPRESSIBLE"


def _facts_to_trace(ci: NeutralCoreInput) -> list[dict]:
    """NeutralFacts -> normalized OpenAI-style chat trace (lossless at the
    fact level: one message pair per attempt fact, ordered by event_index)."""
    events = sorted(ci.facts, key=lambda f: (f.event_index, f.fact_id))
    trace: list[dict] = []
    for fact in events:
        if fact.kind in ("ACTION_ATTEMPTED", "ACTION_COMPLETED",
                         "ACTION_FAILED"):
            # S2: a failed call still SUPPORTS attempted; completed facts
            # imply their call happened — render the call either way
            trace.append({"role": "assistant", "tool_calls": [{
                "id": fact.call_id or fact.fact_id, "type": "function",
                "function": {"name": fact.predicate,
                             "arguments": {"entity": fact.entity}}}]})
            if fact.kind == "ACTION_COMPLETED":
                trace.append({"role": "tool",
                              "tool_call_id": fact.call_id or fact.fact_id,
                              "content": "success"})
            elif fact.kind == "ACTION_FAILED":
                trace.append({"role": "tool",
                              "tool_call_id": fact.call_id or fact.fact_id,
                              "content": "error"})
        elif fact.kind in ("STATE_OBSERVATION", "FIELD_VALUE"):
            trace.append({"role": "tool", "tool_call_id":
                          f"obs-{fact.fact_id}",
                          "content": f"{fact.predicate}={fact.value}"})
        elif fact.kind == "EFFECT":
            # a trusted effect pairs with its own call when the call id is
            # known (so the comparator can see the completion); sourceless
            # effects are rendered as observations
            cid = fact.call_id or f"obs-{fact.fact_id}"
            trace.append({"role": "tool", "tool_call_id": cid,
                          "content": "success" if fact.call_id
                          else f"{fact.predicate}={fact.value}"})
        # CLAIM / ENTITY / RELATION: not trace events
    return trace


def _call_exists(trace: list[dict], action: str) -> bool:
    return any(
        message.get("role") == "assistant"
        and any(call["function"]["name"] == action
                for call in message.get("tool_calls", []))
        for message in trace)


def _result_exists(trace: list[dict], action: str) -> bool:
    call_ids = {call["id"] for message in trace
                if message.get("role") == "assistant"
                for call in message.get("tool_calls", [])
                if call["function"]["name"] == action}
    return any(message.get("role") == "tool"
               and message.get("tool_call_id") in call_ids
               and message.get("content") == "success"
               for message in trace)


def probe(ci: NeutralCoreInput, atoms: list[NeutralAtom]) \
        -> list[PrimitiveResult]:
    """Answer the trace-matching subset; abstain elsewhere."""
    from invariant.analyzer import LocalPolicy
    trace = _facts_to_trace(ci)
    out: list[PrimitiveResult] = []
    for atom in atoms:
        if atom.kind == "attempted":
            policy = LocalPolicy.from_string(f"""
raise "call present" if:
    (call: ToolCall)
    call is tool:{atom.action}
""")
            result = policy.analyze(trace)
            value = "TRUE" if result.errors else "FALSE"
            out.append(PrimitiveResult(atom_key=atom.key(), value=value))
        elif atom.kind == "completed":
            policy = LocalPolicy.from_string(f"""
from invariant import count

raise "completion present" if:
    count(min=1):
        (out: ToolOutput)
        out.content == "success"
        out is tool:{atom.action}
""")
            result = policy.analyze(trace)
            value = "TRUE" if result.errors else "FALSE"
            out.append(PrimitiveResult(atom_key=atom.key(), value=value))
        else:
            out.append(PrimitiveResult(atom_key=atom.key(),
                                       value=NOT_EXPRESSIBLE))
    return out


def evaluate(ci: NeutralCoreInput) -> BackendResult:
    """The Invariant backend does NOT evaluate obligations/worlds (no
    four-valued evidence, no interpretations); it reports its scope."""
    return BackendResult(backend="invariant-comparator", status="UNRESOLVED",
                         input_content_hash=ci.content_hash(),
                         notes="comparator backend: trace matching only "
                               "(attempted/completed presence); policy "
                               "evaluation NOT_EXPRESSIBLE")


BACKEND_NAME = "invariant-comparator"
