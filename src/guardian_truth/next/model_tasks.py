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

from .records import (
    Claim,
    ClaimKind,
    IdentityConstraint,
    PolicyMeaning,
    PolicyModality,
    PolicyProvenance,
    PolicyQuantification,
    PolicySubject,
    RegulatedKind,
    RegulatedMatter,
    SemanticQualifier,
    SemanticUncertainty,
    Span,
    TemporalConstraint,
)


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
        "meanings": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "modality": {"type": "string", "enum": [item.value for item in PolicyModality]},
                    "subject": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["agent", "user", "tool", "organization", "role", "other"]},
                            "identifier": {"type": "string"},
                        },
                        "required": ["kind", "identifier"],
                        "additionalProperties": False,
                    },
                    "regulated": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": [item.value for item in RegulatedKind]},
                            "predicate": {"type": "string"},
                            "object": {"type": "string"},
                        },
                        "required": ["kind", "predicate", "object"],
                        "additionalProperties": False,
                    },
                    "conditions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"quote": {"type": "string"}, "occurrence": {"type": "integer"}},
                            "required": ["quote", "occurrence"],
                            "additionalProperties": False,
                        },
                    },
                    "exceptions": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"quote": {"type": "string"}, "occurrence": {"type": "integer"}},
                            "required": ["quote", "occurrence"],
                            "additionalProperties": False,
                        },
                    },
                    "temporal": {
                        "type": "object",
                        "properties": {
                            "relation": {"type": "string", "enum": ["before", "after", "during", "until", "within", "always", "unspecified"]},
                            "anchor": {"type": "string"},
                            "duration": {"type": "string"},
                        },
                        "required": ["relation", "anchor", "duration"],
                        "additionalProperties": False,
                    },
                    "identity_constraints": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {
                                "entity_type": {"type": "string"},
                                "key": {"type": "string"},
                                "relation": {"type": "string", "enum": ["equals", "not_equals", "matches", "belongs_to", "same_as", "different_from"]},
                                "value": {"type": "string"},
                            },
                            "required": ["entity_type", "key", "relation", "value"],
                            "additionalProperties": False,
                        },
                    },
                    "quantification": {
                        "type": "object",
                        "properties": {
                            "kind": {"type": "string", "enum": ["all", "any", "exactly", "at_least", "at_most", "none", "unspecified"]},
                            "amount": {"type": "integer", "minimum": 0},
                        },
                        "required": ["kind", "amount"],
                        "additionalProperties": False,
                    },
                    "uncertainty": {"type": "string", "enum": [item.value for item in SemanticUncertainty]},
                    "unsupported_reason": {"type": "string"},
                    "quote": {"type": "string"},
                    "occurrence": {"type": "integer"},
                },
                "required": [
                    "modality", "subject", "regulated", "conditions", "exceptions", "temporal",
                    "identity_constraints", "quantification", "uncertainty", "unsupported_reason",
                    "quote", "occurrence",
                ],
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
    "required": ["meanings", "unknown_quotes"],
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


def _exact_cited_span(document: str, text: str, quote: str, occurrence: int) -> Span:
    """Resolve an exact, case-sensitive citation for policy provenance."""
    if not isinstance(quote, str) or not quote or type(occurrence) is not int or occurrence < 0:
        raise ValueError("invalid citation")
    starts = []
    cursor = 0
    while True:
        start = text.find(quote, cursor)
        if start < 0:
            break
        starts.append(start)
        cursor = start + 1
    if occurrence >= len(starts):
        raise ValueError("policy citation is not an exact substring occurrence")
    start = starts[occurrence]
    return Span(document, start, start + len(quote))


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
    meanings: tuple[PolicyMeaning, ...]
    unknown_spans: tuple[Span, ...]
    usage: dict
    returned_model: str | None

    @property
    def spans(self) -> tuple[Span, ...]:
        return tuple(meaning.provenance.source for meaning in self.meanings)


