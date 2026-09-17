"""semantic_pipeline_v1 — Phase 2: deterministic source/timeline representation.

Every source segment preserves: segment_id, source_type, actor, event_index,
turn_index, call_id, paired relation, exact character span in its document,
exact original text, parent segment, tool name.  No summarization, no
timestamps (relative event ordering only).

Built on the repository's own structural parsers (guardian_truth.parsing):
regex is used ONLY for structure, never for semantic relevance.

Fragment = retrieval/extraction unit (sentence- or line-level sub-span of a
segment); every fragment keeps its parent segment and an exact span, so any
later semantic statement is traceable to source + time.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import re
import sys
from pathlib import Path

_REPO_SRC = str(Path(__file__).resolve().parents[2] / "src")
if _REPO_SRC not in sys.path:
    sys.path.insert(0, _REPO_SRC)

from guardian_truth.parsing import decode_json, parse_catalog, parse_events


DOCUMENTS = ("prompt", "response")

# source_type values (superset of the task list; SYSTEM covers instructions)
SOURCE_TYPES = (
    "SYSTEM", "USER", "ASSISTANT", "TOOL_CALL", "TOOL_RESULT",
    "TOOL_DESCRIPTION", "TOOL_SCHEMA",
)

_POLICY_RE = re.compile(r"<policy>\s*(.*?)\s*</policy>", re.IGNORECASE | re.DOTALL)
_CATALOG_MARK = "[AVAILABLE TOOLS]"

_SENT_END = re.compile(r"(?<=[.!?;])\s+(?=[A-Z\u0400-\u04FF0-9\"'(\[])")


@dataclass(frozen=True)
class Segment:
    segment_id: str
    document: str          # "prompt" | "response"
    source_type: str
    actor: str
    event_index: int       # global order across prompt+response
    turn_index: int | None
    call_id: str | None
    paired_segment_id: str | None
    tool: str | None
    span: tuple[int, int]
    text: str
    parent_segment_id: str | None = None


@dataclass(frozen=True)
class Fragment:
    fragment_id: str
    segment_id: str
    document: str
    source_type: str       # inherited from segment
    span: tuple[int, int]  # absolute span inside the segment's document
    text: str
    kind: str              # policy_sentence | text_sentence | result_block | ...
    tool: str | None = None
    kb_candidate: bool = False


@dataclass
class SourceTimeline:
    case_id: str
    prompt: str
    response: str
    segments: tuple[Segment, ...] = ()
    fragments: tuple[Fragment, ...] = ()
    notes: dict = field(default_factory=dict)

    def segment(self, segment_id: str) -> Segment | None:
        return next((s for s in self.segments if s.segment_id == segment_id), None)

    def fragments_of(self, segment_id: str) -> tuple[Fragment, ...]:
        return tuple(f for f in self.fragments if f.segment_id == segment_id)

    def by_type(self, source_type: str) -> tuple[Segment, ...]:
        return tuple(s for s in self.segments if s.source_type == source_type)

    def segment_by_event_index(self, event_index: int) -> Segment | None:
        return next((s for s in self.segments if s.event_index == event_index), None)


# ------------------------------------------------------------------ chunking

def _line_spans(text: str) -> list[tuple[int, int]]:
    spans = []
    offset = 0
    for line in text.splitlines(keepends=True):
        stripped = line.strip()
        if stripped:
            start = offset + (len(line) - len(line.lstrip()))
            end = offset + len(line.rstrip("\n\r"))
            if start < end:
                spans.append((start, end))
        offset += len(line)
    return spans


def _sentence_spans(text: str, max_len: int = 600) -> list[tuple[int, int]]:
    """Deterministic sentence-ish splits with exact offsets; long sentences are
    split on sentence-end boundaries if possible; no text is modified."""
    spans = []
    for start, end in _line_spans(text):
        line = text[start:end]
        if len(line) <= max_len:
            spans.append((start, end))
            continue
        cursor = start
        for match in _SENT_END.finditer(line):
            nxt = start + match.end()
            if nxt - cursor > max_len:
                # give up on fine-grained splitting for this stretch
                continue
            spans.append((cursor, nxt))
            cursor = nxt
        if cursor < end:
            spans.append((cursor, end))
    return spans


def _result_fragment_spans(text: str) -> list[tuple[int, int]]:
    """Tool-result payload: top-level JSON lines (depth 0/1) or text sentences.
    Preserves exact spans; deterministic."""
    spans = _line_spans(text)
    return spans if len(spans) <= 32 else _sentence_spans(text)


# ------------------------------------------------------------------- builder

_ERROR_RESULT_RE = re.compile(
    r"^[ \t]*← TOOL_RESPONSE[ \t]+(?P<tool>[\w.-]+)[ \t]+\[ERROR\][ \t]*:[ \t]*(?P<text>.*)$",
    re.MULTILINE)


def _error_result_splits(text: str) -> list[tuple[int, str, str]]:
    """[(line_start_offset_in_text, tool_name, full_line_text), ...] for every
    `← TOOL_RESPONSE tool [ERROR]: ...` line (with its trailing newline)."""
    splits = []
    for match in _ERROR_RESULT_RE.finditer(text):
        line_end = match.end()
        while line_end < len(text) and text[line_end] in "\r\n":
            line_end += 1
        splits.append((match.start(), match.group("tool"), text[match.start():line_end].strip("\n\r")))
    return splits


def _pair_calls(events):
    """Pair → TOOL_CALL with the next unmatched ← TOOL_RESPONSE of the same
    (role, tool), FIFO — the repository's own `normalize` convention for
    transports without explicit call ids (oldest pending call first)."""
    pending: dict[tuple[str, str], list[int]] = {}
    pairs: dict[int, int] = {}
    ambiguous: list[tuple[int, int]] = []
    for index, event in enumerate(events):
        key = (event.role, event.name or "")
        if event.kind == "call" and event.name:
            pending.setdefault(key, []).append(index)
        elif event.kind == "result" and event.name:
            queue = pending.get(key)
            if queue:
                call_index = queue.pop(0)          # FIFO: oldest pending call
                pairs[call_index] = index
            else:
                ambiguous.append((None, index))
    return pairs, ambiguous


def build_timeline(case_id: str, prompt: str, response: str) -> SourceTimeline:
    prompt_events = parse_events(prompt, "prompt")
    response_events = parse_events(response, "response")
    all_events = [("prompt", e) for e in prompt_events] + [("response", e) for e in response_events]
    flat_events = [e for _, e in all_events]
    pairs, unmatched_results = _pair_calls(flat_events)
    # event index in `pairs` refers to positions in flat_events
    system_event = next((e for e in flat_events if e.role == "system" and e.kind == "text"), None)

    catalog = parse_catalog(prompt_events, prompt)

    segments: list[Segment] = []
    fragments: list[Fragment] = []
    turn_counter = 0
    seg_seq = 0

    def add_segment(**kwargs) -> Segment:
        nonlocal seg_seq
        segment = Segment(segment_id=f"seg:{seg_seq:03d}", **kwargs)
        seg_seq += 1
        segments.append(segment)
        return segment

    # ---- SYSTEM block: one segment; catalog tools get child segments
    policy_region: tuple[int, int] | None = None          # TRUE <policy> block
    frontend_policy_region: tuple[int, int] | None = None  # what the incumbent
    # policy frontend ACTUALLY receives: the extraction regex starts at the
    # FIRST '<policy>' occurrence, which lives inside the instructions sentence
    # ("according to the <policy> provided below."), so the payload includes
    # the instructions tail and any nested policy documents up to the first
    # '</policy>'.
    if system_event is not None:
        doc, event = "prompt", system_event
        system_seg = add_segment(
            document="prompt", source_type="SYSTEM", actor="system",
            event_index=0, turn_index=0, call_id=None, paired_segment_id=None,
            tool=None, span=(event.source.start, event.source.end), text=event.text)
        text_value = event.text
        first_close = text_value.find("</policy>")
        first_open = text_value.find("<policy>")
        if first_open >= 0 and first_close > first_open:
            last_open = text_value.rfind("<policy>", 0, first_close)
            true_start = event.source.start + last_open + len("<policy>")
            # strip leading whitespace, mirroring the repo regex semantics
            while prompt[true_start].isspace():
                true_start += 1
            true_end = event.source.start + first_close
            policy_region = (true_start, true_end)
            front_start = event.source.start + first_open + len("<policy>")
            while prompt[front_start].isspace():
                front_start += 1
            frontend_policy_region = (front_start, true_end)
        # fragments: instructions region, TRUE policy region, remainder
        regions = []
        if policy_region:
            regions.append(("instructions", (event.source.start, policy_region[0])))
            regions.append(("policy", policy_region))
            cat_start = prompt.find(_CATALOG_MARK, event.source.start, event.source.end)
            if cat_start >= 0:
                regions.append(("catalog_header", (policy_region[1], cat_start)))
                regions.append(("catalog_region", (cat_start, event.source.end)))
            else:
                regions.append(("system_tail", (policy_region[1], event.source.end)))
        else:
            regions.append(("instructions", (event.source.start, event.source.end)))
        for region_name, (r_start, r_end) in regions:
            region_text = prompt[r_start:r_end]
            for f_start, f_end in _sentence_spans(region_text):
                fragments.append(Fragment(
                    fragment_id=f"frag:{len(fragments):04d}", segment_id=system_seg.segment_id,
                    document="prompt", source_type="SYSTEM", span=(r_start + f_start, r_start + f_end),
                    text=region_text[f_start:f_end], kind=f"{region_name}_sentence"))

    # ---- tool declarations (catalog): TOOL_DESCRIPTION + TOOL_SCHEMA segments
    if catalog.source is not None:
        for name, spec in sorted(catalog.tools.items()):
            raw = prompt[spec.source.start:spec.source.end]
            first_line_span = _line_spans(raw)[0] if _line_spans(raw) else None
            desc_end = spec.source.start + (first_line_span[1] if first_line_span else 0)
            desc_text = prompt[spec.source.start:desc_end] if first_line_span else ""
            desc_seg = None
            if desc_text:
                desc_seg = add_segment(
                    document="prompt", source_type="TOOL_DESCRIPTION", actor="system",
                    event_index=0, turn_index=0, call_id=None, paired_segment_id=None, tool=name,
                    span=(spec.source.start, desc_end), text=desc_text,
                    parent_segment_id=segments[0].segment_id if segments else None)
                fragments.append(Fragment(
                    fragment_id=f"frag:{len(fragments):04d}", segment_id=desc_seg.segment_id,
                    document="prompt", source_type="TOOL_DESCRIPTION",
                    span=(spec.source.start, desc_end), text=desc_text,
                    kind="tool_description", tool=name))
            schema_start = desc_end
            schema_end = spec.source.end
            schema_text = prompt[schema_start:schema_end]
            if schema_text.strip():
                schema_seg = add_segment(
                    document="prompt", source_type="TOOL_SCHEMA", actor="system",
                    event_index=0, turn_index=0, call_id=None, paired_segment_id=None, tool=name,
                    span=(schema_start, schema_end), text=schema_text,
                    parent_segment_id=segments[0].segment_id if segments else None)
                for f_start, f_end in _line_spans(schema_text):
                    fragments.append(Fragment(
                        fragment_id=f"frag:{len(fragments):04d}", segment_id=schema_seg.segment_id,
                        document="prompt", source_type="TOOL_SCHEMA",
                        span=(schema_start + f_start, schema_start + f_end),
                        text=schema_text[f_start:f_end], kind="tool_field", tool=name))

    # ---- trajectory events (prompt history + response target)
    last_call_id_by_tool: dict[str, str] = {}
    for event_index, (doc, event) in enumerate(all_events, start=1):
        if event is system_event:
            continue  # already emitted as the SYSTEM segment
        text = event.text
        start, end = event.source.start, event.source.end
        # ERROR responses (`← TOOL_RESPONSE name [ERROR]: ...`) do not match
        # the transport grammar's colon requirement, so the repository parser
        # swallows them into the preceding call/text event.  Phase 2 must NOT
        # throw away source text: split them out as first-class TOOL_RESULT
        # segments (kind error_result).
        error_splits = _error_result_splits(text)
        if error_splits and event.kind in {"call", "text"}:
            first_rel = error_splits[0][0]
            main_text = text[:first_rel]
            main_end = start + first_rel
        else:
            error_splits = []
            main_text, main_end = text, end
        if event.kind == "text":
            if event.role == "user":
                source_type, actor = "USER", "user"
                turn_counter += 1
            elif event.role == "assistant":
                source_type, actor = "ASSISTANT", "assistant"
                turn_counter += 1
            else:
                source_type, actor = "SYSTEM", "system"
            seg = add_segment(document=doc, source_type=source_type, actor=actor,
                              event_index=event_index, turn_index=turn_counter,
                              call_id=None, paired_segment_id=None, tool=None,
                              span=(start, main_end), text=main_text)
            for f_start, f_end in _sentence_spans(main_text):
                fragments.append(Fragment(
                    fragment_id=f"frag:{len(fragments):04d}", segment_id=seg.segment_id,
                    document=doc, source_type=source_type, span=(start + f_start, start + f_end),
                    text=main_text[f_start:f_end], kind="text_sentence"))
        elif event.kind == "call":
            seg = add_segment(document=doc, source_type="TOOL_CALL", actor=event.role,
                              event_index=event_index, turn_index=turn_counter,
                              call_id=f"call:{event_index}", paired_segment_id=None, tool=event.name,
                              span=(start, main_end), text=main_text)
            if event.name:
                last_call_id_by_tool[event.name] = f"call:{event_index}"
            fragments.append(Fragment(
                fragment_id=f"frag:{len(fragments):04d}", segment_id=seg.segment_id,
                document=doc, source_type="TOOL_CALL", span=(start, main_end), text=main_text,
                kind="call_payload", tool=event.name))
        elif event.kind == "result":
            flat_index = event_index - 1
            paired_call_flat = pairs.get(flat_index)
            call_id = f"call:{paired_call_flat + 1}" if paired_call_flat is not None else None
            seg = add_segment(document=doc, source_type="TOOL_RESULT", actor=event.role,
                              event_index=event_index, turn_index=turn_counter,
                              call_id=call_id, paired_segment_id=None, tool=event.name,
                              span=(start, end), text=text)
            fragments.append(Fragment(
                fragment_id=f"frag:{len(fragments):04d}", segment_id=seg.segment_id,
                document=doc, source_type="TOOL_RESULT", span=(start, end), text=text,
                kind="result_payload", tool=event.name))
            # sub-fragments for retrieval (KB-like or long results)
            payload_lines = _result_fragment_spans(text)
            kb_like = _kb_candidate(event.name or "", text)
            if len(payload_lines) > 1 or kb_like:
                for f_start, f_end in payload_lines[:64]:
                    line_text = text[f_start:f_end]
                    if not line_text.strip() or line_text.strip() in {"{", "}", "[", "]"}:
                        continue
                    fragments.append(Fragment(
                        fragment_id=f"frag:{len(fragments):04d}", segment_id=seg.segment_id,
                        document=doc, source_type="TOOL_RESULT", span=(start + f_start, start + f_end),
                        text=line_text, kind="result_block", tool=event.name,
                        kb_candidate=kb_like or _kb_candidate(event.name or "", line_text)))

        # ---- split-out ERROR tool responses as first-class TOOL_RESULT segments
        for rel_start, tool_name, error_text in error_splits:
            paired_call = last_call_id_by_tool.get(tool_name)
            err_seg = add_segment(
                document=doc, source_type="TOOL_RESULT", actor=event.role,
                event_index=event_index, turn_index=turn_counter,
                call_id=paired_call, paired_segment_id=None, tool=tool_name,
                span=(start + rel_start, start + rel_start + len(error_text)), text=error_text)
            fragments.append(Fragment(
                fragment_id=f"frag:{len(fragments):04d}", segment_id=err_seg.segment_id,
                document=doc, source_type="TOOL_RESULT",
                span=err_seg.span, text=error_text, kind="error_result", tool=tool_name))

    # ---- call/result pairing as notes + backfilled call_id on call segments
    seg_by_event_index = {s.event_index: s for s in segments if s.event_index > 0}
    notes = {
        "call_result_pairs": [
            {"call_event_index": call_index + 1, "result_event_index": result_index + 1,
             "tool": (seg_by_event_index.get(call_index + 1).tool
                      if seg_by_event_index.get(call_index + 1) else None)}
            for call_index, result_index in sorted(pairs.items())],
        "unmatched_result_events": [index + 1 for _, index in unmatched_results],
        "policy_region": list(policy_region) if policy_region else None,
        "frontend_policy_region": list(frontend_policy_region) if frontend_policy_region else None,
        "catalog_tools": sorted(catalog.tools) if catalog.source is not None else [],
        "catalog_complete": bool(catalog.complete),
    }
    return SourceTimeline(case_id=case_id, prompt=prompt, response=response,
                          segments=tuple(segments), fragments=tuple(fragments), notes=notes)


_KB_NAME_MARKERS = ("search", "knowledge", "kb", "document", "doc_", "lookup", "reference", "policy", "faq", "guideline")


def _kb_candidate(tool_name: str, text: str) -> bool:
    """Generic, benchmark-independent heuristic marking of document-like tool
    results (retrieval candidates only — never a policy promotion)."""
    lowered = tool_name.lower()
    name_hit = any(marker in lowered for marker in _KB_NAME_MARKERS)
    document_like = len(text) > 400 and ("\\n" in text or text.count("\\n") > 3 or text.lstrip().startswith(("{", "[")))
    return name_hit and document_like


def load_development_rows(parquet_path: str) -> list[dict]:
    """Development view (VIEWED DATA): id, prompt, response, label, explanation."""
    import pandas as pd
    frame = pd.read_parquet(parquet_path)
    return frame.to_dict(orient="records")


def timeline_summary(timeline: SourceTimeline) -> dict:
    counts: dict[str, int] = {}
    for segment in timeline.segments:
        counts[segment.source_type] = counts.get(segment.source_type, 0) + 1
    return {
        "case_id": timeline.case_id,
        "segments": len(timeline.segments),
        "fragments": len(timeline.fragments),
        "segment_types": counts,
        "catalog_tools": len(timeline.notes.get("catalog_tools", [])),
    }


if __name__ == "__main__":  # pragma: no cover - manual smoke
    import sys
    sys.path.insert(0, "/home/z/my-project/Guardian-of-Truth/src")
    rows = load_development_rows("/home/z/my-project/Guardian-of-Truth/valid.parquet")
    row = next(r for r in rows if r["id"] == "airline__21::t7")
    timeline = build_timeline(row["id"], row["prompt"], row["response"])
    print(json.dumps(timeline_summary(timeline), indent=1))
    sample = timeline.fragments[3]
    print("sample fragment:", sample.fragment_id, sample.source_type, sample.span, repr(sample.text[:90]))
