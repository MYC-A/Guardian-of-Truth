"""Single conservative proof path over reviewed programs and candidate claims.

This layer does not promote a model policy, tool contract, claim, or goal into a
trusted input. Callers must declare coverage of the reviewed scopes. One proven
ERROR is sufficient; NO_ERROR requires every declared scope to be discharged.
"""
from __future__ import annotations

from guardian_truth.integration.automatic_claims import compile_candidate_claims
from guardian_truth.integration.contracts import facts_from_documented
from guardian_truth.integration.proof_engine import (
    ReviewedProgram, check_call, check_claim, decide_reviewed)
from guardian_truth.integration.reachability import (
    ReviewedGoal, assess_local_reachability, decide_refusal)
from guardian_truth.step2.verifier import TrajectoryCase


def analyze_system_case(
    case: TrajectoryCase,
    *,
    response: str,
    response_index: int,
    programs: tuple[ReviewedProgram, ...] = (),
    reviewed_policy_scope_complete: bool = False,
    candidate_claim_raw: str | None = None,
    reviewed_goal: ReviewedGoal | None = None,
    reviewed_refusal: dict | None = None,
    reviewed_non_refusal: bool = False,
    user_request: str = "",
    catalog_complete: bool = False,
) -> dict:
    """Return a traceable verdict; all coverage flags are explicit oracle inputs.

    A reviewed goal/refusal enables the Step 4 branch. For ordinary replies,
    `reviewed_non_refusal` must be independently certified before NO_ERROR is
    possible. Missing policy/claim/refusal coverage gives UNKNOWN, not success.
    """
    facts, assessments, acquisition_issues = facts_from_documented(case)
    compiled = (compile_candidate_claims(response, response_index, case,
                                         candidate_claim_raw)
                if candidate_claim_raw is not None else None)
    action_proofs = tuple(
        check_call(program, case, call, tuple(facts))
        for program in programs for call in case.calls
        if call.tool == program.governed_tool and call.index < response_index
    )
    claim_proofs = tuple(
        check_claim(query, case, tuple(facts)) for query in compiled.queries
    ) if compiled is not None else ()
    policy_complete = (bool(programs) and reviewed_policy_scope_complete
                       and all(p.complete_for_governed_action for p in programs))
    reviewed = decide_reviewed(
        action_proofs, claim_proofs, policy_complete=policy_complete,
        claim_inventory_complete=(compiled.inventory_complete
                                  if compiled is not None else False))

    reachability = None
    if reviewed_goal is not None and reviewed_refusal is not None:
        reachability = assess_local_reachability(
            user_request, response, response_index, reviewed_goal, programs,
            case, tuple(facts), catalog_complete=catalog_complete)
        refusal = decide_refusal(response, reviewed_refusal, reachability)
    elif reviewed_non_refusal and reviewed_goal is None and reviewed_refusal is None:
        refusal = {"status": "NOT_APPLICABLE", "reason": "reviewed_non_refusal"}
    else:
        refusal = {"status": "UNKNOWN", "reason": "refusal_scope_unreviewed"}

    if "ERROR" in {reviewed["status"], refusal["status"]}:
        status, reason = "ERROR", "one_reviewed_proof_path_failed"
    elif (reviewed["status"] == "NO_ERROR"
          and refusal["status"] in {"NO_ERROR", "NOT_APPLICABLE"}):
        status, reason = "NO_ERROR", "all_reviewed_scopes_discharged"
    else:
        status, reason = "UNKNOWN", "system_proof_path_incomplete"
    return {
        "status": status, "reason": reason,
        "policy": {"program_count": len(programs),
                   "reviewed_scope_complete": policy_complete,
                   "action_proofs": action_proofs},
        "world": {"verified_fact_count": len(facts),
                  "acquisition_issues": acquisition_issues,
                  "assessment_issues": [a.issues for a in assessments if a.issues]},
        "claims": {"inventory_complete": (compiled.inventory_complete
                                          if compiled is not None else False),
                   "queries": [q.__dict__ for q in compiled.queries]
                   if compiled is not None else [],
                   "issues": compiled.issues if compiled is not None else
                   ("claim_extraction_absent",),
                   "proofs": claim_proofs},
        "reachability": reachability, "reviewed_branch": reviewed,
        "refusal_branch": refusal,
    }