_SUBJECT_KINDS = {"agent", "user", "tool", "organization", "role", "other"}
_TEMPORAL_RELATIONS = {"before", "after", "during", "until", "within", "always", "unspecified"}
_IDENTITY_RELATIONS = {"equals", "not_equals", "matches", "belongs_to", "same_as", "different_from"}
_QUANTIFIERS = {"all", "any", "exactly", "at_least", "at_most", "none", "unspecified"}
_NUMERIC_QUANTIFIERS = {"exactly", "at_least", "at_most"}


def _nonempty_strings(row: dict, fields: set[str]) -> bool:
    return all(isinstance(row.get(field), str) and bool(row[field].strip()) for field in fields)


def _parse_qualifiers(items: Any, policy_segment: str) -> tuple[SemanticQualifier, ...]:
    if not isinstance(items, list):
        raise ValueError("invalid semantic qualifier array")
    result = []
    for item in items:
        if not _keys(item, {"quote", "occurrence"}):
            raise ValueError("invalid semantic qualifier")
        span = _exact_cited_span("prompt", policy_segment, item["quote"], item["occurrence"])
        result.append(SemanticQualifier(text=policy_segment[span.start:span.end], source=span))
    return tuple(result)


def _parse_temporal(row: Any) -> TemporalConstraint:
    expected = {"relation", "anchor", "duration"}
    if not _keys(row, expected) or not all(isinstance(row[key], str) for key in expected):
        raise ValueError("invalid temporal constraint")
    relation = row["relation"]
    anchor, duration = row["anchor"].strip(), row["duration"].strip()
    if relation not in _TEMPORAL_RELATIONS:
        raise ValueError("invalid temporal relation")
    if relation in {"before", "after", "during", "until"} and not anchor:
        raise ValueError("temporal relation requires an anchor")
    if relation == "within" and not duration:
        raise ValueError("within requires a duration")
    if relation in {"always", "unspecified"} and (anchor or duration):
        raise ValueError("unscoped temporal relation cannot carry anchor or duration")
    return TemporalConstraint(relation=relation, anchor=anchor, duration=duration)


def _parse_identities(items: Any) -> tuple[IdentityConstraint, ...]:
    expected = {"entity_type", "key", "relation", "value"}
    if not isinstance(items, list):
        raise ValueError("invalid identity constraint array")
    result = []
    for item in items:
        if (not _keys(item, expected) or not _nonempty_strings(item, expected)
                or item["relation"] not in _IDENTITY_RELATIONS):
            raise ValueError("invalid identity constraint")
        result.append(IdentityConstraint(
            entity_type=item["entity_type"].strip(), key=item["key"].strip(),
            relation=item["relation"], value=item["value"].strip(),
        ))
    return tuple(result)


def _parse_quantification(row: Any) -> PolicyQuantification:
    if (not _keys(row, {"kind", "amount"}) or not isinstance(row["kind"], str)
            or type(row["amount"]) is not int or row["amount"] < 0
            or row["kind"] not in _QUANTIFIERS):
        raise ValueError("invalid quantification")
    numeric = row["kind"] in _NUMERIC_QUANTIFIERS
    if numeric != (row["amount"] > 0):
        raise ValueError("numeric quantifiers require a positive amount; other quantifiers require zero")
    return PolicyQuantification(row["kind"], row["amount"] if numeric else None)


