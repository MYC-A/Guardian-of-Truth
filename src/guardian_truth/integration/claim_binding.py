"""Literal response-to-tool argument binding, with explicit abstention.

Only values written verbatim in a response quote are bound here. This does
not solve paraphrase, pronouns or semantic value interpretation.
"""
from __future__ import annotations

import re

from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.step2.result_types import scalar_to_json
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.verifier import TrajectoryCase


def _literal_occurs(quote: str, value: str) -> bool:
    return re.search(r"(?<![\w])" + re.escape(value) + r"(?![\w])",
                     quote, flags=re.IGNORECASE) is not None


def containing_sentence_span(response: str, start: int, end: int) -> tuple[int, int] | None:
    """Return a source-exact local sentence enclosing a claim span."""
    if start < 0 or end <= start or end > len(response):
        return None
    for match in re.finditer(r"[^.!?\n]+(?:[.!?]+|$)", response):
        if match.start() <= start and end <= match.end():
            return match.start(), match.end()
    return None


def literal_scope_arguments(case: TrajectoryCase, predicate: str, entity_value: str,
                            quote: str) -> tuple[tuple[str, str], ...] | None:
    """Bind every non-entity producer parameter from exact response text.

    Returns None if any required dimension is absent or ambiguous. An empty
    tuple means the relevant documented producer has no extra parameters.
    """
    acquired = acquire_documented(case)
    relevant = []
    for binding in acquired.bindings:
        if binding.predicate != predicate:
            continue
        catalog = [t for t in case.tools if producer_scope(case, t.get("name")) == binding.producer]
        if len(catalog) != 1 or not isinstance(catalog[0].get("parameters"), dict):
            continue
        for call in case.calls:
            if (producer_scope(case, call.tool) == binding.producer
                    and isinstance(call.payload, dict)
                    and call.payload.get(binding.entity_field) == entity_value):
                relevant.append((catalog[0], call, binding.entity_field))
    if not relevant:
        return None
    field_sets = [set(tool["parameters"]) - {entity_field}
                  for tool, _, entity_field in relevant]
    if any(fields != field_sets[0] for fields in field_sets):
        return None
    bound = []
    for field in sorted(field_sets[0]):
        matches = set()
        for _, call, _ in relevant:
            value = call.payload.get(field)
            rendered = scalar_to_json(value)
            if rendered is None:
                continue
            literal = str(value).lower() if isinstance(value, bool) else str(value)
            if _literal_occurs(quote, literal):
                matches.add(rendered)
        if len(matches) != 1:
            return None
        bound.append((field, next(iter(matches))))
    return tuple(bound)
