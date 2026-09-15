"""H0: flat conservative single-structure Policy parser (spec 26-35).

One primary semantic attempt on the policy text. Only a pre-registered
format/transport repair is allowed (one re-ask when the transport payload was
not valid JSON). Schema-valid-but-semantically-suspicious output is NEVER
retried. Deterministic post-processing only: fence/JSON cleanup, schema
validation, canonical clause ordering. Invalid after repair => UNAVAILABLE,
which is not safe and not a permission.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..integrity import canonical
from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import FrontendCandidate, PolicyFlatStructure, SemanticLiteral

H0_VERSION = "policy_h0_e2e_v1"

H0_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["modality", "actor", "regulated_kind", "facet", "relation",
                 "target_clauses", "condition_clauses", "exception_clauses",
                 "condition_mode", "exception_mode", "quantification",
                 "source_quotes", "unresolved_terms"],
    "properties": {
        "modality": {"type": "string", "enum": ["PERMISSION", "PROHIBITION", "REQUIREMENT", "UNKNOWN"]},
        "actor": {"anyOf": [{"type": "string"}, {"type": "null"}]},
        "regulated_kind": {"type": "string", "enum": ["ACTION", "INFORMATION", "STATE", "EFFECT", "CLAIM", "UNKNOWN"]},
        "facet": {"type": "string", "enum": ["PRIMARY", "QUALIFIER", "OTHER", "UNKNOWN"]},
        "relation": {"type": "string", "enum": ["NONE", "IF", "ONLY_IF", "UNLESS", "BEFORE", "AFTER", "UNTIL", "WHILE", "UNKNOWN"]},
        "target_clauses": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "polarity", "normalized_key", "quote"],
            "properties": {"kind": {"type": "string", "enum": ["ACTION", "STATE", "ACTOR", "ENTITY", "CLAIM", "EVIDENCE", "VALUE", "EFFECT"]},
                "polarity": {"type": "string", "enum": ["POSITIVE", "NEGATED"]},
                "normalized_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quote": {"type": "string"}}}},
        "condition_clauses": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "polarity", "normalized_key", "quote"],
            "properties": {"kind": {"type": "string", "enum": ["ACTION", "STATE", "ACTOR", "ENTITY", "CLAIM", "EVIDENCE", "VALUE", "EFFECT"]},
                "polarity": {"type": "string", "enum": ["POSITIVE", "NEGATED"]},
                "normalized_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quote": {"type": "string"}}}},
        "exception_clauses": {"type": "array", "maxItems": 6, "items": {
            "type": "object", "additionalProperties": False,
            "required": ["kind", "polarity", "normalized_key", "quote"],
            "properties": {"kind": {"type": "string", "enum": ["ACTION", "STATE", "ACTOR", "ENTITY", "CLAIM", "EVIDENCE", "VALUE", "EFFECT"]},
                "polarity": {"type": "string", "enum": ["POSITIVE", "NEGATED"]},
                "normalized_key": {"anyOf": [{"type": "string"}, {"type": "null"}]},
                "quote": {"type": "string"}}}},
        "condition_mode": {"type": "string", "enum": ["ALL", "ANY", "UNKNOWN"]},
        "exception_mode": {"type": "string", "enum": ["ALL", "ANY", "UNKNOWN"]},
        "quantification": {"type": "string", "enum": ["ALL", "ANY", "EXACTLY_ONE", "AT_LEAST_ONE", "UNKNOWN"]},
        "source_quotes": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
        "unresolved_terms": {"type": "array", "uniqueItems": True, "items": {"type": "string"}},
    },
}

INSTRUCTIONS = (
    "Parse the POLICY text into ONE flat conservative structure for the whole policy. "
    "You see only the policy text. Do not invent rules, actors, scopes or conditions; "
    "use UNKNOWN where the text is ambiguous. Every clause must cite an exact quote that "
    "appears verbatim in the policy text. modality: PERMISSION only with explicit positive "
    "permission wording; PROHIBITION for forbid/must-not; REQUIREMENT for must/required. "
    "relation: IF when the target is required only under the condition; ONLY_IF when the "
    "condition is necessary; UNLESS for exceptions; BEFORE/AFTER for ordering: with relation "
    "BEFORE the TARGET clause is the action that MUST happen and the condition clause is the "
    "anchor action it must precede. "
    "normalized_key: when a clause names a tool, use the exact tool name verbatim as the key "
    "(for example transfer_money). "
    "List unresolved_terms ONLY for genuinely undefined normative references (for example "
    "an undefined 'old', 'trusted' or 'suspicious' qualifier) that block the interpretation. "
    "Ordinary content words such as field names or action verbs are NOT unresolved terms. "
    "This is a candidate interpretation, NOT a verdict. Return exactly one JSON object, no markdown.")


@dataclass(frozen=True)
class H0Result:
    candidate: FrontendCandidate
    structure: PolicyFlatStructure | None


def _clean_json_fences(text_value):
    """Registered transport repair: strip code fences around a JSON object."""
    if text_value is None:
        return None
    stripped = text_value.strip()
    if stripped.startswith("```"):
        stripped = stripped.strip("`")
        stripped = stripped[stripped.find("{"):] if "{" in stripped else stripped
    return stripped or None


def _literals(items, policy_text):
    out, valid = [], True
    for item in items:
        quote = item["quote"]
        if not quote or quote not in policy_text:
            valid = False
            continue
        try:
            out.append(SemanticLiteral(item["kind"], item["polarity"], item["normalized_key"], quote))
        except ValueError:
            valid = False
    return tuple(out), valid


def parse_h0(policy_text: str, backend: SemanticBackend, *, allow_format_repair: bool = True) -> H0Result:
    if not policy_text.strip():
        return H0Result(FrontendCandidate("h0", True, None), None)
    payload = {"policy": policy_text, "instructions": INSTRUCTIONS}
    proposal = backend.propose("policy_h0_flat_structure", payload, H0_SCHEMA)
    if (proposal.transport_status != "SUCCESS" and allow_format_repair
            and getattr(proposal, "payload_json", None) is None):
        # One registered format/transport repair request, then stop (spec 28).
        proposal = backend.propose("policy_h0_flat_structure", payload, H0_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return H0Result(FrontendCandidate("h0", False, "TRANSPORT", proposal.error_category), None)
    if proposal.schema_status != "VALID" or not schema_valid(proposal.value, H0_SCHEMA):
        return H0Result(FrontendCandidate("h0", False, "SCHEMA"), None)
    value = proposal.value
    targets, ok_t = _literals(value["target_clauses"], policy_text)
    conditions, ok_c = _literals(value["condition_clauses"], policy_text)
    exceptions, ok_e = _literals(value["exception_clauses"], policy_text)
    quotes = tuple(dict.fromkeys(q for q in value["source_quotes"] if q and q in policy_text))
    if not (ok_t and ok_c and ok_e) or (value["modality"] != "UNKNOWN" and not targets):
        return H0Result(FrontendCandidate("h0", False, "COMPILE", "ungrounded-or-empty-target"), None)
    # Deterministic canonical ordering; no semantic rewrite.
    targets = tuple(sorted(targets, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote)))
    conditions = tuple(sorted(conditions, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote)))
    exceptions = tuple(sorted(exceptions, key=lambda c: (c.kind, c.polarity, c.normalized_key or "", c.quote)))
    structure = PolicyFlatStructure(
        modality=value["modality"], actor=value["actor"] or "UNKNOWN",
        regulated_kind=value["regulated_kind"], facet=value["facet"], relation=value["relation"],
        target_clauses=targets, condition_literals=conditions, exception_literals=exceptions,
        condition_mode=value["condition_mode"], exception_mode=value["exception_mode"],
        quantification=value["quantification"], source_quotes=quotes,
        unresolved_terms=tuple(dict.fromkeys(value["unresolved_terms"])))
    return H0Result(FrontendCandidate("h0", True, None), structure)
