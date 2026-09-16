"""Minimal competition adapter (directive §15): prompt + response -> E2ECaseInput.

Deterministic, source-grounded, NO invented metadata:
- system_policy  = the ⟦SYSTEM⟧ block body (instructions + <policy> + [AVAILABLE TOOLS])
- user_request   = all user message texts (leading text of each top-level ⟦USER⟧
                   block, i.e. the user-side intent), joined in original order
- history        = every remaining raw segment (assistant turns incl. nested
                   ⟦ASSISTANT · ход N⟧ blocks and →/← tool call/result lines),
                   VERBATIM byte slices in original order
- tool_metadata  = [{"name": N}] for every [AVAILABLE TOOLS] entry (identity:
                   name only; provider/version unknown -> absent)
- tool_schemas   = {"name", "description", "parameters"} parsed from the
                   [AVAILABLE TOOLS] typed field specs (prompt-derived, §16)
- history_complete = True with completeness_basis = the OFFICIAL task contract
  ("prompt — the full context the agent saw"): absence-of-attempt proofs for
  ACTION atoms are licensed by the contract itself, never invented
- t1_contracts / state_contract / authoritative_* = ABSENT (unknown), never
  guessed — missing information produces abstention, not premises
"""
from __future__ import annotations

import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))
if str(REPO_ROOT / "src") not in sys.path:
    sys.path.insert(0, str(REPO_ROOT / "src"))

from guardian_truth.parsing import MARKER, TOOL, FIELD, parse_events, parse_catalog
from guardian_truth.vnext.e2e.e2e_types_v1 import E2ECaseInput

COMPLETENESS_BASIS = ("official task contract: prompt is the full agent-visible "
                      "context (dsworks.ru/champ/aij26-guardian, rules §3.7)")

TopLevel = re.compile(r'^⟦(SYSTEM|USER|ASSISTANT)⟧', re.MULTILINE)


def _split_top_level(prompt: str):
    """[(tag, start_of_marker, body_start, segment_end)] for top-level blocks."""
    out = []
    matches = list(TopLevel.finditer(prompt))
    for i, match in enumerate(matches):
        end = matches[i + 1].start() if i + 1 < len(matches) else len(prompt)
        # body starts after the marker line
        line_end = prompt.find("\n", match.start(), end)
        body_start = line_end + 1 if line_end != -1 else end
        out.append((match.group(1), match.start(), body_start, end))
    return out


def _nested_markers(segment: str):
    """Marker matches INSIDE a segment body (after the segment's own marker
    line). The segment's own top-level marker must not be counted as nested:
    otherwise the leading user text would be treated as empty and the goal
    firewall source would silently disappear (adapter bug found after the
    first R1 run; fixed before any fix-iteration cycle)."""
    line_end = segment.find("\n")
    body_offset = line_end + 1 if line_end != -1 else len(segment)
    return list(MARKER.finditer(segment, body_offset))


def parse_competition_prompt(prompt: str) -> dict:
    """Deterministic decomposition of a competition prompt."""
    blocks = _split_top_level(prompt)
    if not blocks or blocks[0][0] != "SYSTEM":
        raise ValueError("prompt does not start with a ⟦SYSTEM⟧ block")
    system_policy = prompt[blocks[0][2]:blocks[0][3]].strip("\n")

    user_texts = []
    history_parts = []
    for tag, seg_start, body_start, seg_end in blocks[1:]:
        segment = prompt[seg_start:seg_end]
        nested = _nested_markers(segment)
        if tag == "USER":
            first_nested = nested[0].start() if nested else len(segment)
            user_text = segment[segment.find("\n") + 1:first_nested].strip("\n") \
                if "\n" in segment[:first_nested] else ""
            if user_text.strip():
                user_texts.append(user_text)
            if first_nested < len(segment):
                # Restore the USER-block role context: the nested content of a
                # USER block originally executed with role=user until the first
                # nested ASSISTANT marker (user tool calls keep role=user).
                # The marker line itself emits no text event (empty body).
                history_parts.append("⟦USER⟧\n" + segment[first_nested:].rstrip("\n"))
        else:  # top-level ASSISTANT block (e.g. the opening greeting)
            history_parts.append(segment.rstrip("\n"))
    return {
        "system_policy": system_policy,
        "user_request": "\n\n".join(user_texts),
        "history": tuple(part for part in history_parts if part.strip()),
        "raw_user_texts": user_texts,
    }


def parse_tool_catalog(prompt: str) -> tuple[list[dict], list[dict]]:
    """Prompt-derived [AVAILABLE TOOLS] -> (tool_metadata, tool_schemas).

    tool_metadata: [{"name": N}] — identity by name only.
    tool_schemas:  [{"name", "description", "parameters": {field: spec}}]
    with per-field type/required/enum/description and NESTED children kept
    under their parent parameter ("children": {name: spec}) — all
    source-grounded from the typed field specs.
    """
    events = parse_events(prompt, "prompt")
    catalog = parse_catalog(events, prompt)
    if not catalog.complete:
        raise ValueError("incomplete tool catalog: " + ",".join(catalog.issues))
    block = catalog.source
    raw = prompt[block.start:block.end]
    lines = raw.splitlines()
    tools_meta, tools_schema = [], []
    current = None
    stack = []  # [(indent, spec_dict)] from root to current parent
    for line in lines:
        tool_match = TOOL.match(line)
        if tool_match:
            if current is not None:
                tools_schema.append(current)
            name = tool_match.group("name")
            description = line[tool_match.end():].strip()
            current = {"name": name, "description": description, "parameters": {}}
            tools_meta.append({"name": name})
            stack = [(-1, current)]
            continue
        if current is None:
            continue
        field_match = FIELD.match(line)
        if field_match:
            indent = len(field_match.group("indent").expandtabs(4))
            spec = {
                "type": field_match.group("kind"),
                "required": bool(field_match.group("required")),
                "description": line[field_match.end():].strip(),
            }
            if field_match.group("enum"):
                spec["enum"] = [item.strip() for item in field_match.group("enum").split("|")]
            # pop to the parent whose indent is strictly smaller
            while len(stack) > 1 and stack[-1][0] >= indent:
                stack.pop()
            parent = stack[-1][1]
            container = parent.get("children") if "children" in parent else parent.get("parameters")
            if container is None:
                container = parent.setdefault("children", {})
            container[field_match.group("name")] = spec
            # a container-typed spec may receive nested fields
            if spec["type"] in ("array", "object"):
                stack.append((indent, spec))
                spec.setdefault("children", {})
    if current is not None:
        tools_schema.append(current)
    return tools_meta, tools_schema


def competition_case(firewalled: dict) -> E2ECaseInput:
    """{id, prompt, response} -> E2ECaseInput with prompt-derived fields only."""
    prompt, response = firewalled["prompt"], firewalled["response"]
    parts = parse_competition_prompt(prompt)
    tools_meta, tools_schema = parse_tool_catalog(prompt)
    return E2ECaseInput(
        case_id=firewalled["id"],
        family="",
        system_policy=parts["system_policy"],
        user_request=parts["user_request"],
        history=parts["history"],
        target_response=response,
        tool_metadata=tuple(tools_meta),
        tool_schemas=tuple(tools_schema),
        t1_contracts=(),
        state_contract=None,
        history_complete=True,
        completeness_basis=COMPLETENESS_BASIS,
        authoritative_policy_readings=(),
        authoritative_goal_readings=(),
        authoritative_policy_behaviors=(),
        authoritative_goal_behaviors=(),
        gold_core_status="",
        gold_binary=None,
        notes="",
    )
