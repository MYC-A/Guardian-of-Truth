"""semantic_pipeline_v1 — Phases 7 + 13: Phi assembly (no voting).

Phi = the SET of admissible RuleIR interpretations, never one "best" rule.

  - candidates from independent extractors (Mistral / NuExtract / GLiNER2)
    are kept DISTINCT; deduplication happens ONLY on semantic_key equality
    (representation variance collapses, material disagreement never does);
  - disagreement means uncertainty, NOT majority truth (no 2-vs-1 voting);
  - NLI CONTRADICTION flags a candidate as "cannot be the only accepted
    interpretation" (A7 filtering may drop it; A6 keeps it flagged);
  - entity binding results are attached, alternatives preserved.

Structural validity (Phase 12) is enforced upstream: every RuleIR instance is
a validated pydantic model.
"""

from __future__ import annotations

from dataclasses import dataclass, field
import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

from rule_ir import RuleIR, render_rule


@dataclass
class PhiCandidate:
    rule: RuleIR
    nli: dict | None = None                # {label, scores} vs the source unit
    binding: dict | None = None            # BindingResult.as_dict() for target
    flags: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {
            "rule_id": self.rule.rule_id,
            "semantic_key": self.rule.semantic_key(),
            "extractor": self.rule.provenance.extractor,
            "modality": self.rule.modality,
            "target": {"kind": self.rule.target.kind, "text": self.rule.target.text,
                       "ref": self.rule.target.ref},
            "rendered": render_rule(self.rule),
            "nli": self.nli,
            "binding": self.binding,
            "flags": self.flags,
            "unresolved": self.rule.unresolved,
            "rule": json.loads(self.rule.model_dump_json(by_alias=True, exclude_none=True)),
        }


@dataclass
class Phi:
    case_id: str
    candidates: list[PhiCandidate] = field(default_factory=list)
    provenance_counts: dict = field(default_factory=dict)

    def as_dict(self) -> dict:
        return {"case_id": self.case_id,
                "interpretations": len(self.candidates),
                "provenance_counts": self.provenance_counts,
                "candidates": [candidate.as_dict() for candidate in self.candidates]}


def dedupe_candidates(rules: list[RuleIR]) -> list[RuleIR]:
    """Deduplicate ONLY semantically equivalent candidates (semantic_key).
    Representation variance collapses; material disagreement is preserved."""
    by_key: dict[str, RuleIR] = {}
    for rule in rules:
        key = rule.semantic_key()
        if key in by_key:
            # same semantics from different extractors: keep the FIRST, record
            # the agreement in flags later via provenance merge
            existing = by_key[key]
            merged_provenance = existing.provenance.model_copy(
                update={"raw_output": (existing.provenance.raw_output or "")[:200] + " |merged:" + rule.provenance.extractor})
            by_key[key] = existing.model_copy(update={"provenance": merged_provenance})
        else:
            by_key[key] = rule
    return list(by_key.values())


def assemble_phi(case_id: str, rules: list[RuleIR], *, nli_results: dict[str, dict] | None = None,
                 bindings: dict[str, dict] | None = None, nli_filter: bool = False) -> Phi:
    """nli_results: {rule_id: nli_dict}; bindings: {rule_id: binding_dict}."""
    nli_results = nli_results or {}
    bindings = bindings or {}
    deduped = dedupe_candidates(rules)
    candidates: list[PhiCandidate] = []
    dropped_contradicted = 0
    for rule in deduped:
        nli = nli_results.get(rule.rule_id)
        flags: dict[str, bool] = {}
        if nli is not None:
            label = nli.get("label")
            flags["supported_by_nli"] = label == "ENTAILMENT"
            flags["contradicted_by_nli"] = label == "CONTRADICTION"
            flags["cannot_be_sole_interpretation"] = label == "CONTRADICTION"
        if nli_filter and flags.get("contradicted_by_nlI", flags.get("contradicted_by_nli")):
            dropped_contradicted += 1
            continue
        candidates.append(PhiCandidate(rule=rule, nli=nli, binding=bindings.get(rule.rule_id),
                                        flags=flags))
    counts: dict[str, int] = {}
    for candidate in candidates:
        counts[candidate.rule.provenance.extractor] = counts.get(candidate.rule.provenance.extractor, 0) + 1
    phi = Phi(case_id=case_id, candidates=candidates, provenance_counts=counts)
    if dropped_contradicted:
        phi.provenance_counts["nli_filtered_contradicted"] = dropped_contradicted
    return phi
