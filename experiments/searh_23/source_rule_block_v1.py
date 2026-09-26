"""A source clause owns scope; its prerequisites cannot override that scope.

Statuses apply only to the supplied interpretation of ONE source clause.
This component never returns a global SAFE/VIOLATION or proves NL coverage.
"""
from __future__ import annotations

from policy_atoms_probe_v1 import FIELDS, optimistic_verdict, source_guard_reason, valid_atom


REQUIREMENT_FIELDS = (set(FIELDS) - {"governs_tool"}) | {"source_quote"}


def evaluate_block(block: dict, source: dict, case: dict) -> dict:
    def result(status: str, reason: str) -> dict:
        return {"status": status, "reason": reason, "global_verdict": "UNKNOWN"}

    if not isinstance(block, dict) or set(block) != {"source_quote", "scope_tools", "requirements"}:
        return result("UNKNOWN", "invalid_block_shape")
    quote, scopes, requirements = (block[k] for k in ("source_quote", "scope_tools", "requirements"))
    if quote != source["policy"]:
        return result("UNKNOWN", "source_clause_changed")
    if (not isinstance(scopes, list) or not scopes or
            not all(isinstance(s, str) and s in source["tools"] for s in scopes)):
        return result("UNKNOWN", "invalid_parent_scope")
    if not isinstance(requirements, list) or not requirements:
        return result("UNKNOWN", "no_prerequisites")
    # Reject a stray child-level governs_tool instead of silently discarding it.
    if any(not isinstance(r, dict) or set(r) != REQUIREMENT_FIELDS for r in requirements):
        return result("UNKNOWN", "child_may_not_define_scope")
    bound = [{**r, "governs_tool": scopes[0]} for r in requirements]
    if not all(valid_atom(a, source) for a in bound):
        return result("UNKNOWN", "invalid_requirement_anchor_or_type")
    guard = source_guard_reason(quote, bound)
    if guard:
        return result("UNKNOWN", guard)
    if case["target_tool"] not in scopes:
        return result("OUT_OF_SCOPE", "this_clause_does_not_constrain_target")
    # Scope is inherited, fixed for every requirement of this source clause.
    for atom in bound:
        atom["governs_tool"] = case["target_tool"]
    verdict = optimistic_verdict(case, bound)
    if verdict == "SAFE":
        return result("RULE_SATISFIED", "all_proposed_prerequisites_satisfied")
    if verdict == "VIOLATION":
        return result("RULE_BROKEN", "a_proposed_prerequisite_is_missing_or_false")
    return result("UNKNOWN", "evidence_unresolved")
