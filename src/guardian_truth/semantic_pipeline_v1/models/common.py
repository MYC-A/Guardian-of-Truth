"""Shared strict normalization from independent extractor output to RuleCandidate."""

from __future__ import annotations

import hashlib
import json

from ..rule_ir import rule_digest, rule_from_dict
from ..types import RuleCandidate, SourceSpan


def extract_json_object(text: str) -> dict:
    decoder = json.JSONDecoder()
    for index, char in enumerate(text):
        if char != "{":
            continue
        try:
            value, _ = decoder.raw_decode(text[index:])
        except ValueError:
            continue
        if isinstance(value, dict):
            return value
    raise ValueError("extractor did not return a JSON object")


def normalize_candidates(value: dict, *, extractor: str, segment_id: str,
                         source_text: str) -> tuple[RuleCandidate, ...]:
    candidates = []
    for index, item in enumerate(value.get("rules", ())):
        try:
            rule = rule_from_dict(item)
        except (KeyError, TypeError, ValueError):
            continue
        spans, unresolved = [], list(rule.unresolved_references)
        for raw_span in item.get("source_spans", ()):
            try:
                start, end = int(raw_span["start"]), int(raw_span["end"])
                quote = raw_span["quote"]
                if source_text[start:end] != quote or not quote:
                    raise ValueError
                spans.append(SourceSpan(segment_id, start, end, quote))
            except (KeyError, TypeError, ValueError):
                unresolved.append("invalid-or-ungrounded-source-span")
        if not spans:
            unresolved.append("missing-exact-source-span")
        digest = rule_digest(rule)
        candidate_id = hashlib.sha256(
            f"{extractor}\0{segment_id}\0{index}\0{digest}".encode("utf-8")).hexdigest()[:20]
        candidates.append(RuleCandidate(candidate_id, rule, tuple(spans), (segment_id,),
                                        (extractor,), unresolved_components=tuple(dict.fromkeys(unresolved)),
                                        canonical_digest=digest))
    return tuple(candidates)


EXTRACTION_INSTRUCTIONS = """Extract semantic rules only; never judge whether the response is erroneous.
Return one JSON object with a `rules` array. Each rule uses compositional RuleIR:
modality REQUIRE|FORBID|ALLOW|UNKNOWN; subject; target {kind ACTION|STATE|CLAIM|INFORMATION|EFFECT,
name,value,entity_ref,field}; relation IF|ONLY_IF|UNLESS|NONE; temporal BEFORE|AFTER|UNTIL|WHILE|NONE;
condition/exception expression trees with operators ATOM, AND, OR, NOT, COMPARE, CARDINALITY;
comparators EQ,NE,LT,LE,GT,GE; cardinality EXACT,MIN,MAX. Cite source_spans as exact offsets and quotes
relative to SOURCE. Preserve unresolved references. Do not invent tool names or facts."""
