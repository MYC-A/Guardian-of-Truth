"""Conservative bridge from model claim proposals to source-bound proof queries.

The model supplies a predicate/mode candidate. This compiler requires literal
response evidence for entity, value and every extra producer argument. It
abstains on paraphrase and negation; it does not manufacture a WorldFact.
"""
from __future__ import annotations

from dataclasses import dataclass
import json
import re

from guardian_truth.integration.candidate_claims import (
    candidate_meanings, validate_proposal)
from guardian_truth.integration.claim_binding import (
    _literal_occurs, containing_sentence_span, literal_scope_arguments)
from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.integration.proof_engine import ClaimQuery
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.verifier import TrajectoryCase


_NEGATION = re.compile(r"\b(?:not|never|no|cannot|can't|didn't|wasn't|hasn't|не|нет)\b",
                       re.IGNORECASE)
_WORD = re.compile(r"\w+", re.UNICODE)


@dataclass(frozen=True)
class CompiledClaims:
    queries: tuple[ClaimQuery, ...]
    nonfactual: tuple[dict, ...]
    issues: tuple[str, ...]
    inventory_complete: bool


def _literal_entity(case: TrajectoryCase, predicate: str, sentence: str) -> str | None:
    bindings = [b for b in acquire_documented(case).bindings if b.predicate == predicate]
    values = set()
    for binding in bindings:
        for call in case.calls:
            if (producer_scope(case, call.tool) != binding.producer
                    or not isinstance(call.payload, dict)):
                continue
            value = call.payload.get(binding.entity_field)
            if isinstance(value, (str, int)) and not isinstance(value, bool):
                if _literal_occurs(sentence, str(value)):
                    values.add(str(value))
    return next(iter(values)) if len(values) == 1 else None


def _literal_value(case: TrajectoryCase, predicate: str, sentence: str):
    values: dict[str, object] = {}
    for binding in acquire_documented(case).bindings:
        if binding.predicate != predicate:
            continue
        for canonical in binding.allowed_values:
            value = json.loads(canonical)
            if isinstance(value, str) and _literal_occurs(sentence, value):
                values[canonical] = value
            elif isinstance(value, (int, float)) and not isinstance(value, bool):
                if _literal_occurs(sentence, str(value)):
                    values[canonical] = value
            # Boolean polarity requires a separate licensed interpretation.
    return next(iter(values.values())) if len(values) == 1 else None


def compile_candidate_claims(response: str, response_index: int,
                             case: TrajectoryCase, raw: str) -> CompiledClaims:
    candidates = candidate_meanings(case)
    accepted, syntax_issues = validate_proposal(response, candidates, raw)
    issues = list(syntax_issues)
    queries: list[ClaimQuery] = []
    nonfactual: list[dict] = []
    covered = [False] * len(response)
    candidate_types = {c.predicate: c.entity_type for c in candidates}
    for item in accepted:
        if item["mode"] == "NONE":
            continue
        quote = item["quote"]
        if not quote:
            issues.append(f"{item['id']}:empty_active_quote")
            continue
        start, end = item["start"], item["end"]
        for i in range(start, end):
            covered[i] = True
        mode = item["mode"]
        if mode in {"PROPOSED", "CONDITIONAL", "REQUEST", "REFUSAL"}:
            nonfactual.append(item)
            continue
        if mode not in {"CLAIMED_COMPLETED", "STATE_CLAIM"}:
            issues.append(f"{item['id']}:mode_unknown")
            continue
        span = containing_sentence_span(response, start, end)
        if span is None:
            issues.append(f"{item['id']}:sentence_unbound")
            continue
        sentence = response[span[0]:span[1]]
        if _NEGATION.search(sentence):
            issues.append(f"{item['id']}:negated_literal_requires_semantics")
            continue
        predicate = item["predicate"]
        entity = _literal_entity(case, predicate, sentence)
        value = _literal_value(case, predicate, sentence)
        scope = (literal_scope_arguments(case, predicate, entity, sentence)
                 if entity is not None else None)
        if entity is None or value is None or scope is None:
            issues.append(f"{item['id']}:literal_entity_value_or_scope_unbound")
            continue
        actor = ("ASSISTANT" if re.match(r"^\s*I\b", sentence)
                 else "UNSPECIFIED")
        queries.append(ClaimQuery(response, response_index, quote, start, end,
                                  mode, predicate, candidate_types[predicate],
                                  entity, value, "MODEL_PROPOSED_LITERAL_GROUNDED",
                                  actor, scope, span))
    uncovered = [response[m.start():m.end()] for m in _WORD.finditer(response)
                 if not all(covered[i] for i in range(m.start(), m.end()))]
    if uncovered:
        issues.append("uncovered_response_words:" + ",".join(uncovered[:8]))
    return CompiledClaims(tuple(queries), tuple(nonfactual), tuple(issues),
                          not issues)
