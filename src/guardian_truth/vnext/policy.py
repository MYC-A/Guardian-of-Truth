"""P1-like behavioral hypotheses and independent missing-reading challenger.

Natural-language semantic completeness is never inferred from tool schemas.
Only an explicitly authoritative closed universe can make coverage provably closed.
"""

from __future__ import annotations

from dataclasses import dataclass

from .semantic import SemanticBackend, schema_valid
from .types import (CoverageStatus, EvaluationHypothesis, Reason, SemanticCoverage, Span)


RELATIONS = ["PROHIBITION", "REQUIREMENT", "PERMISSION", "NECESSARY", "SUFFICIENT",
             "EXCEPTION", "NO_REQUIREMENT", "DEFINITION", "IDENTITY", "EXACTLY", "UNKNOWN"]
ITEM_SCHEMA = {"type": "object", "additionalProperties": False,
    "required": ["behavioral_relation", "actor", "action_or_state", "resource", "conditions", "exceptions", "source_quotes", "unresolved_terms"],
    "properties": {"behavioral_relation": {"type": "string", "enum": RELATIONS},
        "actor": {"type": "string"}, "action_or_state": {"type": "string"}, "resource": {"type": "string"},
        **{key: {"type": "array", "items": {"type": "string"}, "uniqueItems": True}
           for key in ("conditions", "exceptions", "source_quotes", "unresolved_terms")}}}
POLICY_SCHEMA = {"type": "object", "additionalProperties": False, "required": ["interpretations", "unresolved_terms"],
    "properties": {"interpretations": {"type": "array", "items": ITEM_SCHEMA, "maxItems": 4, "uniqueItems": True},
        "unresolved_terms": {"type": "array", "items": {"type": "string"}, "uniqueItems": True}}}


@dataclass(frozen=True)
class ClosedUniverse:
    authority_basis: str
    source_id: str
    hypotheses: tuple[EvaluationHypothesis, ...]
    covers_material_policy: bool

    def __post_init__(self):
        if self.authority_basis not in {"EXPLICIT_CLOSED_DEFINITION", "AUTHORITATIVE_CLOSED_ONTOLOGY"}:
            raise ValueError("tool schema/LLM/challenger does not close policy semantics")
        if not self.source_id or not self.hypotheses or type(self.covers_material_policy) is not bool:
            raise ValueError("explicit authoritative universe required")


@dataclass(frozen=True)
class PolicyHypotheses:
    hypotheses: tuple[EvaluationHypothesis, ...]
    coverage: SemanticCoverage
    failures: tuple[Reason, ...]


def quote_spans(text: str, quotes: list[str], document: str) -> tuple[Span, ...]:
    spans = []
    if not quotes or any(not quote or quote not in text for quote in quotes):
        return ()
    for quote in quotes:
        start = 0
        while (position := text.find(quote, start)) >= 0:
            spans.append(Span(document, position, position + len(quote)))
            start = position + len(quote)
    return tuple(dict.fromkeys(spans))


def candidate(item: dict, text: str, *, ordinal: int, frontend: str) -> EvaluationHypothesis | None:
    spans = quote_spans(text, item["source_quotes"], frontend)
    if not spans or item["behavioral_relation"] == "UNKNOWN" or not item["action_or_state"]:
        return None
    # Semantic conditions may paraphrase; source_quotes remain exact grounding.
    return EvaluationHypothesis(f"{frontend}:h{ordinal}", frontend, item["behavioral_relation"],
        None if item["actor"] == "UNKNOWN" else item["actor"], item["action_or_state"],
        None if item["resource"] == "UNKNOWN" else item["resource"],
        tuple(item["conditions"]), tuple(item["exceptions"]), spans, tuple(item["unresolved_terms"]))


