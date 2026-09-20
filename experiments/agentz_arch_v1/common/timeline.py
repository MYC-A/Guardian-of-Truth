"""Deterministic, lossless-ish timeline parser for the contest transport format.

Markers seen in public46:
  <system>... <user>... <assistant - turn N>...
  -> TOOL_CALL name: {json}
  <- TOOL_RESPONSE {json}
Responsibilities (TRUSTED structure only):
  - split prompt into ordered events with exact char spans in the original prompt
  - classify role (system/user/assistant) and kind (message/tool_call/tool_response)
  - parse tool call JSON payloads (technical validation only, no semantic guessing)
No semantic interpretation happens here.
"""
import json, re
from dataclasses import dataclass, field

RE_SEGMENT = re.compile(r"^\u27e6(SYSTEM|USER|ASSISTANT)(?:\s*·\s*(?:\u0445\u043e\u0434|turn)\s*(\d+))?\u27e7[ \t]*\n?",
                        re.M)
RE_TCALL = re.compile(r"→\s*TOOL_CALL\s*([A-Za-z_][\w.]*)\s*:\s*", re.M)
RE_TRESP = re.compile(r"←\s*TOOL_RESPONSE\s*\.?\s*", re.M)


@dataclass
class Event:
    idx: int
    kind: str          # system | user | assistant | tool_call | tool_response
    role: str          # system | user | assistant | tool
    turn: int | None
    span: tuple        # (start, end) char offsets in prompt (content only)
    header_span: tuple
    text: str
    tool_name: str | None = None
    payload: dict | None = None
    payload_raw: str | None = None
    payload_span: tuple | None = None


def _match_json_at(text, i):
    """Starting at text[i] == '{', find the end of the JSON object (brace depth,
    string aware). Returns (obj_or_None, end_index_exclusive, raw)."""
    depth, j, in_str, esc = 0, i, False, False
    start = i
    while j < len(text):
        c = text[j]
        if in_str:
            if esc: esc = False
            elif c == "\\": esc = True
            elif c == '"': in_str = False
        else:
            if c == '"': in_str = True
            elif c == "{": depth += 1
            elif c == "}":
                depth -= 1
                if depth == 0:
                    raw = text[start:j + 1]
                    try:
                        return json.loads(raw), j + 1, raw
                    except Exception:
                        return None, j + 1, raw
        j += 1
    return None, len(text), text[start:]


def parse_prompt(prompt: str):
    """Return list[Event] in order (empty message events dropped)."""
    events = _parse_prompt_raw(prompt)
    return [e for e in events
            if e.kind in ("tool_call", "tool_response") or e.text.strip()]


