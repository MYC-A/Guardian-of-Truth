#!/usr/bin/env python3
"""SEARCH_23 §2.3/§4.3: typed evidence status discipline (shared module).

Directive: the evidence controller must not conflate
  - a quote that EXISTS in the source (SPAN_ANCHORED)
  - a MEANING a model PROPOSED (EXTRACTED_UNVERIFIED_SEMANTICS)
  - a claim that actually FOLLOWS from the right fragment in the right scope
    (SEMANTICALLY_SUPPORTED, with method + limitation)
  - explicitly stated premises with provenance (PREMISES_VERIFIED)
  - a formally derived consequence over correct domain (FORMAL_CONSEQUENCE_VALIDATED)
  - refutation of ONE named hypothesis (SUSPICION_REFUTED) vs the whole case
    (CASE_VERDICT)
AMBIGUOUS / NOT_FOUND / FAILED are never truth or falsity.

This module is deliberately stdlib-only and side-effect-free so it can be
unit-tested (ev_controller_regression.py) and reused by q_discriminator_v2,
router_v1_audit and investigator_v2.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Optional

# ---------------------------------------------------------------- statuses ----

OBSERVED_STRUCTURED = "OBSERVED_STRUCTURED"
SPAN_ANCHORED = "SPAN_ANCHORED"
EXTRACTED_UNVERIFIED_SEMANTICS = "EXTRACTED_UNVERIFIED_SEMANTICS"
SEMANTICALLY_SUPPORTED = "SEMANTICALLY_SUPPORTED"
PREMISES_VERIFIED = "PREMISES_VERIFIED"
FORMAL_CONSEQUENCE_VALIDATED = "FORMAL_CONSEQUENCE_VALIDATED"
AMBIGUOUS = "AMBIGUOUS"
NOT_FOUND = "NOT_FOUND"
FAILED = "FAILED"
SUSPICION_REFUTED = "SUSPICION_REFUTED"
SUSPICION_SUPPORTED = "SUSPICION_SUPPORTED"
UNKNOWN = "UNKNOWN"
CONFLICTING = "CONFLICTING"
CASE_VERDICT = "CASE_VERDICT"

STATUS_DOC = {
    OBSERVED_STRUCTURED: "verifiable field/event taken from an exact source result",
    SPAN_ANCHORED: "the source quote actually exists (verbatim, normalized)",
    EXTRACTED_UNVERIFIED_SEMANTICS: "meaning/subject/relation proposed by a model",
    SEMANTICALLY_SUPPORTED: "the specific claim follows from the needed fragment in "
                            "the right scope; method and limitation recorded",
    PREMISES_VERIFIED: "explicitly stated premises with provenance",
    FORMAL_CONSEQUENCE_VALIDATED: "formal derivation over a correct, bound domain",
    AMBIGUOUS: "more than one binding/reading possible; not truth or falsity",
    NOT_FOUND: "looked for, absent; not equal to FALSE or SAFE",
    FAILED: "the check itself failed; never evidence",
    SUSPICION_REFUTED: "enough verified grounds to refute the NAMED hypothesis only",
    SUSPICION_SUPPORTED: "enough verified grounds to support the NAMED hypothesis",
    UNKNOWN: "insufficient grounds either way",
    CONFLICTING: "verified grounds point in both directions",
    CASE_VERDICT: "conclusion over ALL suspicions + fixed fallback",
}

# verification strength for flip gating (higher = stronger)
STRENGTH = {
    OBSERVED_STRUCTURED: 3,
    FORMAL_CONSEQUENCE_VALIDATED: 3,
    PREMISES_VERIFIED: 3,
    SPAN_ANCHORED: 1,          # quote exists — says NOTHING about the inference
    SEMANTICALLY_SUPPORTED: 2, # probabilistic unless mechanically grounded
    EXTRACTED_UNVERIFIED_SEMANTICS: 0,
    AMBIGUOUS: 0,
    NOT_FOUND: 0,
    FAILED: 0,
    UNKNOWN: 0,
}


def norm(t: str) -> str:
    return re.sub(r"\s+", " ", (t or "")).strip().lower()


def span_anchor(fragment: str, source_text: str) -> dict:
    """MECHANICAL verbatim anchoring of a fragment inside a source text.

    Returns dict with `anchored` bool, `normalized` bool (matched only after
    whitespace/case normalization — weaker, recorded separately).
    """
    if not fragment or not source_text:
        return {"anchored": False, "normalized": False}
    if fragment in source_text:
        return {"anchored": True, "normalized": False}
    nf, ns = norm(fragment), norm(source_text)
    return {"anchored": False, "normalized": bool(nf) and nf in ns}


def entity_binding(entity: str, candidates: list) -> dict:
    """Bind a named entity to observed structured candidates.

    candidates: [{"id":..., "value":...}, ...] — exact source items.
    Matching is CONTAINMENT on normalized text (entity substring of id/value
    or vice versa). Returns binding status: unique / ambiguous / none —
    never a silent pick between multiple hits.
    """
    ent = norm(entity)
    hits = []
    for c in candidates:
        cid = norm(str(c.get("id", "")))
        cval = norm(str(c.get("value", "")))
        if ent and (ent in cid or ent in cval or (cid and cid in ent)
                    or (cval and cval in ent)):
            hits.append(c)
    if len(hits) == 1:
        return {"status": "unique", "bound": hits[0]}
    if len(hits) > 1:
        return {"status": AMBIGUOUS, "bound": None, "n_candidates": len(hits)}
    return {"status": NOT_FOUND, "bound": None}


# ---------------------------------------------------------------- registry ----

@dataclass
class EvidenceItem:
    tool: str
    query: str
    status: str                      # one of the statuses above
    evidence_refs: list = field(default_factory=list)   # [{source_id, span, offset?}]
    limitations: list = field(default_factory=list)
    method: Optional[str] = None     # e.g. "verbatim substring", "clingo 5.8.2"
    new_information: bool = False
    provenance: dict = field(default_factory=dict)


@dataclass
class Suspicion:
    suspicion_id: str
    claim: str                       # the concrete action/statement/refusal checked
    policy_clause: str = ""
    suspected_violation: str = ""
    alternative_explanation: str = ""  # what would refute THIS suspicion
    scope: dict = field(default_factory=dict)  # entity/time/action binding
    evidence_refs: list = field(default_factory=list)
    disposition: str = UNKNOWN


# ------------------------------------------------------------ controller ----

class EvidenceControllerV2:
    """Independent validation of tool results + per-suspicion disposition.

    v1 defect being fixed (directive §2.3): `VERIFIED_BY_SPAN` promoted an NL
    answer to proof whenever its deciding words existed in the policy — the
    existence of a quote proves neither that the answer follows from it, nor
    that it addresses the right rule/entity, nor that refuting one ground
    clears the whole case.

    v2 rules:
      - NL answers are SPAN_ANCHORED at best; semantic support is a SEPARATE,
        explicitly recorded, probabilistic check (method + limitation).
      - SUSPICION_REFUTED requires verified grounds (strength >= 2) targeted
        at the NAMED suspicion (binding + scope must match).
      - 1 -> 0 case flip requires ALL suspicions refuted AND the counter
        hypothesis (missed-violation scan) to be clear.
      - 0 -> 1 flip requires a suspicion SUPPORTED by mechanical/formal
        evidence (strength >= 3).
      - everything else keeps the control label; UNKNOWNs are reported.
    """

    def validate_nl(self, answer: dict, policy_text: str, question: str) -> EvidenceItem:
        dw = str(answer.get("deciding_words", "") or "")
        ans = str(answer.get("answer", "") or "")
        if not ans:
            return EvidenceItem(tool="nl_question", query=question, status=FAILED,
                                limitations=["empty answer"])
        a = span_anchor(dw, policy_text)
        item = EvidenceItem(
            tool="nl_question", query=question,
            status=EXTRACTED_UNVERIFIED_SEMANTICS,
            method="llm_answer+mechanical_span_check",
            limitations=["LLM semantics are probabilistic; span existence does not "
                         "entail the claimed inference"])
        if dw and (a["anchored"] or a["normalized"]):
            item.status = SPAN_ANCHORED
            item.evidence_refs = [{"source": "policy", "span": dw[:200],
                                   "verbatim": a["anchored"]}]
            item.limitations.append("quote anchored; entailment NOT checked here")
        return item

    def semantic_support(self, claim: str, fragment: str, verdict: str,
                         method: str = "llm_entailment_probabilistic") -> EvidenceItem:
        """Record a SEPARATE semantic support check. `verdict` in
        {"supports","refutes","neither"}; the method string must name its own
        limitation. Never upgrades SPAN_ANCHORED to formal proof."""
        st = {"supports": SEMANTICALLY_SUPPORTED,
              "refutes": SEMANTICALLY_SUPPORTED}.get(
            verdict, UNKNOWN if verdict == "neither" else FAILED)
        return EvidenceItem(
            tool="semantic_check", query=claim[:200], status=st, method=method,
            limitations=["probabilistic semantic signal, not a formal guarantee"],
            evidence_refs=[{"source": "policy", "span": fragment[:200]}] if fragment else [])

    def validate_structured(self, tool: str, result: dict, query: str) -> EvidenceItem:
        """Structured/graph/python tool result validation."""
        if not result or result.get("error"):
            return EvidenceItem(tool=tool, query=query, status=FAILED,
                                limitations=[str(result.get("error", "empty"))[:200]])
        args = result.get("arguments") or []
        if not args:
            return EvidenceItem(tool=tool, query=query, status=NOT_FOUND,
                                limitations=["no matching structured items"])
        bad = [a for a in args if a.get("status") in
               ("observed_mismatch", "value_conflict", "scope_conflict")]
        item = EvidenceItem(tool=tool, query=query, status=OBSERVED_STRUCTURED,
                            method="graph/provenance",
                            new_information=bool(bad))
        return item

    def disposition(self, suspicion: Suspicion, items: list) -> str:
        """Per-suspicion disposition from typed evidence items."""
        refs = {i.status for i in items}
        mech = any(i.status in (OBSERVED_STRUCTURED, FORMAL_CONSEQUENCE_VALIDATED,
                                PREMISES_VERIFIED) and i.new_information for i in items)
        sem_refute = any(i.status == SEMANTICALLY_SUPPORTED and i.tool == "semantic_check"
                         for i in items)
        amb = AMBIGUOUS in refs or any(i.status == AMBIGUOUS for i in items)
        if mech:
            return SUSPICION_SUPPORTED if any(
                _in_scope(i, suspicion) for i in items if i.new_information) else UNKNOWN
        if amb:
            return AMBIGUOUS
        if items and all(i.status in (NOT_FOUND, FAILED) for i in items):
            return NOT_FOUND
        # semantic-only or span-only evidence: probabilistic — never a flip basis
        return UNKNOWN

    # ---------------- aggregation (fixed BEFORE any run) ----------------

    def case_verdict(self, suspicions: list, control_label: int,
                     counter_hypothesis_clear: Optional[bool] = None,
                     fallback: str = "control") -> dict:
        """Aggregate per-suspicion dispositions into the contest label.

        flip 1->0 : ALL suspicions SUSPICION_REFUTED on verified grounds AND
                    the counter-hypothesis (missed violation) is clear.
        flip 0->1 : >= 1 suspicion SUSPICION_SUPPORTED with mechanical/formal
                    evidence.
        else      : keep control; UNKNOWNs reported separately.
        """
        disps = [s.disposition for s in suspicions]
        out = {"control": control_label, "label": control_label,
               "flip": None, "dispositions": disps,
               "n_unknown": sum(1 for d in disps if d in (UNKNOWN, AMBIGUOUS, NOT_FOUND))}
        supported = any(d == SUSPICION_SUPPORTED for d in disps)
        refuted_all = bool(suspicions) and all(
            d == SUSPICION_REFUTED for d in disps)
        if control_label == 0 and supported:
            out["label"] = 1
            out["flip"] = "0->1:suspicion_supported_mechanical"
        elif control_label == 1 and refuted_all and counter_hypothesis_clear:
            out["label"] = 0
            out["flip"] = "1->0:all_suspicions_refuted+counter_clear"
        return out


def _in_scope(item: EvidenceItem, suspicion: Suspicion) -> bool:
    """Scope check: entity/time/action binding of the evidence must intersect
    the suspicion scope. Placeholder predicates are explicit; no guessing."""
    sc = suspicion.scope or {}
    refs = item.evidence_refs or []
    if not sc:
        return True  # unrestricted suspicion scope — mechanical result applies
    ent = norm(str(sc.get("entity", "")))
    if ent and refs:
        return any(ent in norm(str(r)) for r in refs)
    return True
