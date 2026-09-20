"""Lossless trace parser for the competition ⟦⟧ format.

Parses prompt+response into:
- segments: SYSTEM / USER / ASSISTANT_N / RESPONSE with exact char spans
  (absolute offsets into the full original text, so any span can be
  verified byte-exactly against the original).
- tool_events: ordered list of TOOL_CALL / TOOL_RESPONSE with parsed JSON
  args/results, source segment index, and char offsets.
- fact_ledger: helper views (latest value per (tool, entity-ish key)).

Design rules (from project history):
- never invent effects; SUCCESS status unknown unless stated in result.
- exact original bytes preserved; spans are [start, end) into the full text.
- ERROR tool responses are first-class events.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from typing import Optional

SEG_RE = re.compile(r"⟦(SYSTEM|USER|ASSISTANT(?: · ход (\d+))?)⟧")
TOOL_CALL_RE = re.compile(r"→ TOOL_CALL ([A-Za-z0-9_]+): (.*)")
TOOL_RESP_RE = re.compile(r"← TOOL_RESPONSE ([A-Za-z0-9_]+): (.*)")
ERROR_RE = re.compile(r"\[ERROR\]")


@dataclass
class Segment:
    kind: str  # SYSTEM | USER | ASSISTANT | RESPONSE
    turn: Optional[int]  # assistant turn number; None for SYSTEM/USER
    start: int  # absolute char offset of content start (after marker line)
    end: int  # absolute char offset of content end
    marker_start: int  # offset of ⟦ marker itself
    text: str  # exact original content
    idx: int  # segment index in order

    @property
    def is_response(self) -> bool:
        return self.kind == "RESPONSE"

    def span_of(self, fragment: str) -> Optional[tuple[int, int]]:
        """Absolute span of first occurrence of fragment inside this segment."""
        rel = self.text.find(fragment)
        if rel < 0:
            return None
        return (self.start + rel, self.start + rel + len(fragment))


@dataclass
class ToolEvent:
    kind: str  # CALL | RESPONSE
    tool: str
    raw_payload: str
    payload: Optional[dict | list]  # parsed JSON if possible
    seg_idx: int  # index into segments
    abs_start: int
    abs_end: int
    is_error: bool = False
    seq: int = 0  # global order among all tool events

    @property
    def call_id_key(self) -> str:
        return f"{self.tool}#{self.seq}"


@dataclass
class Trace:
    full_text: str
    prompt_text: str
    response_text: str
    segments: list[Segment] = field(default_factory=list)
    tool_events: list[ToolEvent] = field(default_factory=list)

    # ---------- views ----------

    @property
    def system_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "SYSTEM"]

    @property
    def policy_text(self) -> str:
        """Policy block inside SYSTEM (between <policy> tags if present).

        Takes the LAST '<policy>' before the LAST '</policy>': instructions
        often contain a literal '<policy>' reference ('according to the
        <policy> provided below') which must not start the block.
        """
        sys_txt = "\n".join(s.text for s in self.system_segments)
        j = sys_txt.rfind("</policy>")
        i = sys_txt.rfind("<policy>", 0, j)
        if 0 <= i < j:
            return sys_txt[i + len("<policy>") : j].strip()
        return sys_txt

    @property
    def user_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "USER"]

    @property
    def assistant_segments(self) -> list[Segment]:
        return [s for s in self.segments if s.kind == "ASSISTANT"]

    @property
    def response_segment(self) -> Optional[Segment]:
        for s in self.segments:
            if s.kind == "RESPONSE":
                return s
        return None

    def absolute_span(self, seg_idx: int, rel_start: int, rel_end: int) -> tuple[int, int]:
        seg = self.segments[seg_idx]
        return (seg.start + rel_start, seg.start + rel_end)

    def verify_span(self, abs_start: int, abs_end: int, expected: str) -> bool:
        """Byte-exact check that the span in the original text equals expected."""
        if abs_start < 0 or abs_end > len(self.full_text) or abs_start >= abs_end:
            return False
        return self.full_text[abs_start:abs_end] == expected

    def find_fragment(self, fragment: str) -> Optional[tuple[int, int]]:
        """First absolute span of fragment in the full text (prompt+response)."""
        i = self.full_text.find(fragment)
        if i < 0:
            return None
        return (i, i + len(fragment))

    # ---------- fact ledger helpers ----------

    def tool_responses(self, tool: Optional[str] = None) -> list[ToolEvent]:
        out = []
        for e in self.tool_events:
            if e.kind == "RESPONSE" and (tool is None or e.tool == tool):
                out.append(e)
        return out

    def tool_calls(self, tool: Optional[str] = None) -> list[ToolEvent]:
        out = []
        for e in self.tool_events:
            if e.kind == "CALL" and (tool is None or e.tool == tool):
                out.append(e)
        return out

    def summary_card(self) -> dict:
        return {
            "n_segments": len(self.segments),
            "n_user": len(self.user_segments),
            "n_assistant": len(self.assistant_segments),
            "n_tool_calls": len(self.tool_calls()),
            "n_tool_responses": len(self.tool_responses()),
            "n_error_responses": sum(1 for e in self.tool_events if e.kind == "RESPONSE" and e.is_error),
            "tools_used": sorted({e.tool for e in self.tool_events if e.kind == "CALL"}),
            "prompt_chars": len(self.prompt_text),
            "response_chars": len(self.response_text),
        }


def parse_trace(prompt: str, response: str) -> Trace:
    """Parse prompt+response into a Trace with byte-exact spans.

    The response text continues the prompt; spans are absolute within
    prompt + "\\n" + response (the joined full_text) to keep one coordinate
    system. The response is marked as segment kind RESPONSE.
    """
    full_text = prompt + "\n" + response
    # segment boundaries over full_text; response begins at len(prompt)+1
    response_start = len(prompt) + 1

    segments: list[Segment] = []
    marks: list[tuple[str, Optional[int], int]] = []  # (kind, turn, marker_start)
    for m in SEG_RE.finditer(full_text):
        kind = "SYSTEM" if m.group(1) == "SYSTEM" else ("USER" if m.group(1) == "USER" else "ASSISTANT")
        turn = int(m.group(2)) if (m.group(2) and m.group(2).isdigit()) else None
        # assistant markers inside the response region -> RESPONSE kind
        if m.start() >= response_start and kind == "ASSISTANT":
            kind = "RESPONSE"
        marks.append((kind, turn, m.start()))

    for i, (kind, turn, marker_start) in enumerate(marks):
        content_start = marker_start + len(full_text[marker_start : full_text.find("\n", marker_start)]) + 1
        content_end = marks[i + 1][2] if i + 1 < len(marks) else len(full_text)
        # trim trailing whitespace-only tail but keep exact bytes for span math
        text = full_text[content_start:content_end]
        segments.append(
            Segment(
                kind=kind,
                turn=turn,
                start=content_start,
                end=content_end,
                marker_start=marker_start,
                text=text,
                idx=i,
            )
        )

    trace = Trace(
        full_text=full_text,
        prompt_text=prompt,
        response_text=response,
        segments=segments,
    )

    # tool events inside every segment (both prompt history and response)
    seq = 0
    for seg in segments:
        for line_i, line in enumerate(seg.text.split("\n")):
            abs_line_start = seg.start + sum(len(l) + 1 for l in seg.text.split("\n")[:line_i])
            mc = TOOL_CALL_RE.match(line.strip())
            mr = TOOL_RESP_RE.match(line.strip())
            if mc:
                tool, payload = mc.group(1), mc.group(2)
                parsed = _try_json(payload)
                trace.tool_events.append(
                    ToolEvent(
                        kind="CALL",
                        tool=tool,
                        raw_payload=payload,
                        payload=parsed,
                        seg_idx=seg.idx,
                        abs_start=abs_line_start,
                        abs_end=abs_line_start + len(line),
                        seq=seq,
                    )
                )
                seq += 1
            elif mr:
                tool, payload = mr.group(1), mr.group(2)
                parsed = _try_json(payload)
                trace.tool_events.append(
                    ToolEvent(
                        kind="RESPONSE",
                        tool=tool,
                        raw_payload=payload,
                        payload=parsed,
                        seg_idx=seg.idx,
                        abs_start=abs_line_start,
                        abs_end=abs_line_start + len(line),
                        is_error=bool(ERROR_RE.search(payload)),
                        seq=seq,
                    )
                )
                seq += 1
    return trace


def _try_json(s: str) -> Optional[dict | list]:
    s = s.strip()
    # strip possible trailing [ERROR] marker for parse purposes
    s2 = ERROR_RE.sub("", s).strip()
    for cand in (s2, s2.rstrip("[]ERROR").strip()):
        try:
            v = json.loads(cand)
            if isinstance(v, (dict, list)):
                return v
        except json.JSONDecodeError:
            continue
    return None


# ---------------- clause segmentation for policies ----------------

_CLAUSE_SPLIT_RE = re.compile(r"(?<=[.!?;])\s+(?=[A-ZА-ЯЁ0-9#*\-\[])|\n{2,}")


def split_policy_clauses(policy_text: str, min_len: int = 25) -> list[dict]:
    """Split policy into clause units with char spans.

    Uses paragraph + sentence boundaries. Each clause keeps its absolute
    span within the policy_text. Non-normative lines (headers, xml tags,
    tool lists, timestamps) get clause_kind='non_policy' so the coverage
    registry can account for them as non_policy_with_reason instead of
    diluting coverage.
    """
    import re as _re

    NON_POLICY_PAT = _re.compile(
        r"^(\s*#{1,6}\s|</?[a-z_]+>\s*$|\s*[-*]\s*$|AVAILABLE TOOLS|\s*-\s+[a-z_]+\s*$|"
        r"The current time is|^\s*\d+\.\s*$)"
    )
    clauses = []
    pos = 0
    for para in policy_text.split("\n"):
        para_start = pos
        pos += len(para) + 1
        if not para.strip():
            continue
        non_policy = bool(NON_POLICY_PAT.match(para)) or len(para.strip()) < 12
        if len(para) < 400:
            clauses.append(
                {
                    "text": para,
                    "start": para_start,
                    "end": para_start + len(para),
                    "clause_kind": "non_policy" if non_policy else "normative",
                }
            )
        else:
            # sentence split with absolute spans
            rel = 0
            parts = _CLAUSE_SPLIT_RE.split(para)
            for part in parts:
                if not part.strip():
                    continue
                found = para.find(part, rel)
                if found < 0:
                    continue
                if len(part.strip()) >= min_len:
                    clauses.append(
                        {
                            "text": part,
                            "start": para_start + found,
                            "end": para_start + found + len(part),
                            "clause_kind": "non_policy" if NON_POLICY_PAT.match(part) else "normative",
                        }
                    )
                rel = found + len(part)
    return clauses
