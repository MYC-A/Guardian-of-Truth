"""Trace-independent policy segmentation and conservative compilation."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
from pathlib import Path

from guardian_truth.checks import CURRENT_DATE, EXCLUSIVE_ACTION, ONE_CALL
from guardian_truth.parsing import parse_events

from .records import CoverageItem, PolicyBundle, PolicyRule, PolicySegment, Span


COMPILER_VERSION = "p0-structural-v1"
_SEGMENT = re.compile(r"(?m)^(?:#{1,6}\s+.+|\s*(?:[-*]|\d+[.)])\s+.+)$")
_POLICY_BLOCK = re.compile(r"<(instructions|policy)>\s*(?P<body>[\s\S]*?)\s*</\1>", re.IGNORECASE)


def _span(start: int, end: int) -> Span:
    return Span("prompt", start, end)


def _segments(text: str, start: int, end: int) -> list[tuple[int, int]]:
    """Cover every non-whitespace policy character with stable coarse spans."""
    body = text[start:end]
    boundaries = {0, len(body)}
    for match in _SEGMENT.finditer(body):
        boundaries.update((match.start(), match.end()))
    for match in re.finditer(r"\n\s*\n", body):
        boundaries.update((match.start(), match.end()))
    ordered = sorted(boundaries)
    result = []
    for left, right in zip(ordered, ordered[1:]):
        while left < right and body[left].isspace():
            left += 1
        while right > left and body[right - 1].isspace():
            right -= 1
        if left < right:
            result.append((start + left, start + right))
    return result


def _segment_kind(value: str) -> tuple[str, int | None]:
    stripped = value.lstrip()
    heading = re.match(r"^(#{1,6})\s+", stripped)
    if heading:
        return "HEADING", len(heading.group(1))
    if re.match(r"^(?:[-*]|\d+[.)])\s+", stripped):
        return "LIST_ITEM", None
    if stripped.startswith("|") and "|" in stripped[1:]:
        return "TABLE", None
    if re.match(r"^\[\^?[^]]+\]", stripped):
        return "FOOTNOTE", None
    return "PARAGRAPH", None


def _policy_regions(prompt: str, event) -> list[tuple[int, int]]:
    """Exclude tool schemas when explicit instruction/policy blocks exist."""
    matches = list(_POLICY_BLOCK.finditer(event.text))
    if not matches:
        return [(event.source.start, event.source.end)]
    return [(event.source.start + match.start("body"), event.source.start + match.end("body"))
            for match in matches]


def policy_source_identity(prompt: str) -> tuple[str, tuple[tuple[int, int], ...]]:
    events = parse_events(prompt, "prompt")
    systems = [event for event in events if event.role == "system" and event.kind == "text"]
    regions = [(start, end) for event in systems for start, end in _policy_regions(prompt, event)]
    source_text = [prompt[start:end] for start, end in regions]
    digest = hashlib.sha256(json.dumps(source_text, ensure_ascii=False, separators=(",", ":")).encode("utf-8")).hexdigest()
    return digest, tuple(regions)


def compile_policy(prompt: str, *, arm: str = "P0") -> PolicyBundle:
    """Compile only authoritative system text; response/trace are not accepted."""
    events = parse_events(prompt, "prompt")
    systems = [event for event in events if event.role == "system" and event.kind == "text"]
    regions = [(event_index, start, end) for event_index, event in enumerate(systems)
               for start, end in _policy_regions(prompt, event)]
    digest, _ = policy_source_identity(prompt)
    rules: list[PolicyRule] = []
    coverage: list[CoverageItem] = []
    segments: list[PolicySegment] = []
    for region_index, (event_index, region_start, region_end) in enumerate(regions):
        heading_stack: list[tuple[int, str]] = []
        for segment_index, (start, end) in enumerate(_segments(prompt, region_start, region_end)):
            segment_id = f"s{event_index}_{region_index}_{segment_index}"
            segment_text = prompt[start:end]
            kind, heading_level = _segment_kind(segment_text)
            if heading_level is not None:
                while heading_stack and heading_stack[-1][0] >= heading_level:
                    heading_stack.pop()
                parent_id = heading_stack[-1][1] if heading_stack else None
                heading_stack.append((heading_level, segment_id))
            else:
                parent_id = heading_stack[-1][1] if heading_stack else None
            segments.append(PolicySegment(segment_id, _span(start, end), kind, segment_text,
                                          len(segments), parent_id, heading_level))
            matched: list[str] = []
            for name, pattern, predicate, obj in (
                ("one_call", ONE_CALL, "max_tool_calls", 1),
                ("exclusive_action", EXCLUSIVE_ACTION, "text_xor_tool_call", True),
                ("current_date", CURRENT_DATE, "current_date", None),
            ):
                found = pattern.search(segment_text)
                if found is None:
                    continue
                value = found.group(1) if name == "current_date" else obj
                rule_id = f"{segment_id}:{name}"
                rules.append(PolicyRule(
                    id=rule_id,
                    kind="structural" if name != "current_date" else "context",
                    subject="assistant_turn" if name != "current_date" else "environment",
                    predicate=predicate,
                    object=value,
                    source=_span(start + found.start(), start + found.end()),
                    compiler=COMPILER_VERSION,
                    confidence=1.0,
                    executable=True,
                ))
                matched.append(rule_id)
            coverage.append(CoverageItem(
                segment_id=segment_id,
                span=_span(start, end),
                status=("CONTEXT" if matched and all(rule_id.endswith(":current_date") for rule_id in matched)
                        else "RULE" if matched else "UNKNOWN"),
                reason="exact_supported_pattern" if matched else "open_vocabulary_not_compiled",
                rule_ids=tuple(matched),
            ))
    return PolicyBundle(
        version=COMPILER_VERSION,
        source_hash=digest,
        segments=tuple(segments),
        rules=tuple(rules),
        coverage=tuple(coverage),
        compiler_arm=arm,
        trace_independent=True,
    )


def write_cached(bundle: PolicyBundle, cache_dir: Path) -> Path:
    """Write a content-addressed bundle; existing bytes are never rewritten."""
    cache_dir.mkdir(parents=True, exist_ok=True)
    target = cache_dir / f"{bundle.source_hash}.{bundle.compiler_arm}.json"
    encoded = json.dumps(asdict(bundle), ensure_ascii=False, sort_keys=True, indent=2)
    if target.exists():
        if target.read_text(encoding="utf-8") != encoded:
            raise ValueError("policy cache hash collision")
        return target
    target.write_text(encoded, encoding="utf-8")
    return target
