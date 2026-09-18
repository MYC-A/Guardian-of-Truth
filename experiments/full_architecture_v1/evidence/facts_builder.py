"""full_architecture_v1 — real-case evidence facts builder (directive §13).

prompt + response -> classified NeutralFacts (the "raw evidence facts" of
the NeutralCoreInput), WITHOUT any LLM and without domain literals:

  * every tool call in the PROMPT trace  -> ACTION_ATTEMPTED (region
    history); a paired result that parses as JSON or is non-empty ->
    ACTION_COMPLETED; a result whose payload or text marks an error ->
    ACTION_FAILED (error markers are generic transport-level words, not
    domain knowledge)
  * every tool call in the RESPONSE under audit -> ACTION_ATTEMPTED
    (region target; the response document is the artifact under audit)
  * JSON result payloads -> STATE_OBSERVATION rows (predicate = field name,
    value = field value, entity = the call's entity guess) — payload fields
    are whatever the tools actually return
  * assistant non-tool text in the response -> CLAIM facts (never evidence)
  * entity resolution: the first short string argument of the call whose
    name mentions id/ref/number/key, else the first short string argument,
    else "*" — generic identifier heuristics only

Semantic safety fences respected by construction:
  CALL_ATTEMPTED != COMPLETED (pairing required), FAILED != SUCCESS,
  CLAIM != OBSERVED_FACT, payload rows are STATE_OBSERVATION (trusted
  transport rows, not effects: TOOL_SCHEMA != EFFECT_CONTRACT).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_REPO = _FULLARCH.parents[1]
for p in (str(_BAKEOFF), str(_REPO / "src")):
    if p not in sys.path:
        sys.path.insert(0, p)

from guardian_truth.parsing import parse_events  # noqa: E402
from neutral_types import NeutralFact  # noqa: E402

_ERROR_MARKERS = re.compile(
    r"\b(error|failed|failure|denied|invalid|unauthorized|forbidden|"
    r"not found|unable|exception)\b", re.IGNORECASE)
_ID_ARG = re.compile(r"(id|ref|number|num|no|key|code|account|order)$",
                     re.IGNORECASE)
_MAX_ENTITY_LEN = 48


def _entity_guess(arguments: dict) -> str:
    """Generic identifier heuristics ONLY (no domain words)."""
    if not isinstance(arguments, dict):
        return "*"
    id_args = [(k, v) for k, v in arguments.items()
               if _ID_ARG.search(str(k)) and isinstance(v, str)]
    if id_args:
        value = id_args[0][1]
        return value[:_MAX_ENTITY_LEN] if value else "*"
    for value in arguments.values():
        if isinstance(value, str) and value and len(value) <= _MAX_ENTITY_LEN:
            return value[:_MAX_ENTITY_LEN]
    return "*"


def _result_is_error(result) -> bool:
    """Generic transport-level error detection on the paired result."""
    if result is None:
        return False
    if isinstance(result, dict):
        for key in ("error", "errors", "status", "result", "code"):
            if key in result:
                value = result[key]
                if isinstance(value, str) and _ERROR_MARKERS.search(value):
                    return True
                if isinstance(value, dict) or isinstance(value, list):
                    text = str(value)
                    if _ERROR_MARKERS.search(text):
                        return True
        return False
    if isinstance(result, str):
        return bool(_ERROR_MARKERS.search(result))
    return False


def _pair_results(events):
    """FIFO pairing of result events to call events (repo convention)."""
    pending: list = []
    pairs: dict[int, object] = {}
    for event in events:
        if event.kind == "call":
            pending.append(event)
        elif event.kind == "result" and pending:
            call = pending.pop(0)
            pairs[id(call)] = event
    return pairs


def build_facts(case_id: str, prompt: str, response: str) \
        -> tuple[tuple[NeutralFact, ...], dict]:
    """Build NeutralFacts for one competition case (gold-free inputs only)."""
    facts: list[NeutralFact] = []
    stats = {"calls": 0, "completed": 0, "failed": 0, "attempts": 0,
             "state_rows": 0, "claims": 0, "unparsed_calls": 0}
    counter = 0

    def next_id() -> str:
        nonlocal counter
        counter += 1
        return f"{case_id}#f{counter}"

    for document, region in ((prompt, "history"), (response, "target")):
        events = parse_events(document, document)
        pairs = _pair_results(events)
        for event in events:
            if event.kind == "call" and event.name:
                stats["calls"] += 1
                arguments = event.value if isinstance(event.value, dict) \
                    else {}
                if not event.json_valid:
                    stats["unparsed_calls"] += 1
                entity = _entity_guess(arguments)
                facts.append(NeutralFact(
                    next_id(), "ACTION_ATTEMPTED", "assistant", entity,
                    event.name, value=None,
                    event_index=len(facts) + 1,
                    call_id=event.name, region=region))
                stats["attempts"] += 1
                result = pairs.get(id(event))
                if result is not None:
                    if _result_is_error(result.value):
                        facts.append(NeutralFact(
                            next_id(), "ACTION_FAILED", "assistant", entity,
                            event.name, value=None,
                            event_index=len(facts) + 1,
                            call_id=event.name, region=region))
                        stats["failed"] += 1
                    else:
                        facts.append(NeutralFact(
                            next_id(), "ACTION_COMPLETED", "assistant",
                            entity, event.name, value=None,
                            event_index=len(facts) + 1,
                            call_id=event.name, region=region))
                        stats["completed"] += 1
                        # payload rows -> STATE_OBSERVATION (transport
                        # observations, not effects)
                        payload = result.value
                        if isinstance(payload, dict):
                            for key, value in list(payload.items())[:20]:
                                if isinstance(value, (str, int, float, bool)) \
                                        or value is None:
                                    facts.append(NeutralFact(
                                        next_id(), "STATE_OBSERVATION",
                                        "tool", entity, str(key),
                                        value=value,
                                        event_index=len(facts) + 1,
                                        region=region))
                                    stats["state_rows"] += 1
            elif event.kind == "text" and event.role == "assistant" \
                    and region == "target" and event.text.strip():
                facts.append(NeutralFact(
                    next_id(), "CLAIM", "assistant", "*", "response_text",
                    value=event.text[:512], event_index=len(facts) + 1,
                    region=region))
                stats["claims"] += 1

    return tuple(facts), stats
