"""Construction of the admissible interpretation set without majority voting."""

from __future__ import annotations

from dataclasses import replace

from .rule_ir import rule_digest
from .types import RuleCandidate, SemanticInterpretationSet


def build_phi(candidates, source_coverage, *, contradiction_threshold: float = 0.5):
    merged: dict[str, RuleCandidate] = {}
    unresolved = []
    for candidate in candidates:
        digest = candidate.canonical_digest or rule_digest(candidate.rule)
        contradicted = any(
            evidence.label == "CONTRADICTION"
            and evidence.scores.get("CONTRADICTION", 0.0) >= contradiction_threshold
            for evidence in candidate.nli_evidence)
        if contradicted:
            unresolved.append(f"source-contradicted:{candidate.candidate_id}")
            continue
        current = replace(candidate, canonical_digest=digest)
        if digest in merged:
            previous = merged[digest]
            current = replace(
                previous,
                extractors=tuple(dict.fromkeys((*previous.extractors, *current.extractors))),
                source_spans=tuple(dict.fromkeys((*previous.source_spans, *current.source_spans))),
                source_segment_ids=tuple(dict.fromkeys(
                    (*previous.source_segment_ids, *current.source_segment_ids))),
                nli_evidence=tuple((*previous.nli_evidence, *current.nli_evidence)),
                binding_alternatives=tuple(dict.fromkeys(
                    (*previous.binding_alternatives, *current.binding_alternatives))),
                unresolved_components=tuple(dict.fromkeys(
                    (*previous.unresolved_components, *current.unresolved_components))))
        merged[digest] = current
    for candidate in merged.values():
        unresolved.extend(candidate.unresolved_components)
    return SemanticInterpretationSet(tuple(merged[key] for key in sorted(merged)),
                                     tuple(dict.fromkeys(unresolved)), tuple(source_coverage))
