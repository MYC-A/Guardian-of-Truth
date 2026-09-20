"""Validated two-author B3 critique and repair cycle.

The cycle is deliberately append-only: original theories are never edited,
criticism cannot delete an element, and every repair remains an alternative.
"""

from __future__ import annotations

from dataclasses import asdict
from typing import Any, Sequence

from .contracts import (CaseInput, CritiqueProblem, TheoryCandidate, TheoryCritique,
                        Variant)
from .grounding import validate_link
from .orchestrator import run_case


def _element_payload(element) -> dict:
    """Return the semantic fields used by the preservation invariant."""
    return {
        "interpretation": element.interpretation,
        "source_links": [asdict(link) for link in element.source_links],
        "rule_ir": element.rule_ir,
        "unresolved_components": list(element.unresolved_components),
    }


def _validate_critiques(case: CaseInput, originals: Sequence[TheoryCandidate],
                        critiques: Sequence[TheoryCritique]) -> tuple[list[dict], list[str]]:
    sources = {item.source_id: item for item in case.sources}
    original_index = {item.candidate_id: item for item in originals}
    records, global_issues = [], []
    directions = set()
    for critique in critiques:
        issues = []
        target = original_index.get(critique.target_candidate_id)
        if target is None:
            issues.append("CRITIQUE_TARGET_NOT_ORIGINAL")
        else:
            if critique.reviewer_provider == target.provider:
                issues.append("CRITIQUE_MUST_BE_CROSS_PROVIDER")
            directions.add((critique.reviewer_provider, target.provider))
            element_ids = {item.element_id for item in target.elements}
            for item in critique.issues:
                theory_level = (item.target_element_id == "__theory__" and
                                item.problem_type in {CritiqueProblem.MISSING_CONDITION,
                                                      CritiqueProblem.MISSING_EXCEPTION,
                                                      CritiqueProblem.OTHER})
                if item.target_element_id not in element_ids and not theory_level:
                    issues.append(f"{item.issue_id}:UNKNOWN_TARGET_ELEMENT")
                valid, reason = validate_link(item.source_link, sources)
                if not valid:
                    issues.append(f"{item.issue_id}:{reason}")
        records.append({
            "critique_id": critique.critique_id,
            "reviewer_provider": critique.reviewer_provider,
            "target_candidate_id": critique.target_candidate_id,
            "issues": [{**asdict(item), "problem_type": item.problem_type.value}
                       for item in critique.issues],
            "unresolved": list(critique.unresolved),
            "outcome": "NO_ISSUES_FOUND" if not critique.issues else "ISSUES_FOUND",
            "validation_issues": issues,
            "status": "VALID_GROUNDED_CRITIQUE" if not issues else "UNRESOLVED",
        })
    providers = {item.provider for item in originals}
    if len(originals) != 2 or len(providers) != 2:
        global_issues.append("B3_REQUIRES_TWO_INDEPENDENT_ORIGINAL_THEORIES")
    else:
        expected = {(reviewer, target) for reviewer in providers for target in providers
                    if reviewer != target}
        if not expected <= directions:
            global_issues.append("B3_MISSING_BIDIRECTIONAL_CROSS_CRITIQUE")
    if any(row["validation_issues"] for row in records):
        global_issues.append("B3_HAS_INVALID_CRITIQUE")
    return records, global_issues


def _repair_diff(parent: TheoryCandidate, repair: TheoryCandidate,
                 targeted_ids: set[str]) -> dict:
    before = {item.element_id: item for item in parent.elements}
    after = {item.element_id: item for item in repair.elements}
    removed = sorted(set(before) - set(after))
    added = sorted(set(after) - set(before))
    changed = sorted(item_id for item_id in set(before) & set(after)
                     if _element_payload(before[item_id]) != _element_payload(after[item_id]))
    unauthorized = sorted(set(changed) - targeted_ids)
    parent_accounts = {item.clause_id: asdict(item) for item in parent.clause_accounts}
    repair_accounts = {item.clause_id: asdict(item) for item in repair.clause_accounts}
    accounts_removed = sorted(set(parent_accounts) - set(repair_accounts))
    violations = []
    if removed:
        violations.append("REPAIR_REMOVED_PARENT_ELEMENT")
    if unauthorized:
        violations.append("REPAIR_CHANGED_UNCRITIQUED_ELEMENT")
    if accounts_removed:
        violations.append("REPAIR_REMOVED_CLAUSE_ACCOUNT")
    return {
        "parent_candidate_id": parent.candidate_id,
        "repair_candidate_id": repair.candidate_id,
        "retained_element_ids": sorted(set(before) & set(after)),
        "changed_element_ids": changed,
        "added_element_ids": added,
        "removed_element_ids": removed,
        "unauthorized_changed_element_ids": unauthorized,
        "removed_clause_accounts": accounts_removed,
        "invariant_violations": violations,
        "status": "PRESERVATION_CHECK_PASSED" if not violations else "UNRESOLVED",
    }


