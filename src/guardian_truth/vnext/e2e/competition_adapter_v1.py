"""Competition real-input adapter (AI Journey Contest 2026, Guardian of Truth).

Converts the REAL competition transport into ``E2ECaseInput`` objects without
any oracle metadata (no label, no explanation, no hand-authored per-case T1,
no domain knowledge). Two transports are accepted:

1. the transport actually observed in ``valid.parquet``: ``⟦SYSTEM⟧`` block
   containing ``<instructions>``/``<policy>``/``[AVAILABLE TOOLS]`` catalog
   DSL, ``⟦USER⟧`` turns, ``⟦ASSISTANT`` / ``⟦ASSISTANT · ход N⟧`` turn
   headers with inline tab-indented ``→ TOOL_CALL name: {json}`` and
   ``← TOOL_RESPONSE name: {json}`` lines;
2. the officially documented marker transport
   (``⟦ASSISTANT_TOOL_CALL name="X" call_id="c1"⟧`` /
   ``⟦TOOL_RESULT name="X" requestor="assistant" call_id="c1"⟧``) and the
   ``<prompt>``/``<response>`` outer tags, for the hidden test set.

Gold firewall invariant: this module receives only ``(id, prompt, response)``
strings. It never parses labels, explanations or any benchmark metadata, and
``id`` is used exclusively as an output-joining key.

Source grounding: every parsed catalog atom keeps its exact span inside the
original prompt text, so downstream audit records can quote the source
verbatim (EXPLICIT_SCHEMA origin class).
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from pathlib import Path

from ...parsing import decode_json
from ..integrity import digest

# ---------------------------------------------------------------- transports

TURN_HEADER = re.compile(r"^⟦(SYSTEM|USER|ASSISTANT)(?P<rest>[^⟧\r\n]*)⟧", re.M)
ARROW_CALL = re.compile(r"^[ \t]*→[ \t]*TOOL_CALL[ \t]+(?P<tool>[\w.-]+)[ \t]*:", re.M)
ARROW_RESULT = re.compile(r"^[ \t]*←[ \t]*TOOL_RESPONSE[ \t]+(?P<tool>[\w.-]+)[ \t]*:", re.M)
OUTER_TAG = re.compile(r"^\s*<(prompt|response)>(.*)</\1>\s*$", re.S)

# [AVAILABLE TOOLS] catalog DSL (same grammar the legacy parser accepts).
CATALOG_HEADER = "[AVAILABLE TOOLS]"
TOOL_DEF = re.compile(r"^- (?P<name>[\w.-]+)\s+[—–]\s*(?P<description>.*)$", re.M)
CATALOG_FIELD = re.compile(
    r"^(?P<indent>[ \t]+)(?:·\s*)?(?P<name>\w+):\s*"
    r"(?P<kind>string|integer|number|boolean|array|object)(?P<required>!)?"
    r"(?:\s+\[enum:\s*(?P<enum>[^\]]+)\])?(?=\s|$)"
)


@dataclass(frozen=True)
class CatalogField:
    name: str
    kind: str
    required: bool
    enum: tuple[str, ...]
    quote: str
    depth: int
    children: tuple["CatalogField", ...] = ()

    def to_schema_dict(self) -> dict:
        schema: dict = {"type": self.kind}
        if self.enum:
            schema["enum"] = list(self.enum)
        if self.kind in {"array", "object"} and self.children:
            if self.kind == "array":
                schema["items"] = _children_schema(self.children)
            else:
                schema["properties"] = _children_schema(self.children)
                schema["required"] = [c.name for c in self.children if c.required]
        return schema


def _children_schema(children: tuple[CatalogField, ...]) -> dict:
    if len(children) == 1:
        return children[0].to_schema_dict()
    return {"anyOf": [c.to_schema_dict() for c in children]}


@dataclass(frozen=True)
class CatalogTool:
    name: str
    description: str
    fields: tuple[CatalogField, ...]
    start: int
    end: int

    def to_schema_dict(self) -> dict:
        properties = {}
        required = []
        for f in self.fields:
            properties[f.name] = f.to_schema_dict()
            if f.required:
                required.append(f.name)
        schema = {"name": self.name, "description": self.description,
                  "arguments": {"type": "object", "properties": properties}}
        if required:
            schema["arguments"]["required"] = required
        return schema


@dataclass(frozen=True)
class CompetitionTurn:
    actor: str                      # "system" | "user" | "assistant"
    body: str                       # byte-exact body (without turn header)
    start: int                      # span in the original prompt text
    end: int
    turn_label: str                 # original header text, e.g. "ASSISTANT · ход 7"
    tool_calls: tuple[tuple[str, str], ...] = ()     # (tool_name, raw_json)
    tool_responses: tuple[tuple[str, str], ...] = ()  # (tool_name, raw_json)


@dataclass(frozen=True)
class CompetitionCase:
    case_id: str
    system_block: str               # full SYSTEM body (instructions+policy+catalog)
    user_request: str               # all USER turn bodies joined (goal source)
    assistant_turns: tuple[CompetitionTurn, ...]
    target_response_body: str       # response body without its turn header
    target_turn_label: str
    catalog: tuple[CatalogTool, ...]
    prompt_chars: int
    response_chars: int


def _strip_outer_tag(text: str) -> str:
    match = OUTER_TAG.match(text)
    return match.group(2) if match else text


def _split_turns(text: str) -> list[tuple[str, str, int, int, int]]:
    """Return (actor, label, body_start, body_end, header_start) tuples."""
    markers = list(TURN_HEADER.finditer(text))
    if not markers:
        return []
    turns = []
    for i, marker in enumerate(markers):
        actor = marker.group(1).lower()
        label = marker.group(0).strip()
        body_start = marker.end()
        body_end = markers[i + 1].start() if i + 1 < len(markers) else len(text)
        turns.append((actor, label, body_start, body_end, marker.start()))
    return turns


def _parse_catalog(system_text: str, system_start: int) -> tuple[CatalogTool, ...]:
    """Parse the [AVAILABLE TOOLS] DSL with source spans (EXPLICIT_SCHEMA)."""
    header_at = system_text.find(CATALOG_HEADER)
    if header_at < 0:
        return ()
    raw = system_text[header_at:]
    definitions = list(TOOL_DEF.finditer(raw))
    if not definitions:
        return ()
    tools = []
    for i, definition in enumerate(definitions):
        begin, end = definition.start(), (definitions[i + 1].start()
                                          if i + 1 < len(definitions) else len(raw))
        block = raw[begin:end]
        fields: list[CatalogField] = []
        stack: list[tuple[int, CatalogField]] = []
        offset = 0
        for line in block.splitlines(keepends=True):
            match = CATALOG_FIELD.match(line)
            if match:
                depth = len(match.group("indent").expandtabs(4))
                catalog_field = CatalogField(
                    match.group("name"), match.group("kind"), bool(match.group("required")),
                    tuple(match.group("enum").split("|")) if match.group("enum") else (),
                    line.strip(), depth)
                while stack and stack[-1][0] >= depth:
                    stack.pop()
                if stack:
                    parent = stack[-1][1]
                    stack[-1] = (stack[-1][0],
                                 CatalogField(parent.name, parent.kind, parent.required, parent.enum,
                                              parent.quote, parent.depth,
                                              parent.children + (catalog_field,)))
                else:
                    fields.append(catalog_field)
                stack.append((depth, catalog_field))
            offset += len(line)
        tools.append(CatalogTool(definition.group("name"), definition.group("description").strip(),
                                 tuple(fields),
                                 system_start + header_at + begin,
                                 system_start + header_at + end))
    return tuple(tools)


def parse_competition_case(case_id: str, prompt: str, response: str) -> CompetitionCase:
    """Parse one competition row. Only (id, prompt, response) may be read."""
    prompt_text = _strip_outer_tag(prompt)
    response_text = _strip_outer_tag(response)

    turns = _split_turns(prompt_text)
    system_turns = [t for t in turns if t[0] == "system"]
    user_turns = [t for t in turns if t[0] == "user"]
    assistant_turns = [t for t in turns if t[0] == "assistant"]

    # SYSTEM block: from first SYSTEM header to the next non-SYSTEM turn.
    system_body = ""
    if system_turns:
        actor, label, body_start, body_end, _ = system_turns[0]
        for other_actor, _, _, other_end, _ in turns:
            if other_end > body_start and other_actor != "system":
                body_end = min(body_end, other_end)
                break
        system_body = prompt_text[body_start:body_end].strip("\n")

    catalog = _parse_catalog(system_body, prompt_text.find(system_body) if system_body else 0) \
        if system_body else ()

    # Response: strip its own ASSISTANT turn header; keep the body byte-exact.
    response_markers = list(TURN_HEADER.finditer(response_text))
    target_label = response_markers[0].group(0).strip() if response_markers else ""
    target_body = (response_text[response_markers[0].end():] if response_markers
                   else response_text).strip("\n")

    parsed_assistant: list[CompetitionTurn] = []
    for actor, label, body_start, body_end, _ in assistant_turns:
        body = prompt_text[body_start:body_end].strip("\n")
        calls = tuple((m.group("tool"), _json_after(response_text, m, prompt_text, body_start, body_end))
                      for m in ARROW_CALL.finditer(prompt_text[body_start:body_end]))
        results = tuple((m.group("tool"), _json_after(response_text, m, prompt_text, body_start, body_end))
                        for m in ARROW_RESULT.finditer(prompt_text[body_start:body_end]))
        parsed_assistant.append(CompetitionTurn("assistant", body, body_start, body_end, label, calls, results))

    user_request = "\n\n".join(prompt_text[s:e].strip("\n") for _, _, s, e, _ in user_turns)

    return CompetitionCase(case_id=case_id, system_block=system_body, user_request=user_request,
                           assistant_turns=tuple(parsed_assistant), target_response_body=target_body,
                           target_turn_label=target_label, catalog=catalog,
                           prompt_chars=len(prompt), response_chars=len(response))


def _json_after(_response_text, match, full_text, base_start, base_end):
    """Extract the raw JSON body after an arrow marker inside [base_start, base_end)."""
    absolute = base_start + match.end()
    remainder = full_text[absolute:base_end]
    # The JSON body extends to the end of the line (single-line JSON per transport).
    line_end = remainder.find("\n")
    return (remainder if line_end < 0 else remainder[:line_end]).strip()


# ------------------------------------------------------------ E2E conversion

def to_e2e_case(case: CompetitionCase, *, family: str = "competition") -> "E2ECaseInput":
    """Build an E2ECaseInput with NO oracle fields (gold firewall honored).

    - system_policy: the full SYSTEM block byte-exact (instructions + policy +
      [AVAILABLE TOOLS] catalog): everything the platform gave the agent.
    - user_request: all USER turn bodies (the accumulated user intent).
    - history: prior ASSISTANT turns re-marked ``⟦ASSISTANT⟧`` (bodies
      byte-exact, inline arrow tool calls preserved; the legacy marker parser
      understands them natively, authority comes from the transport marker).
    - target_response: ``⟦ASSISTANT⟧`` + response body byte-exact.
    - history_complete: True — the official black-box definition states the
      prompt is the full context the agent saw before its answer.
    """
    from .e2e_types_v1 import E2ECaseInput

    history = tuple(f"⟦ASSISTANT⟧\n{turn.body}" for turn in case.assistant_turns)
    schemas = tuple(tool.to_schema_dict() for tool in case.catalog)
    # tool_metadata entries are dicts (E2E corpus convention; build_source
    # converts them to ToolIdentity itself). provider/version are canonical
    # placeholder bindings derived from the prompt catalog itself (the
    # competition prompt carries no provider/version fields); schema_sha256
    # is the deterministic digest of the parsed catalog schema.
    metadata = tuple({"name": tool.name, "provider": "competition-prompt",
                      "version": "catalog-v1", "schema_sha256": digest(tool.to_schema_dict())}
                     for tool in case.catalog)
    return E2ECaseInput(
        case_id=case.case_id, family=family,
        system_policy=case.system_block,
        user_request=case.user_request,
        history=history,
        target_response=f"⟦ASSISTANT⟧\n{case.target_response_body}",
        tool_metadata=metadata,
        tool_schemas=schemas,
        t1_contracts=(),                 # no oracle contracts (C2/C3)
        state_contract=None,
        history_complete=True,
        completeness_basis="competition black-box: prompt is the full agent-visible context",
        authoritative_policy_readings=(), authoritative_goal_readings=(),
        authoritative_policy_behaviors=(), authoritative_goal_behaviors=(),
        gold_core_status="", gold_binary=None, notes="",
    )


# ------------------------------------------------------- manual T1 (arm C1)

FRESHNESS_MAP = {"result_event": "fresh-read", "fresh": "fresh-read"}


def load_manual_t1_registry(path: Path, *, catalog: tuple[CatalogTool, ...] = ()):
    """Mechanical converter of the legacy hand-authored T1 shorthand
    (contracts/tool_effects_v1.json) into frozen TrustedContract format.

    STRICTLY MECHANICAL rules (no invented semantics; §13 discipline):
    - read-only tools (writes=[], no effects) become fresh-read pure readers
      (freshness shorthand ``result_event`` maps to ``fresh-read``; the
      mapping is recorded, never silent);
    - effect tools: a ``success_predicate`` entry ``path=value`` converts to
      a guarantee EffectSpec ONLY when ``<entity>.<path>`` (or exactly
      ``path``) appears in ``writes`` AND ``entity_key_mapping`` names the
      argument field for that entity. The value is quoted verbatim.
    - everything else (prose guaranteed/possible effects, prose
      preconditions, entity_fields without values) stays UNMAPPED and is
      reported in ``coverage`` — it is never guessed into typed semantics.

    These contracts are diagnostic-ceiling oracle data for arm C1 only; they
    are NEVER available in the competition input. Identity is rebound to the
    prompt-parsed catalog schema digest so the frozen exact-match lookup
    (ContractRegistry.lookup) can fire on competition events."""
    import json
    from ..tools import (ConditionalGuarantee, ContractRegistry, EffectSpec,
                         FieldCondition, TrustedContract)

    data = json.loads(Path(path).read_text(encoding="utf-8"))
    catalog_sha = {tool.name: digest(tool.to_schema_dict()) for tool in catalog}
    contracts, coverage = [], []
    for row in data.get("contracts", ()):
        name = row.get("tool")
        if not name:
            continue
        if catalog_sha.get(name) is None:
            coverage.append({"tool": name, "skipped": "tool_not_in_this_case_catalog"})
            continue
        writes = tuple(row.get("writes", ()))
        mapping = dict(row.get("entity_key_mapping", {}) or {})
        unmapped = {"guaranteed_effects": [], "possible_effects": list(row.get("possible_effects", ())),
                    "preconditions": list(row.get("preconditions", ()))}
        guarantees, plain_effects = [], []
        for predicate in row.get("success_predicate", ()):
            if not isinstance(predicate, str) or "=" not in predicate:
                continue
            path, _, value = predicate.partition("=")
            path, value = path.strip(), value.strip()
            target = next((w for w in writes if w == path or w.endswith("." + path)), None)
            if target is None:
                unmapped["guaranteed_effects"].append(predicate)
                continue
            entity = target.rsplit(".", 1)[0] if "." in target else None
            arg = next((a for a, e in mapping.items() if e == entity), None) if entity else None
            if arg is None:
                unmapped["guaranteed_effects"].append(predicate)
                continue
            plain_effects.append(EffectSpec(arg, target, _canonical_value(value), True))
        if plain_effects:
            guarantees.append(ConditionalGuarantee(conditions=(), effects=tuple(plain_effects)))
        for effect in row.get("guaranteed_effects", ()):
            if not any(effect in predicate or predicate in effect
                       for predicate in row.get("success_predicate", ())):
                unmapped["guaranteed_effects"].append(effect)
        identity_sha = catalog_sha.get(name)
        read_only = writes == () and not plain_effects
        from ..tools import ToolIdentity
        contracts.append(TrustedContract(
            identity=ToolIdentity(name, "competition-prompt", "catalog-v1", identity_sha),
            preconditions=(),
            reads=(),
            writes=writes,
            guarantees=tuple(guarantees),
            possible_effects=(),
            no_effect_conditions=(),
            failure_semantics="documented",
            freshness=FRESHNESS_MAP.get(row.get("freshness"), "unspecified") if read_only else "unspecified",
            idempotence="unspecified",
            provenance=f"manual_oracle_mechanical:{row.get('provenance', '')}"))
        coverage.append({"tool": name, "read_only_pure_reader": read_only,
                         "mapped_guarantee_effects": len(plain_effects),
                         "unmapped": {k: v for k, v in unmapped.items() if v},
                         "freshness_mapping": ("result_event->fresh-read" if read_only
                                                and row.get("freshness") == "result_event" else None)})
    return ContractRegistry(tuple(contracts)), coverage


def _canonical_value(value: str) -> str:
    import json as _json
    try:
        return _json.dumps(_json.loads(value), ensure_ascii=False, sort_keys=True)
    except Exception:
        return _json.dumps(value, ensure_ascii=False)


def parse_response_calls(response: str) -> tuple[tuple[str, str], ...]:
    """Target-response attempted tool calls as (tool_name, raw_json) pairs."""
    text = _strip_outer_tag(response)
    return tuple((m.group("tool"), _json_line(text, m)) for m in ARROW_CALL.finditer(text))


def _json_line(text, match):
    remainder = text[match.end():]
    line_end = remainder.find("\n")
    return (remainder if line_end < 0 else remainder[:line_end]).strip()
