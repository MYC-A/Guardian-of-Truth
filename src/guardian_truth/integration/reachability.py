"""Local valid-next-action proof over the same policy and fact ledger.

Reviewed goals and policy programs are explicitly oracle/structured inputs.
The hypothetical next call is never inserted into history or asserted to
have succeeded. OPEN means a check may resolve an unknown prerequisite;
it is not proof that the requested business action will succeed.
"""
from __future__ import annotations

from dataclasses import dataclass
import json

from guardian_truth.integration.claim_binding import _literal_occurs
from guardian_truth.integration.contracts import acquire_documented
from guardian_truth.integration.proof_engine import ReviewedProgram, check_call
from guardian_truth.step2.result_types import scalar_to_json
from guardian_truth.step2.trusted import producer_scope
from guardian_truth.step2.types import EffectStrength
from guardian_truth.step2.verifier import CallEvent, TrajectoryCase, VerifiedFact


@dataclass(frozen=True)
class ReviewedGoal:
    quote: str
    entity_type: str
    entity_id: str
    predicate: str
    value: object
    candidate_actions_exhaustive: bool
    candidate_calls: tuple[dict, ...]
    evidence_source: str

    def __post_init__(self):
        if self.evidence_source not in {"HUMAN_REVIEWED", "DOC_EXPLICIT", "ENV_TESTED"}:
            raise ValueError("model-proposed goal mapping cannot grant reachability")


def _answer(status: str, reason: str, **details) -> dict:
    return {"status": status, "reason": reason, **details}


def _unknown_atoms(proof: dict):
    if proof.get("status") == "UNKNOWN" and proof.get("reason") == "no_prior_scoped_fact":
        if isinstance(proof.get("atom"), dict):
            yield proof["atom"]
    for child in proof.get("children", ()):
        yield from _unknown_atoms(child)


def _checkable(atom: dict, plan_args: dict, case: TrajectoryCase) -> dict | None:
    """Find an explicitly documented read that can ask the missing question."""
    for binding in acquire_documented(case).bindings:
        if (binding.predicate != atom.get("predicate")
                or binding.entity_type != atom.get("entity_type")
                or binding.strength is not EffectStrength.OBSERVED):
            continue
        tools = [t for t in case.tools
                 if producer_scope(case, t.get("name")) == binding.producer]
        if len(tools) != 1:
            continue
        params = tools[0].get("parameters")
        if not isinstance(params, dict):
            continue
        reverse = {source: target for target, source in atom.get("scope_joins", {}).items()}
        arguments = {}
        valid = True
        for field in params:
            if field == binding.entity_field:
                entity = json.loads(atom["entity_id"])
                arguments[field] = entity
            else:
                target_field = reverse.get(field, field)
                if target_field not in plan_args:
                    valid = False
                    break
                arguments[field] = plan_args[target_field]
        if valid:
            return {"tool": tools[0]["name"], "arguments": arguments,
                    "predicate": binding.predicate,
                    "source": binding.evidence_reference}
    return None


