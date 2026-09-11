"""Trace-independent policy segmentation and conservative compilation."""

from __future__ import annotations

from dataclasses import asdict
import hashlib
import json
import re
from pathlib import Path

from guardian_truth.checks import CURRENT_DATE, EXCLUSIVE_ACTION, ONE_CALL
from guardian_truth.parsing import parse_events

from .records import CoverageItem, PolicyBundle, PolicyRule, Span


COMPILER_VERSION = "p0-structural-v1"
_SEGMENT = re.compile(r"(?m)^(?:#{1,6}\s+.+|\s*(?:[-*]|\d+[.)])\s+.+)$")


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


def compile_policy(prompt: str, *, arm: str = "P0") -> PolicyBundle:
    """Compile only authoritative system text; response/trace are not accepted."""
    events = parse_events(prompt, "prompt")
    systems = [event for event in events if event.role == "system" and event.kind == "text"]
    source_text = "".join(prompt[e.source.start:e.source.end] for e in systems)
    digest = hashlib.sha256(source_text.encode("utf-8")).hexdigest()
    rules: list[PolicyRule] = []
    coverage: list[CoverageItem] = []
    for event_index, event in enumerate(systems):
        for segment_index, (start, end) in enumerate(_segments(prompt, event.source.start, event.source.end)):
            segment_id = f"s{event_index}_{segment_index}"
            segment_text = prompt[start:end]
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
                status="compiled" if matched else "unknown",
                reason="exact_supported_pattern" if matched else "open_vocabulary_not_compiled",
                rule_ids=tuple(matched),
            ))
    return PolicyBundle(
        version=COMPILER_VERSION,
        source_hash=digest,
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