def parse_policy(text: str, backend: SemanticBackend, *, universe: ClosedUniverse | None = None,
                  context: dict | None = None) -> PolicyHypotheses:
    payload = {"policy": text, "context": context or {},
        "instructions": "Propose 1-4 distinct behaviorally meaningful readings, not a verdict. Keep only-if/if direction, exceptions, negation scope, cardinality, identity, temporal definitions and provenance distinct. Undefined old/trusted/suspicious remain unresolved. Cite exact source quotes. Do not infer completeness from schemas or choose a reading by confidence."}
    first = backend.propose("policy_behavioral_hypotheses", payload, POLICY_SCHEMA)
    hypotheses, discarded, unresolved, failures = [], [], [], []
    if first.transport_status != "SUCCESS":
        failures.append(Reason.TRANSPORT_ERROR)
    elif first.schema_status != "VALID" or not schema_valid(first.value, POLICY_SCHEMA):
        failures.append(Reason.SCHEMA_ERROR)
    else:
        unresolved.extend(first.value["unresolved_terms"])
        for i, item in enumerate(first.value["interpretations"]):
            hypothesis = candidate(item, text, ordinal=len(hypotheses), frontend="policy")
            if hypothesis is None:
                discarded.append((f"candidate:{i}", "UNSUPPORTED_SOURCE_GROUNDING_OR_UNKNOWN_RELATION"))
            else:
                hypotheses.append(hypothesis)
                unresolved.extend(hypothesis.unresolved_terms)
    # A separate challenger, not another vote and not a semantic-completeness proof.
    challenger_payload = {"policy": text, "context": context or {},
        "existing_behavioral_readings": [{"relation": hyp.behavioral_relation, "action": hyp.action_or_state,
            "resource": hyp.resource, "conditions": list(hyp.conditions), "exceptions": list(hyp.exceptions)} for hyp in hypotheses],
        "instructions": "Find a reasonable MISSING interpretation that could change obligations/verdict. Return distinct grounded alternatives and unresolved material terms. No alternative is empirical evidence only, NOT proof of completeness. Do not echo existing readings or use majority vote."}
    challenger = backend.propose("policy_missing_interpretation_challenger", challenger_payload, POLICY_SCHEMA)
    alternatives = []
    if challenger.transport_status != "SUCCESS":
        failures.append(Reason.TRANSPORT_ERROR)
    elif challenger.schema_status != "VALID" or not schema_valid(challenger.value, POLICY_SCHEMA):
        failures.append(Reason.SCHEMA_ERROR)
    else:
        unresolved.extend(challenger.value["unresolved_terms"])
        for i, item in enumerate(challenger.value["interpretations"]):
            hyp = candidate(item, text, ordinal=len(hypotheses), frontend="policy")
            if hyp is None:
                discarded.append((f"challenger:{i}", "UNSUPPORTED_SOURCE_GROUNDING_OR_UNKNOWN_RELATION"))
            else:
                key = (hyp.behavioral_relation, hyp.actor, hyp.action_or_state, hyp.resource, hyp.conditions, hyp.exceptions)
                if not any(key == (other.behavioral_relation, other.actor, other.action_or_state,
                                   other.resource, other.conditions, other.exceptions) for other in hypotheses):
                    hypotheses.append(hyp)
                    alternatives.append(hyp.hypothesis_id)
                unresolved.extend(hyp.unresolved_terms)
    status = CoverageStatus.OPEN_SEMANTICS if unresolved or failures or not hypotheses or discarded else CoverageStatus.EMPIRICALLY_COVERED
    universe_source, complete = None, False
    if universe is not None:
        # Authoritative mappings are enumerated, never synthesized from LLM confidence.
        if any(hyp.frontend != "policy" or not hyp.grounding or hyp.unresolved_terms
               or hyp.behavioral_relation not in RELATIONS or hyp.behavioral_relation == "UNKNOWN"
               or any(span.document != "policy" or span.end > len(text) for span in hyp.grounding)
               for hyp in universe.hypotheses):
            raise ValueError("closed-universe mappings must ground to this policy document")
        for hyp in hypotheses:
            if not any((hyp.behavioral_relation, hyp.actor, hyp.action_or_state, hyp.resource, hyp.conditions, hyp.exceptions)
                       == (allowed.behavioral_relation, allowed.actor, allowed.action_or_state,
                           allowed.resource, allowed.conditions, allowed.exceptions) for allowed in universe.hypotheses):
                discarded.append((hyp.hypothesis_id, "OUTSIDE_AUTHORITATIVE_CLOSED_UNIVERSE"))
        hypotheses = list(universe.hypotheses)
        universe_source = universe.source_id
        complete = universe.covers_material_policy
        if complete:
            status, unresolved = CoverageStatus.PROVABLY_CLOSED, []
        else:
            status = CoverageStatus.OPEN_SEMANTICS
            unresolved.append("closed universe does not cover material policy")
    if not hypotheses:
        failures.append(Reason.POLICY_NO_INTERPRETATION)
    coverage = SemanticCoverage(status, universe_source, complete, tuple(dict.fromkeys(unresolved)),
                                tuple(discarded), tuple(alternatives))
    return PolicyHypotheses(tuple(hypotheses), coverage, tuple(dict.fromkeys(failures)))
