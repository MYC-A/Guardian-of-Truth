"""Lossless source/timeline construction. No semantic relevance decisions live here."""

from __future__ import annotations

import hashlib
import re

from guardian_truth.parsing import parse_catalog, parse_events

from .types import SourceSegment, SourceTimeline


_CALL_ID = re.compile(r'\bcall_id="([^"]+)"')


def _sha(text: str) -> str:
    return hashlib.sha256(text.encode("utf-8")).hexdigest()


def build_source_timeline(prompt: str, response: str) -> SourceTimeline:
    """Preserve roots byte-for-byte and add deterministic structural child segments."""
    if not isinstance(prompt, str) or not isinstance(response, str):
        raise TypeError("prompt and response must be strings")
    segments = [
        SourceSegment("prompt:root", "RAW_PROMPT", "unknown", 0, 0, 0, len(prompt), prompt),
        SourceSegment("response:root", "TARGET_RESPONSE", "assistant", 1, 0, 0,
                      len(response), response, document="response"),
    ]
    event_index, turn_index = 2, 0
    prompt_events = parse_events(prompt, "prompt")
    for number, event in enumerate(prompt_events):
        turn_index += int(event.kind == "text")
        raw = prompt[event.source.start:event.source.end]
        match = _CALL_ID.search(raw)
        call_id = match.group(1) if match else None
        source_type = {"call": "TOOL_CALL", "result": "TOOL_RESULT"}.get(
            event.kind, event.role.upper())
        segments.append(SourceSegment(
            f"prompt:event:{number}", source_type, event.role, event_index, turn_index,
            event.source.start, event.source.end, raw, call_id=call_id,
            paired_call_id=call_id if event.kind == "result" else None,
            tool_name=event.name, parent_segment_id="prompt:root"))
        event_index += 1
    catalog = parse_catalog(prompt_events, prompt)
    for number, (name, spec) in enumerate(sorted(catalog.tools.items())):
        raw = prompt[spec.source.start:spec.source.end]
        segments.append(SourceSegment(
            f"prompt:tool:{number}", "TOOL_SCHEMA", "system", event_index, 0,
            spec.source.start, spec.source.end, raw, tool_name=name,
            parent_segment_id="prompt:root"))
        event_index += 1
    # The target is chronologically after the prompt trajectory even though it
    # remains a separate document with its own exact coordinates.
    segments[1] = SourceSegment("response:root", "TARGET_RESPONSE", "assistant",
                                event_index, turn_index + 1, 0, len(response), response,
                                document="response")
    return SourceTimeline(_sha(prompt), _sha(response), tuple(segments))


def verify_timeline(timeline: SourceTimeline, prompt: str, response: str) -> None:
    roots = {segment.segment_id: segment for segment in timeline.segments}
    if roots["prompt:root"].exact_text != prompt or roots["response:root"].exact_text != response:
        raise ValueError("lossless root mismatch")
    for segment in timeline.segments:
        document = prompt if segment.document == "prompt" else response
        if document[segment.start_char:segment.end_char] != segment.exact_text:
            raise ValueError(f"source mismatch for {segment.segment_id}")