def parse_policy_meaning(
    content: str, policy_segment: str,
) -> tuple[tuple[PolicyMeaning, ...], tuple[Span, ...], tuple[Span, ...]]:
    """Parse a trace-independent semantic proposal under deterministic invariants."""
    payload, valid = decode_json(content)
    if not valid or not _keys(payload, {"meanings", "unknown_quotes"}):
        raise ValueError("invalid policy proposal envelope")
    if not isinstance(payload["meanings"], list) or not isinstance(payload["unknown_quotes"], list):
        raise ValueError("invalid policy proposal arrays")
    meanings = []
    expected = {
        "modality", "subject", "regulated", "conditions", "exceptions", "temporal",
        "identity_constraints", "quantification", "uncertainty", "unsupported_reason",
        "quote", "occurrence",
    }
    for row in payload["meanings"]:
        if not _keys(row, expected):
            raise ValueError("invalid policy meaning fields")
        if not isinstance(row["modality"], str) or not isinstance(row["uncertainty"], str):
            raise ValueError("invalid policy meaning categories")
        try:
            modality = PolicyModality(row["modality"])
            uncertainty = SemanticUncertainty(row["uncertainty"])
        except ValueError:
            raise ValueError("invalid policy meaning category") from None

        subject = row["subject"]
        if (not _keys(subject, {"kind", "identifier"}) or subject["kind"] not in _SUBJECT_KINDS
                or not _nonempty_strings(subject, {"kind", "identifier"})):
            raise ValueError("invalid policy subject")
        regulated = row["regulated"]
        if (not _keys(regulated, {"kind", "predicate", "object"})
                or not _nonempty_strings(regulated, {"kind", "predicate", "object"})):
            raise ValueError("invalid regulated matter")
        try:
            regulated_kind = RegulatedKind(regulated["kind"])
        except ValueError:
            raise ValueError("invalid regulated matter kind") from None

        reason = row["unsupported_reason"]
        if not isinstance(reason, str):
            raise ValueError("invalid unsupported reason")
        if uncertainty is SemanticUncertainty.CERTAIN and reason.strip():
            raise ValueError("certain meaning cannot carry an unsupported reason")
        if uncertainty is not SemanticUncertainty.CERTAIN and not reason.strip():
            raise ValueError("ambiguous or unsupported meaning requires a reason")

        source = _exact_cited_span("prompt", policy_segment, row["quote"], row["occurrence"])
        meanings.append(PolicyMeaning(
            id=f"policy_meaning:{len(meanings)}",
            modality=modality,
            subject=PolicySubject(subject["kind"], subject["identifier"].strip()),
            regulated=RegulatedMatter(
                regulated_kind, regulated["predicate"].strip(), regulated["object"].strip(),
            ),
            conditions=_parse_qualifiers(row["conditions"], policy_segment),
            exceptions=_parse_qualifiers(row["exceptions"], policy_segment),
            temporal=_parse_temporal(row["temporal"]),
            identity_constraints=_parse_identities(row["identity_constraints"]),
            quantification=_parse_quantification(row["quantification"]),
            uncertainty=uncertainty,
            unsupported_reason=reason.strip(),
            provenance=PolicyProvenance(
                source=source, quote=policy_segment[source.start:source.end],
                occurrence=row["occurrence"], extractor="llm_semantic_proposal",
            ),
        ))
    unknown = []
    for item in payload["unknown_quotes"]:
        if not _keys(item, {"quote", "occurrence"}):
            raise ValueError("invalid unknown citation")
        unknown.append(_exact_cited_span("prompt", policy_segment, item["quote"], item["occurrence"]))
    spans = tuple(meaning.provenance.source for meaning in meanings)
    return tuple(meanings), spans, tuple(unknown)


def propose_policy_meaning(client: ChatClient, policy_segment: str, *, budget=None,
                           reasoning_effort: str | None = "low") -> PolicyMeaningProposal:
    """P2/P3 boundary: accepts policy text only, never a trace or target."""
    system = (
        "Translate the POLICY SEGMENT into atomic semantic policy meanings without applying it to any trace. "
        "Represent modality, regulated actor/action-or-state, conditions, exceptions, temporal constraints, "
        "identity constraints, quantification, and uncertainty explicitly. Use exact case-sensitive verbatim "
        "quotes and zero-based occurrences. Use amount=0 for non-numeric quantifiers. Preserve text that cannot "
        "be represented in unknown_quotes. Do not emit solver predicates or invent tool effects, facts, or outcomes."
    )
    messages = [{"role": "system", "content": system},
                {"role": "user", "content": "POLICY SEGMENT:\n" + policy_segment}]
    completion = client.complete_budgeted(messages, budget=budget, schema=POLICY_MEANING_SCHEMA,
                                          reasoning_effort=reasoning_effort) \
        if budget is not None else client.complete(messages, schema=POLICY_MEANING_SCHEMA,
                                                   reasoning_effort=reasoning_effort)
    meanings, _, unknown = parse_policy_meaning(completion.content, policy_segment)
    return PolicyMeaningProposal(meanings, unknown, completion.usage, completion.model)
