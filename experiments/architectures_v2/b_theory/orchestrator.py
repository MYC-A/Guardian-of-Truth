"""Gold-free B0/B1/B2/B3 orchestration over injectable theory outputs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from .contracts import (AccountStatus, CaseInput, Clause, ClauseAccount,
                        TheoryCandidate, TheoryElement, Variant)
from .grounding import validate_clause, validate_link
from .ruleir_boundary import prepare_rule_ir, serialise_boundary


def _element_record(element: TheoryElement, sources, *, require_grounding: bool) -> dict:
    checks = [validate_link(link, sources) for link in element.source_links]
    anchored = bool(checks) and all(valid for valid, _ in checks)
    boundary = prepare_rule_ir(element, sources)
    return {
        "element_id": element.element_id,
        "interpretation": element.interpretation,
        "grounding_status": "ANCHORED" if anchored else "UNANCHORED",
        "grounding_issues": [reason for valid, reason in checks if not valid]
        + ([] if checks else ["NO_SOURCE_LINK"]),
        "eligible_for_variant": anchored or not require_grounding,
        "ruleir_boundary": serialise_boundary(boundary),
    }


def _link_in_clause(element: TheoryElement, clause: Clause) -> bool:
    return any(link.source_id == clause.link.source_id
               and clause.link.start <= link.start < link.end <= clause.link.end
               for link in element.source_links)


def _ledger(candidate: TheoryCandidate, clauses: tuple[Clause, ...]) -> list[dict]:
    accounts = {item.clause_id: item for item in candidate.clause_accounts}
    elements = {item.element_id: item for item in candidate.elements}
    rows = []
    for clause in clauses:
        account = accounts.get(clause.clause_id)
        if account is None:
            rows.append({"clause_id": clause.clause_id, "status": "unresolved",
                         "reason": "MISSING_CLAUSE_ACCOUNT", "element_ids": []})
            continue
        status, reason = account.status.value, account.reason
        if account.status is AccountStatus.ACCOUNTED_FOR:
            selected = [elements.get(item) for item in account.element_ids]
            if (not selected or any(item is None for item in selected)
                    or any(not _link_in_clause(item, clause) for item in selected if item)):
                status, reason = "unresolved", "ACCOUNT_NOT_GROUNDED_IN_CLAUSE"
        rows.append({"clause_id": clause.clause_id, "status": status,
                     "reason": reason, "element_ids": list(account.element_ids)})
    unknown = sorted(set(accounts) - {item.clause_id for item in clauses})
    for clause_id in unknown:
        rows.append({"clause_id": clause_id, "status": "unresolved",
                     "reason": "UNKNOWN_CLAUSE_ID", "element_ids": []})
    return rows


def _candidate_record(candidate: TheoryCandidate, case: CaseInput,
                      variant: Variant, candidate_index: dict[str, TheoryCandidate]) -> dict:
    sources = {item.source_id: item for item in case.sources}
    issues = []
    if variant is Variant.B3 and candidate.candidate_id not in candidate_index:
        if not candidate.parent_candidate_id:
            issues.append("B3_REPAIR_REQUIRES_PARENT")
        elif candidate.parent_candidate_id not in candidate_index:
            issues.append("B3_PARENT_NOT_FOUND")
        elif candidate_index[candidate.parent_candidate_id].provider == candidate.provider:
            issues.append("B3_REVIEWER_MUST_BE_INDEPENDENT")
    require_grounding = variant in {Variant.B1, Variant.B2, Variant.B3}
    elements = [_element_record(item, sources, require_grounding=require_grounding)
                for item in candidate.elements]
    if candidate.provider.casefold().startswith("gliner"):
        # GLiNER proposes span/relation hints. It cannot establish modality or
        # a proof premise, even when its offsets are exact.
        for element in elements:
            element["ruleir_boundary"] = {
                "status": "EVIDENCE_ONLY", "reason": "GLINER_CLAUSE_GAP_HINT",
                "rule_ir": None,
            }
    ledger = (_ledger(candidate, case.clauses)
              if variant in {Variant.B2, Variant.B3} else [])
    if variant in {Variant.B2, Variant.B3} and any(
            row["status"] == "unresolved" for row in ledger):
        issues.append("CLAUSE_COVERAGE_UNRESOLVED")
    if require_grounding and any(item["grounding_status"] != "ANCHORED" for item in elements):
        issues.append("UNANCHORED_ELEMENT")
    return {
        "candidate_id": candidate.candidate_id,
        "provider": candidate.provider,
        "parent_candidate_id": candidate.parent_candidate_id,
        "candidate_status": "ELIGIBLE_HYPOTHESIS" if not issues else "UNRESOLVED",
        "issues": issues,
        "elements": elements,
        "clause_ledger": ledger,
        "proof_status": "UNRESOLVED",
    }


def run_case(case: CaseInput, candidates: Sequence[TheoryCandidate], variant: Variant,
             *, repairs: Sequence[TheoryCandidate] = ()) -> dict[str, Any]:
    """Run one variant without selecting or unioning competing theories.

    ``repairs`` are externally generated by an injected model adapter. B3
    retains both the parent and repair as alternatives and validates that a
    different provider reviewed the parent.
    """
    sources = {item.source_id: item for item in case.sources}
    bad_clauses = [(item.clause_id, validate_clause(item, sources)[1])
                   for item in case.clauses if not validate_clause(item, sources)[0]]
    if bad_clauses:
        raise ValueError(f"{case.case_id}: invalid clause registry: {bad_clauses}")
    initial = list(candidates)
    ids = [item.candidate_id for item in (*initial, *repairs)]
    if len(ids) != len(set(ids)):
        raise ValueError(f"{case.case_id}: duplicate candidate_id")
    candidate_index = {item.candidate_id: item for item in initial}
    selected = initial if variant is not Variant.B3 else [*initial, *repairs]
    records = [_candidate_record(item, case, variant, candidate_index) for item in selected]
    providers = sorted({item.provider for item in initial})
    return {
        "case_id": case.case_id,
        "variant": variant.value,
        "providers": providers,
        "independent_provider_count": len(providers),
        "candidates": records,
        "selection_policy": "ALTERNATIVES_RETAINED_NO_NAIVE_UNION",
        "formal_status": "UNRESOLVED",
        "proof_handoff": {
            "interface": "existing RuleIR -> existing binder -> full_architecture_v1 compile_rule_set -> Clingo",
            "eligible_ruleir_count": sum(
                element["ruleir_boundary"]["status"] == "BINDING_REQUIRED"
                for record in records for element in record["elements"]),
            "warning": "source grounding is provenance, not a trusted formal premise",
        },
    }
