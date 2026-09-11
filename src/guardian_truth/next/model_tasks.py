"""Typed LLM proposal tasks with deterministic validation.

The model proposes records.  Exact source matching and all semantic decisions
remain outside the model.  Each function exposes a narrow visibility boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re
from typing import Any

from guardian_truth.llm_client import ChatClient
from guardian_truth.parsing import decode_json

from .records import Claim, ClaimKind, Span


CLAIM_SCHEMA = {
    "type": "object",
    "properties": {
        "claims": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": [item.value for item in ClaimKind]},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "modality": {"type": "string", "enum": ["asserted", "intent", "completed"]},
                    "quote": {"type": "string"},
                    "occurrence": {"type": "integer"},
                    "entities": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"key": {"type": "string"}, "value": {"type": "string"}},
                            "required": ["key", "value"],
                            "additionalProperties": False,
                        },
                    },
                },
                "required": ["kind", "subject", "predicate", "object", "modality", "quote", "occurrence", "entities"],
                "additionalProperties": False,
            },
        },
        "uncovered_quotes": {"type": "array", "items": {
            "type": "object",
            "properties": {"quote": {"type": "string"}, "occurrence": {"type": "integer"}},
            "required": ["quote", "occurrence"],
            "additionalProperties": False,
        }},
    },
    "required": ["claims", "uncovered_quotes"],
    "additionalProperties": False,
}


POLICY_MEANING_SCHEMA = {
    "type": "object",
    "properties": {
        "rules": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "kind": {"type": "string", "enum": ["permission", "prohibition", "requirement", "context"]},
                    "subject": {"type": "string"},
                    "predicate": {"type": "string"},
                    "object": {"type": "string"},
                    "quote": {"type": "string"},
                    "occurrence": {"type": "integer"},
                },
                "required": ["kind", "subject", "predicate", "object", "quote", "occurrence"],
                "additionalProperties": False,
            },
        },
        "unknown_quotes": {"type": "array", "items": {
            "type": "object",
            "properties": {"quote": {"type": "string"}, "occurrence": {"type": "integer"}},
            "required": ["quote", "occurrence"],
            "additionalProperties": False,
        }},
    },
    "required": ["rules", "unknown_quotes"],
    "additionalProperties": False,
}


def _keys(value: Any, required: set[str]) -> bool:
    return isinstance(value, dict) and set(value) == required


def _cited_span(document: str, text: str, quote: str, occurrence: int) -> Span:
    if not isinstance(quote, str) or not quote or type(occurrence) is not int or occurrence < 0:
        raise ValueError("invalid citation")
    patterns = [re.escape(quote)]
    whitespace_tolerant = r"\s+".join(re.escape(part) for part in quote.split())
    if whitespace_tolerant not in patterns:
        patterns.append(whitespace_tolerant)
    matches = []
    for pattern in patterns:
        matches = list(re.finditer(pattern, text, re.IGNORECASE))
        if matches:
            break
    # Models often emit their claim index here.  If the cited text has exactly
    # one deterministic match, that match is unambiguous regardless of the
    # supplied occurrence.  Multiple matches still require a valid index.
    if len(matches) == 1:
        occurrence = 0
    if occurrence >= len(matches):
        raise ValueError("citation is not a verbatim substring occurrence")
    match = matches[occurrence]
    return Span(document, match.start(), match.end())


@dataclass(frozen=True)
class ClaimProposal:
    claims: tuple[Claim, ...]
    uncovered: tuple[Span, ...]
    usage: dict
    returned_model: str | None


def parse_claim_proposal(content: str, response: str) -> tuple[tuple[Claim, ...], tuple[Span, ...]]:
    payload, valid = decode_json(content)
    if not valid or not _keys(payload, {"claims", "uncovered_quotes"}):
        raise ValueError("invalid claim proposal envelope")
    if not isinstance(payload["claims"], list) or not isinstance(payload["uncovered_quotes"], list):
        raise ValueError("invalid claim proposal arrays")
    claims = []
    for row in payload["claims"]:
        expected = {"kind", "subject", "predicate", "object", "modality", "quote", "occurrence", "entities"}
        string_fields = expected - {"entities", "occurrence"}
        if (not _keys(row, expected) or not all(isinstance(row[key], str) for key in string_fields)
                or type(row["occurrence"]) is not int):
            raise ValueError("invalid claim record")
        try:
            kind = ClaimKind(row["kind"])
        except ValueError:
            raise ValueError("invalid claim kind") from None
        if row["modality"] not in {"asserted", "intent", "completed"} or not isinstance(row["entities"], list):
            raise ValueError("invalid claim modality/entities")
        entities = []
        for entity in row["entities"]:
            if not _keys(entity, {"key", "value"}) or not all(isinstance(v, str) and v for v in entity.values()):
                raise ValueError("invalid entity")
            entities.append((entity["key"], entity["value"]))
        claims.append(Claim(
            id=f"llm_claim:{len(claims)}", kind=kind, subject=row["subject"],
            predicate=row["predicate"], object=row["object"],
            source=_cited_span("response", response, row["quote"], row["occurrence"]),
            modality=row["modality"], entities=tuple(sorted(entities)), extractor="llm_typed",
        ))
    uncovered = []
    for item in payload["uncovered_quotes"]:
        if not _keys(item, {"quote", "occurrence"}):
            raise ValueError("invalid uncovered citation")
        uncovered.append(_cited_span("response", response, item["quote"], item["occurrence"]))
    return tuple(claims), tuple(uncovered)


def propose_claims(client: ChatClient, response: str, *, budget=None,
                   reasoning_effort: str | None = "low") -> ClaimProposal:
    """C1/C2 boundary: only the candidate response is sent to the model."""
    system = (
        "Extract every externally checkable atomic claim from the candidate response. "
        "Distinguish intent from completed action, assertions from observations, and not-found from absence. "
        "Use a verbatim quote from RESPONSE and its zero-based occurrence for every item. Put any meaningful "
        "text you cannot type into uncovered_quotes. Do not decide whether a claim is true."
    )
    completion = client.complete_budgeted(
        [{"role": "system", "content": system}, {"role": "user", "content": "RESPONSE:\n" + response}],
        budget=budget, schema=CLAIM_SCHEMA, reasoning_effort=reasoning_effort,
    ) if budget is not None else client.complete(
        [{"role": "system", "content": system}, {"role": "user", "content": "RESPONSE:\n" + response}],
        schema=CLAIM_SCHEMA, reasoning_effort=reasoning_effort,
    )
    claims, uncovered = parse_claim_proposal(completion.content, response)
    return ClaimProposal(claims, uncovered, completion.usage, completion.model)


@dataclass(frozen=True)
class PolicyMeaningProposal:
    payload: dict
    spans: tuple[Span, ...]
    unknown_spans: tuple[Span, ...]
    usage: dict
    returned_model: str | None


def parse_policy_meaning(content: str, policy_segment: str) -> tuple[dict, tuple[Span, ...], tuple[Span, ...]]:
    payload, valid = decode_json(content)
    if not valid or not _keys(payload, {"rules", "unknown_quotes"}):
        raise ValueError("invalid policy proposal envelope")
    if not isinstance(payload["rules"], list) or not isinstance(payload["unknown_quotes"], list):
        raise ValueError("invalid policy proposal arrays")
    spans = []
    for row in payload["rules"]:
        expected = {"kind", "subject", "predicate", "object", "quote", "occurrence"}
        if (not _keys(row, expected)
                or not all(isinstance(row[key], str) and row[key] for key in expected - {"occurrence"})
                or type(row["occurrence"]) is not int):
            raise ValueError("invalid policy rule")
        if row["kind"] not in {"permission", "prohibition", "requirement", "context"}:
            raise ValueError("invalid policy kind")
        spans.append(_cited_span("prompt", policy_segment, row["quote"], row["occurrence"]))
    unknown = []
    for item in payload["unknown_quotes"]:
        if not _keys(item, {"quote", "occurrence"}):
            raise ValueError("invalid unknown citation")
        unknown.append(_cited_span("prompt", policy_segment, item["quote"], item["occurrence"]))
    return payload, tuple(spans), tuple(unknown)


def propose_policy_meaning(client: ChatClient, policy_segment: str, *, budget=None,
                           reasoning_effort: str | None = "low") -> PolicyMeaningProposal:
    """P2/P3 boundary: accepts policy text only, never a trace or target."""
    system = (
        "Translate the POLICY SEGMENT into atomic policy meanings without applying it to any trace. "
        "Use verbatim quotes and zero-based occurrences. Preserve unknown or ambiguous clauses in unknown_quotes. "
        "Do not invent tool effects, entities, facts, or outcomes."
    )
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "POLICY SEGMENT:\n" + policy_segment}]
    completion = client.complete_budgeted(messages, budget=budget, schema=POLICY_MEANING_SCHEMA,
                                          reasoning_effort=reasoning_effort) \
        if budget is not None else client.complete(messages, schema=POLICY_MEANING_SCHEMA,
                                                   reasoning_effort=reasoning_effort)
    payload, spans, unknown = parse_policy_meaning(completion.content, policy_segment)
    return PolicyMeaningProposal(payload, spans, unknown, completion.usage, completion.model)
