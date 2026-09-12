"""Deterministic source/binding checks shared by Goal solver and checker."""

import json

from .goal_native import GoalOperator, source_inventory
from .goal_progress_v2 import PlanProgressAtom, PlanProgressKind, prove_plan_progress
from .integrity import canonical
from .normalize import normalize
from .proof_evidence import effect_is_verified
from .proof_records import AtomKind, TimeMode
from .ledger import LedgerIndex
from .types import CoverageStatus, Truth


def goal_context_errors(context, ledger, registry):
    errors = []
    try:
        scope = json.loads(context.allowed_scope_json)
        if not isinstance(scope, dict) or canonical(scope).decode("utf-8") != context.allowed_scope_json:
            return ("INVALID_DECLARED_SCOPE",)
        text, sources = source_inventory(context.declared_goal, context.ordered_plan, scope)
    except (ValueError, TypeError):
        return ("INVALID_DECLARED_SOURCES",)
    parsed = context.parsed
    if parsed.source_text != text or parsed.sources != sources:
        errors.append("GOAL_SOURCE_RECONSTRUCTION_FAILED")
    if normalize(context.prompt, context.response, tool_identities=context.tool_metadata) != ledger.events:
        errors.append("LEDGER_SOURCE_RECONSTRUCTION_FAILED")
    if (not context.candidate_basis or context.candidate_enumeration_complete is not True
            or parsed.failures or parsed.coverage.status is not CoverageStatus.EMPIRICALLY_COVERED
            or parsed.coverage.enumeration_complete or parsed.coverage.universe_source
            or parsed.coverage.unresolved_terms or parsed.coverage.discarded_hypotheses):
        errors.append("GOAL_CANDIDATES_INCOMPLETE_OR_UNSUPPORTED_CLOSURE")
    readings = {reading.reading_id: reading for reading in parsed.readings}
    if not readings or len(readings) != len(parsed.readings):
        errors.append("DUPLICATED_OR_MISSING_READING")
    choices = {choice.choice_id: choice for choice in context.choices}
    if (not choices or any(not choice.choice_id for choice in context.choices) or len(choices) != len(context.choices)
            or {choice.reading_id for choice in context.choices} != set(readings)):
        errors.append("BINDING_CANDIDATE_SPACE_INCOMPLETE_OR_DUPLICATED")
    by_source = {source.source_id: source for source in sources}
    targets = [event for event in ledger.events if event.source.document == "response" and event.kind == "call"]
    target = targets[0] if len(targets) == 1 else None
    index = LedgerIndex(ledger)
    catalog = {identity.name for identity in context.tool_metadata} | {event.tool.name for event in ledger.events if event.tool}
    for reading in readings.values():
        if (reading.unknown_fields or not reading.basis.strip() or not reading.source_ids or any(sid not in by_source for sid in reading.source_ids)
                or reading.declared_goal_source not in by_source
                or by_source[reading.declared_goal_source].kind != "GOAL"):
            errors.append("UNGROUNDED_OR_UNKNOWN_READING")
        if (reading.expected_step is None or type(reading.expected_step) is not int
                or not 0 <= reading.expected_step <= len(context.ordered_plan)
                or reading.expected_action_source != (f"plan:{reading.expected_step}"
                    if reading.expected_step < len(context.ordered_plan) else None)
                or reading.actor not in {"assistant", "user", "entity"}):
            errors.append("READING_STEP_ACTION_OR_ACTOR_CONFLICT")
        structural = []
        plan_ids = [source.source_id for source in sources if source.kind == "PLAN_STEP"]
        scope_ids = [source.source_id for source in sources if source.kind == "SCOPE"]
        structural += [(GoalOperator.PLAN_STEP, (sid,), (sid,)) for sid in plan_ids]
        structural += [(GoalOperator.BEFORE, pair, pair) for pair in zip(plan_ids, plan_ids[1:])]
        structural += [(GoalOperator.SCOPE, (sid,), (sid,)) for sid in scope_ids]
        actual = [(clause.operator, clause.source_ids, clause.operands) for clause in reading.clauses
                  if any(clause.clause_id.startswith(reading.reading_id + suffix)
                         for suffix in (":step:", ":order:", ":scope:"))]
        if actual != structural or len({clause.clause_id for clause in reading.clauses}) != len(reading.clauses):
            errors.append("PLAN_ORDER_OR_SCOPE_CLAUSES_DROPPED_OR_CHANGED")
        if any(clause.reading_id != reading.reading_id or not clause.source_ids
                or any(sid not in by_source for sid in (*clause.source_ids, *clause.operands))
                or clause.unresolved_terms for clause in reading.clauses):
            errors.append("UNGROUNDED_OR_UNRESOLVED_CLAUSE")
    for choice in context.choices:
        reading = readings.get(choice.reading_id)
        if reading is None:
            continue
        bound = {(binding.source_id, binding.role): binding for binding in choice.bindings}
        if len(bound) != len(choice.bindings):
            errors.append("DUPLICATED_ROLE_BINDING")
        for binding in choice.bindings:
            source = by_source.get(binding.source_id)
            atom = binding.atom
            if (source is None or not binding.meaning_source_ids
                    or binding.source_id not in binding.meaning_source_ids
                    or any(sid not in by_source for sid in binding.meaning_source_ids)):
                errors.append("UNGROUNDED_BINDING_MEANING")
                continue
            if isinstance(atom, PlanProgressAtom):
                expected_kind = {"active_step": PlanProgressKind.ACTIVE_STEP, "prior_completion": PlanProgressKind.COMPLETED_STEP}.get(binding.role)
                if (atom.kind is not expected_kind or atom.source_id != binding.source_id or atom.actor != reading.actor
                        or prove_plan_progress(atom, context, ledger).value is Truth.UNKNOWN):
                    errors.append("PLAN_PROGRESS_NOT_ESTABLISHED")
                continue
            if atom.kind is AtomKind.TARGET_CALL_MATCH and atom.predicate not in catalog:
                errors.append("UNDECLARED_INVOCATION_INTERFACE")
            if binding.role in {"scope_applicable", "scope_compliant", "current_attempt", "step_satisfied"}:
                if (target is None or atom.kind is not AtomKind.TARGET_CALL_MATCH
                        or atom.time_mode is not TimeMode.AT or atom.time_index != target.index
                        or atom.actor != reading.actor or atom.expected_json != "true"
                        or atom.call_id != target.call_id):
                    errors.append("TARGET_INVOCATION_BINDING_MISMATCH")
            if binding.role == "scope_applicable":
                if source.kind != "SCOPE" or atom.argument_constraints:
                    errors.append("INVALID_SCOPE_APPLICABILITY")
            if binding.role == "scope_compliant":
                applicable = bound.get((binding.source_id, "scope_applicable"))
                if (source.kind != "SCOPE" or len(atom.argument_constraints) != 1
                        or set(atom.argument_constraints[0].allowed_json) != set(source.allowed_json)
                        or applicable is None
                        or (atom.predicate, atom.actor, atom.time_index, atom.call_id)
                        != (applicable.atom.predicate, applicable.atom.actor, applicable.atom.time_index, applicable.atom.call_id)):
                    errors.append("LITERAL_SCOPE_BINDING_MISMATCH")
            if binding.role == "active_step":
                # A reported field alone cannot establish real plan progress.
                # Require a matching regenerated authoritative effect premise.
                if (source.kind != "PLAN_STEP" or atom.kind is not AtomKind.OBSERVED_STATE
                        or atom.expected_json != canonical(source.plan_index).decode("utf-8")
                        or target is None or atom.time_index >= target.index
                        or not any(effect.entity == atom.entity and effect.predicate == atom.predicate
                            and effect.value_json == atom.expected_json
                            and index.positions[effect.event_id] <= atom.time_index
                            and effect_is_verified(effect, ledger, index, registry) for effect in ledger.effects)):
                    errors.append("PLAN_PROGRESS_NOT_ESTABLISHED")
            if binding.role == "prior_completion":
                if (source.kind != "PLAN_STEP" or atom.actor != reading.actor
                        or atom.kind not in {AtomKind.ACTION_COMPLETED, AtomKind.HISTORICAL_ACTION}):
                    errors.append("PRIOR_STEP_IS_NOT_MATCHING_COMPLETION")
    return tuple(dict.fromkeys(errors))