def run_b3_cycle(case: CaseInput, originals: Sequence[TheoryCandidate],
                 critiques: Sequence[TheoryCritique],
                 repairs: Sequence[TheoryCandidate], *,
                 gap_evidence: Sequence[dict[str, Any]] = ()) -> dict[str, Any]:
    """Run B3 while retaining originals, critiques, repairs and unresolved facts."""
    critique_records, cycle_issues = _validate_critiques(case, originals, critiques)
    original_index = {item.candidate_id: item for item in originals}
    target_issue_ids: dict[str, set[str]] = {}
    valid_critique_targets = set()
    for critique, record in zip(critiques, critique_records):
        if record["status"] == "VALID_GROUNDED_CRITIQUE":
            valid_critique_targets.add(critique.target_candidate_id)
            target_issue_ids.setdefault(critique.target_candidate_id, set()).update(
                item.target_element_id for item in critique.issues
                if item.target_element_id != "__theory__")
    repair_diffs = []
    seen_parents = set()
    for repair in repairs:
        parent = original_index.get(repair.parent_candidate_id or "")
        if parent is None:
            repair_diffs.append({"parent_candidate_id": repair.parent_candidate_id,
                                 "repair_candidate_id": repair.candidate_id,
                                 "invariant_violations": ["REPAIR_PARENT_NOT_ORIGINAL"],
                                 "status": "UNRESOLVED"})
            continue
        seen_parents.add(parent.candidate_id)
        diff = _repair_diff(parent, repair, target_issue_ids.get(parent.candidate_id, set()))
        if parent.candidate_id not in valid_critique_targets:
            diff["invariant_violations"].append("REPAIR_LACKS_VALID_GROUNDED_CROSS_CRITIQUE")
            diff["status"] = "UNRESOLVED"
        if repair.provider != parent.provider:
            diff["invariant_violations"].append("REPAIR_AUTHOR_MUST_MATCH_PARENT_AUTHOR")
            diff["status"] = "UNRESOLVED"
        repair_diffs.append(diff)
    required_repairs = {target for target, ids in target_issue_ids.items() if ids}
    required_repairs.update(
        critique.target_candidate_id for critique, record in zip(critiques, critique_records)
        if record["status"] == "VALID_GROUNDED_CRITIQUE" and any(
            item.target_element_id == "__theory__" for item in critique.issues))
    missing_repairs = sorted(required_repairs - seen_parents)
    if missing_repairs:
        cycle_issues.append("B3_MISSING_SEPARATE_AUTHOR_REPAIR")
    if any(item["status"] != "PRESERVATION_CHECK_PASSED" for item in repair_diffs):
        cycle_issues.append("B3_REPAIR_INVARIANT_FAILED")

    result = run_case(case, originals, Variant.B3, repairs=repairs)
    diff_by_repair = {item["repair_candidate_id"]: item for item in repair_diffs}
    original_ids = set(original_index)
    for alternative in result["candidates"]:
        alternative["alternative_kind"] = (
            "ORIGINAL" if alternative["candidate_id"] in original_ids else "REPAIR")
        alternative["critique_ids"] = [row["critique_id"] for row in critique_records
                                       if row["target_candidate_id"] ==
                                       (alternative.get("parent_candidate_id") or
                                        alternative["candidate_id"])]
        diff = diff_by_repair.get(alternative["candidate_id"])
        if diff and diff["status"] != "PRESERVATION_CHECK_PASSED":
            alternative["issues"].extend(diff["invariant_violations"])
            alternative["candidate_status"] = "UNRESOLVED"
    result.update({
        "cycle_status": "READY_FOR_FORMAL_HANDOFF" if not cycle_issues else "UNRESOLVED",
        "cycle_issues": cycle_issues,
        "critiques": critique_records,
        "original_theories": [asdict(item) for item in originals],
        "repair_theories": [asdict(item) for item in repairs],
        "repair_diffs": repair_diffs,
        "unresolved": sorted({item for critique in critiques for item in critique.unresolved}),
        "gap_evidence": list(gap_evidence),
        "preservation_policy": "ORIGINALS_IMMUTABLE_NO_DELETION_NO_AUTOMATIC_MERGE",
    })
    return result
