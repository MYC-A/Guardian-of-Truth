"""Trace-conditioned VIGIL-like competitor.

This arm deliberately derives vocabulary from the observed trace before policy
selection.  It remains separate from the trace-independent proposed compiler.
"""

from __future__ import annotations

from dataclasses import dataclass
import re
from typing import Any

from guardian_truth.pipeline import Detector

from .normalize import normalize_trace
from .policy import compile_policy


def _tokens(value: str) -> set[str]:
    return {item.casefold() for item in re.findall(r"[A-Za-zА-Яа-я0-9_]+", value)
            if len(item) > 2}


def _value_tokens(value: Any) -> set[str]:
    if isinstance(value, dict):
        result = {str(key).casefold() for key in value}
        for item in value.values():
            result |= _value_tokens(item)
        return result
    if isinstance(value, list):
        result = set()
        for item in value:
            result |= _value_tokens(item)
        return result
    return _tokens(str(value))


@dataclass(frozen=True)
class VigilResult:
    label: int
    status: str
    observed_vocabulary: tuple[str, ...]
    selected_segment_ids: tuple[str, ...]
    selected_rule_ids: tuple[str, ...]
    used_fallback: bool
    diagnostics: tuple[str, ...]


def review(prompt: str, response: str) -> VigilResult:
    events = normalize_trace(prompt, response)
    vocabulary = set()
    for event in events:
        if event.name:
            vocabulary |= _tokens(event.name)
        vocabulary |= _value_tokens(event.value)
    policy = compile_policy(prompt, arm="X4_VIGIL_LIKE")
    selected = tuple(segment.id for segment in policy.segments
                     if _tokens(segment.text) & vocabulary)
    selected_set = set(selected)
    rule_ids = tuple(rule.id for rule in policy.rules
                     if rule.id.rsplit(":", 1)[0] in selected_set)
    incumbent = Detector().review(prompt, response)
    diagnostics = list(incumbent.unresolved)
    if not selected:
        diagnostics.append("vigil_no_policy_fragment_selected")
    # No open-vocabulary translation is trusted in this competitor yet.  Tool
    # names/vocabulary only select context and never establish an effect.
    return VigilResult(
        label=int(incumbent.status == "violation"),
        status=incumbent.status,
        observed_vocabulary=tuple(sorted(vocabulary)),
        selected_segment_ids=selected,
        selected_rule_ids=rule_ids,
        used_fallback=incumbent.status != "violation",
        diagnostics=tuple(dict.fromkeys(diagnostics)),
    )