def _parse_prompt_raw(prompt: str):
    segs = []
    for m in RE_SEGMENT.finditer(prompt):
        segs.append((m.start(), m.end(), m.group(1), m.group(2)))
    if not segs:
        # fallback: single anonymous block = whole prompt is system+history
        return [Event(0, "system", "system", None, (0, len(prompt)), (0, 0), prompt)]
    # leading text before first marker
    events = []
    if segs[0][0] > 0:
        events.append(Event(0, "system", "system", None, (0, segs[0][0]), (0, 0),
                            prompt[:segs[0][0]]))
    idx = len(events)
    for si, (hs, he, role, turn) in enumerate(segs):
        body_start = he
        body_end = segs[si + 1][0] if si + 1 < len(segs) else len(prompt)
        body = prompt[body_start:body_end]
        # inside an assistant segment, tool calls / responses split the body
        marks = []
        for m in RE_TCALL.finditer(body):
            marks.append(("tool_call", m))
        for m in RE_TRESP.finditer(body):
            marks.append(("tool_response", m))
        marks.sort(key=lambda x: x[1].start())
        if not marks:
            kind = role.lower()
            events.append(Event(idx, kind, role, int(turn) if turn else None,
                                (body_start, body_end), (hs, he), body.strip()))
            idx += 1
            continue
        # text before first mark belongs to the assistant message
        pos = 0
        for kind, m in marks:
            if m.start() > pos:
                events.append(Event(idx, "assistant", "assistant",
                                    int(turn) if turn else None,
                                    (body_start + pos, body_start + m.start()),
                                    (hs, he), body[pos:m.start()].strip()))
                idx += 1
            if kind == "tool_call":
                name = m.group(1)
                # find json start
                rest = body[m.end():]
                rel = rest.find("{")
                if rel >= 0:
                    jstart_abs = body_start + m.end() + rel
                    obj, jend, raw = _match_json_at(prompt, jstart_abs)
                else:
                    jstart_abs = jend = body_start + body_end
                    obj, raw = None, ""
                events.append(Event(idx, "tool_call", "assistant",
                                    int(turn) if turn else None,
                                    (body_start + m.start(), jend if rel >= 0 else body_end),
                                    (hs, he), prompt[body_start + m.start():jend].strip(),
                                    tool_name=name, payload=obj if isinstance(obj, dict) else None,
                                    payload_raw=raw if rel >= 0 else None,
                                    payload_span=(jstart_abs, jend) if rel >= 0 else None))
                idx += 1
                pos = (m.end() + rel + (len(raw) if rel >= 0 else 0))
                # advance scan position past the JSON in body coordinates
                pos_body = (m.end() - 0) + rel + (len(raw) if rel >= 0 else 0)
                pos = pos_body
            else:
                rest = body[m.end():]
                rel = rest.find("{")
                # scalar / text responses: take lines until next → / ← / segment marker
                nxt = re.search(r"(\n→|\n←|\n\u27e6|\Z)", rest)
                stop = nxt.start() if nxt else len(rest)
                if rel < 0 or (nxt and nxt.start() >= 0 and rest.find("{") > nxt.start()):
                    scalar = rest[:stop].strip()
                    ev_end = body_start + m.end() + (nxt.start() if nxt else stop)
                    events.append(Event(idx, "tool_response", "tool",
                                        int(turn) if turn else None,
                                        (body_start + m.start(), ev_end),
                                        (hs, he), prompt[body_start + m.start():ev_end].strip(),
                                        payload=None,
                                        payload_raw=scalar or None,
                                        payload_span=(body_start + m.end(),
                                                      body_start + m.end() + len(scalar))))
                    idx += 1
                    pos = m.end() + (nxt.start() if nxt else stop)
                    continue
                if rel >= 0:
                    jstart_abs = body_start + m.end() + rel
                    obj, jend, raw = _match_json_at(prompt, jstart_abs)
                else:
                    jstart_abs = jend = body_end
                    obj, raw = None, ""
                events.append(Event(idx, "tool_response", "tool",
                                    int(turn) if turn else None,
                                    (body_start + m.start(), jend if rel >= 0 else body_end),
                                    (hs, he), prompt[body_start + m.start():jend].strip(),
                                    payload=obj if isinstance(obj, (dict, list)) else None,
                                    payload_raw=raw if rel >= 0 else None,
                                    payload_span=(jstart_abs, jend) if rel >= 0 else None))
                idx += 1
                pos_body = (m.end() - 0) + rel + (len(raw) if rel >= 0 else 0)
                pos = pos_body
        # trailing text after last mark
        if pos < len(body):
            events.append(Event(idx, "assistant", "assistant",
                                int(turn) if turn else None,
                                (body_start + pos, body_end), (hs, he), body[pos:].strip()))
            idx += 1
    return events


def find_event(prompt, span):
    return prompt[span[0]:span[1]]


def tool_calls(events):
    return [e for e in events if e.kind == "tool_call"]


def tool_responses(events):
    return [e for e in events if e.kind == "tool_response"]


def pair_calls_responses(events):
    """Naive FIFO pairing of consecutive tool_call -> tool_response (same as
    contest transport: one response right after each call)."""
    pairs = []
    pending = None
    for e in events:
        if e.kind == "tool_call":
            pending = e
        elif e.kind == "tool_response" and pending is not None:
            pairs.append((pending, e))
            pending = None
    return pairs