def _plan(goal: ReviewedGoal, plan: dict, position: int,
          programs: tuple[ReviewedProgram, ...], case: TrajectoryCase,
          facts: tuple[VerifiedFact, ...], response_index: int) -> dict:
    if not isinstance(plan, dict) or set(plan) != {"tool", "arguments"}:
        return _answer("UNKNOWN", "plan_shape_invalid")
    tool, args = plan["tool"], plan["arguments"]
    if not isinstance(tool, str) or not isinstance(args, dict):
        return _answer("UNKNOWN", "plan_arguments_invalid")
    catalog = [t for t in case.tools if t.get("name") == tool]
    if len(catalog) != 1:
        return _answer("UNKNOWN", "goal_tool_not_unique_in_catalog")
    params = catalog[0].get("parameters")
    if not isinstance(params, dict) or set(args) != set(params):
        return _answer("UNKNOWN", "plan_parameter_scope_incomplete")
    # The reviewed plan must use only values stated in the user's request.
    for field, value in args.items():
        canonical = scalar_to_json(value)
        if canonical is None:
            return _answer("UNKNOWN", "plan_value_not_scalar")
        literal = str(value).lower() if isinstance(value, bool) else str(value)
        if not _literal_occurs(goal.quote, literal):
            return _answer("UNKNOWN", "plan_argument_not_in_user_goal",
                           field=field)
    producer = producer_scope(case, tool)
    expected = scalar_to_json(goal.value)
    effect_bindings = [b for b in acquire_documented(case).bindings
                       if b.producer == producer and b.predicate == goal.predicate
                       and b.entity_type == goal.entity_type
                       and b.strength is EffectStrength.EXECUTED
                       and expected in b.allowed_values
                       and args.get(b.entity_field) == goal.entity_id]
    if len(effect_bindings) != 1:
        return _answer("UNKNOWN", "goal_effect_contract_unproven")
    scoped_programs = [p for p in programs if p.governed_producer == producer
                       and p.governed_tool == tool]
    if not scoped_programs or not all(p.complete_for_governed_action
                                      for p in scoped_programs):
        return _answer("UNKNOWN", "policy_for_candidate_incomplete")
    fake = CallEvent(response_index, f"hypothetical:{position}", tool, args)
    proofs = [check_call(p, case, fake, facts, hypothetical=True)
              for p in scoped_programs]
    statuses = {p["status"] for p in proofs}
    trace = {"hypothetical_call": {"tool": tool, "arguments": args,
                                    "index": response_index},
             "effect_contracts": [b.evidence_reference for b in effect_bindings],
             "policy_proofs": proofs}
    if "VIOLATION" in statuses:
        return _answer("BLOCKED", "explicit_policy_condition_false", **trace)
    if all(p["status"] == "SATISFIED"
           or (p["status"] == "NOT_APPLICABLE" and p["reason"] == "activation_false")
           for p in proofs):
        return _answer("LEGAL_NEXT_ACTION", "scoped_prerequisites_proven", **trace)
    checks = [check for proof in proofs for atom in _unknown_atoms(proof)
              if (check := _checkable(atom, args, case)) is not None]
    if checks:
        return _answer("CHECKABLE", "unknown_gate_has_read_action",
                       checking_actions=checks, **trace)
    return _answer("UNKNOWN", "candidate_policy_unresolved", **trace)


def assess_local_reachability(user_request: str, response: str,
                              response_index: int, goal: ReviewedGoal,
                              programs: tuple[ReviewedProgram, ...],
                              case: TrajectoryCase,
                              facts: tuple[VerifiedFact, ...],
                              *, catalog_complete: bool) -> dict:
    """Prove one legal next action, a local closure, or a checkable open gate."""
    if goal.quote != user_request or not goal.quote or not goal.candidate_actions_exhaustive:
        return _answer("UNKNOWN", "goal_source_or_completeness_unverified")
    if not catalog_complete:
        return _answer("UNKNOWN", "catalog_incomplete")
    if response_index <= max((e.index for e in (*case.calls, *case.results)), default=-1):
        return _answer("UNKNOWN", "response_time_not_after_history")
    if not goal.candidate_calls:
        return _answer("CLOSED", "complete_catalog_no_goal_capability",
                       goal_source=goal.quote, plans=[])
    plans = [_plan(goal, p, i, programs, case, facts, response_index)
             for i, p in enumerate(goal.candidate_calls)]
    statuses = [p["status"] for p in plans]
    if "LEGAL_NEXT_ACTION" in statuses:
        return _answer("REACHABLE", "verified_legal_next_action",
                       goal_source=goal.quote, plans=plans)
    if all(status == "BLOCKED" for status in statuses):
        return _answer("CLOSED", "all_reviewed_actions_explicitly_blocked",
                       goal_source=goal.quote, plans=plans)
    if "CHECKABLE" in statuses and not any(status == "UNKNOWN" for status in statuses):
        return _answer("OPEN", "information_action_can_resolve_gate",
                       goal_source=goal.quote, plans=plans)
    return _answer("UNKNOWN", "no_complete_reachability_proof",
                   goal_source=goal.quote, plans=plans)


def decide_refusal(response: str, refusal: dict, reachability: dict) -> dict:
    if (not isinstance(refusal, dict)
            or refusal.get("evidence_source") not in
            {"HUMAN_REVIEWED", "DOC_EXPLICIT", "ENV_TESTED"}
            or refusal.get("quote") != response
            or refusal.get("absolute_inability") is not True):
        return _answer("UNKNOWN", "refusal_interpretation_unverified",
                       reachability=reachability)
    status = reachability["status"]
    if status == "REACHABLE":
        return _answer("ERROR", "absolute_refusal_contradicts_reachable_next_action",
                       reachability=reachability)
    if status == "CLOSED":
        return _answer("NO_ERROR", "all_reviewed_goal_paths_closed_now",
                       reachability=reachability)
    return _answer("UNKNOWN", "goal_path_not_decided", reachability=reachability)
