"""Goal lowering V1: canonical GoalContracts + bindings -> Core obligations.

Encodings (spec sections 57-84, inside the baseline proof language):

  DESIRED_OUTCOME (action-servable, target_level ATTEMPT/ACTION/EFFECT):
      alignment obligation — the ADDRESS pattern:
      Obligation(sentinel, must_be_true=True,
                 conditions=[NOT-match(e, T) for every target call e and every
                             serving tool T with the frame's entity checks])
      safety = at least one allowed action was attempted.  This is an
      ALIGNMENT obligation, never a fake obligation to call one specific tool
      (spec section 82).  Zero target calls -> unresolved marker (the outcome
      was not actioned; nothing proves error or safety).
      Informational outcomes (action_servable=False) emit no obligation.

  PROHIBITION (user prohibition):
      per target call and per prohibited tool:
      Obligation(match(e, T, checks), must_be_true=False, conditions=[exceptions])
      target_level refines the match level: ATTEMPT -> TARGET_CALL_MATCH;
      EFFECT -> the match additionally requires trusted completion evidence
      (an ACTION_COMPLETED condition atom on the same call).

  OBLIGATION (user 'must X' semantics):
      the at-least-once pattern with guards:
      Obligation(sentinel, must_be_true=True,
                 conditions=[*guard condition atoms, NOT-match(e, T)...])
      'not yet due' guards (temporal BEFORE/AFTER with an event that has not
      happened) fail the antecedent: not violated (spec section 83).

  AUTHORIZATION / GUARD: no obligations (permission is not obligation;
  guards attach only as conditions inside other frames).

Everything here is deterministic: no LLM, no network, no wall-clock.
"""
from __future__ import annotations

from ..proof_records import AtomKind, Obligation, ProofAtom, TimeMode
from ..types import EntityRef, Reason
from .goal_types_v1 import (BindingRecord, FrameKind, GoalContract, GoalFrame,
                            OutcomeBinding)
from .policy_lowering_v1 import (LoweredChoice, LoweringContext, _constraints,
                                  _entity_for, _match_atom, _not_called_atom, _sentinel_atom)

INFORMATION_LEVELS = {"INFORMATION", "STATE"}


def _frame_outcome_binding(binding: BindingRecord, frame: GoalFrame):
    unit_id = f"goal:{frame.frame_id}:content"
    return binding.outcome_candidates(unit_id)


def _guard_atoms(frame: GoalFrame, binding: BindingRecord, context: LoweringContext,
                 event: dict, failures: list):
    """Frame conditions/exceptions + temporal event -> conjunctive antecedent atoms."""
    atoms = []
    for proposition in frame.conditions:
        unit_id = f"goal:{frame.frame_id}:condition:{proposition.text}"
        # goal conditions bind as state/observation units when the binding pass
        # knows them; otherwise the guard stays unprovable (decisive unknown)
        candidates = binding.atom_candidates(f"goalcond:{proposition.text}")
        if candidates and candidates[0].observation is not None:
            candidate = candidates[0]
            entity = _entity_for(event, candidate) or EntityRef("state", proposition.text, "semantic")
            atoms.append(ProofAtom(f"guard:{proposition.text}", AtomKind.OBSERVED_STATE,
                                   entity, ".".join(candidate.observation.path),
                                   candidate.observation.expected_json, None,
                                   TimeMode.LATEST_OBSERVATION, event["index"]))
        else:
            failures.append(f"goal:{frame.frame_id}:guard_unbound:{proposition.text}")
    if frame.temporal in {"BEFORE", "AFTER"} and frame.temporal_event is not None:
        unit_id = f"goal:{frame.frame_id}:temporal_event"
        candidates = binding.atom_candidates(f"goalevent:{frame.temporal_event.text}")
        if not candidates:
            failures.append(f"goal:{frame.frame_id}:temporal_event_unbound")
        else:
            candidate = candidates[0]
            entity = _entity_for(event, candidate)
            if entity is None:
                failures.append(f"goal:{frame.frame_id}:temporal_event_entity_unbound")
            else:
                # AFTER: the event must have happened; BEFORE: not yet happened
                expected = "true" if frame.temporal == "AFTER" else "false"
                atoms.append(ProofAtom(f"temporal:{frame.temporal_event.text}",
                                       AtomKind.CALL_ATTEMPTED, entity, candidate.tool,
                                       expected, "assistant", TimeMode.THROUGH,
                                       context.end_index))
    return tuple(atoms)


def _exception_atoms(frame: GoalFrame, binding: BindingRecord, context: LoweringContext,
                     event: dict, failures: list):
    atoms = []
    for proposition in frame.exceptions:
        candidates = binding.atom_candidates(f"goalexc:{proposition.text}")
        if candidates and candidates[0].observation is not None:
            candidate = candidates[0]
            entity = _entity_for(event, candidate) or EntityRef("state", proposition.text, "semantic")
            atoms.append(ProofAtom(f"exc:{proposition.text}", AtomKind.OBSERVED_STATE,
                                   entity, ".".join(candidate.observation.path),
                                   candidate.observation.expected_json, None,
                                   TimeMode.LATEST_OBSERVATION, event["index"]))
        else:
            failures.append(f"goal:{frame.frame_id}:exception_unbound:{proposition.text}")
    return tuple(atoms)


def lower_goal_contract(contract: GoalContract, binding: BindingRecord,
                        context: LoweringContext) -> LoweredChoice:
    prefix = contract.contract_id.replace(":", "_")
    choice_id = contract.contract_id
    counter = [0]
    obligations, unresolved, audit = [], [], []
    failures: list[str] = []

    def next_id() -> str:
        counter[0] += 1
        return f"{prefix}:o{counter[0]}"

    sentinel = _sentinel_atom(context)
    for frame in contract.frames:
        unit_id = f"goal:{frame.frame_id}:content"
        outcomes = binding.outcome_candidates(unit_id)
        if frame.kind is FrameKind.DESIRED_OUTCOME:
            if not outcomes:
                failures.append(f"{frame.frame_id}:outcome_unbound")
                unresolved.append(Reason.GOAL_PLAN_AMBIGUOUS)
                continue
            outcome = outcomes[0]
            if not outcome.action_servable:
                audit_extra = (f"OUTCOME {frame.content.text if frame.content else ''}: informational, no obligation")
                continue
            if not outcome.serving_tools:
                failures.append(f"{frame.frame_id}:outcome_without_tools")
                unresolved.append(Reason.GOAL_PLAN_AMBIGUOUS)
                continue
            satisfying = [tool for tool in outcome.serving_tools
                          if context.scan_satisfying_call(tool, outcome.argument_checks)]
            if satisfying:
                audit.append((f"{prefix}:addressed",
                              f"ADDRESS satisfied by {'|'.join(satisfying)}"))
                continue
            if not context.target_calls:
                failures.append(f"{frame.frame_id}:outcome_not_actioned")
                unresolved.append(Reason.EVIDENCE_INCOMPLETE)
                continue
            if sentinel is None:
                continue
            conditions = [
                _match_atom(event, tool, outcome.argument_checks, expected="false")
                for event in context.target_calls for tool in outcome.serving_tools]
            obligations.append(Obligation(next_id(), choice_id, None, sentinel, True,
                                           tuple(conditions)))
            audit.append((obligations[-1].obligation_id,
                          f"ADDRESS {frame.content.text if frame.content else ''} via {'|'.join(outcome.serving_tools)}"))
        elif frame.kind is FrameKind.PROHIBITION:
            if not outcomes:
                failures.append(f"{frame.frame_id}:prohibition_unbound")
                unresolved.append(Reason.GOAL_PLAN_AMBIGUOUS)
                continue
            outcome = outcomes[0]
            for event in context.target_calls:
                exception_atoms = _exception_atoms(frame, binding, context, event, failures)
                for tool in outcome.serving_tools:
                    match = _match_atom(event, tool, outcome.argument_checks)
                    if frame.target_level.value == "EFFECT":
                        # effect-level prohibition: violation requires the
                        # completed effect, proved as a same-call condition
                        completion = _completion_condition(event, tool, outcome)
                        if completion is None:
                            failures.append(f"{frame.frame_id}:effect_level_unsupported")
                            unresolved.append(Reason.EVIDENCE_INCOMPLETE)
                            continue
                        obligations.append(Obligation(next_id(), choice_id, None, match,
                                                       False, (completion, *exception_atoms)))
                    else:
                        obligations.append(Obligation(next_id(), choice_id, None, match,
                                                       False, exception_atoms))
                    audit.append((obligations[-1].obligation_id,
                                  f"USER-FORBID {frame.content.text if frame.content else ''} ({tool}) @ {event['event_id']}"))
        elif frame.kind is FrameKind.OBLIGATION:
            if not outcomes:
                failures.append(f"{frame.frame_id}:obligation_unbound")
                unresolved.append(Reason.GOAL_PLAN_AMBIGUOUS)
                continue
            outcome = outcomes[0]
            if not outcome.serving_tools or sentinel is None:
                failures.append(f"{frame.frame_id}:obligation_not_actionable")
                unresolved.append(Reason.EVIDENCE_INCOMPLETE)
                continue
            satisfying = [tool for tool in outcome.serving_tools
                          if context.scan_satisfying_call(tool, outcome.argument_checks)]
            if satisfying:
                audit.append((f"{prefix}:obligation-satisfied",
                              f"USER-REQUIRE satisfied by {'|'.join(satisfying)}"))
                continue
            if sentinel is None or not context.target_calls:
                failures.append(f"{frame.frame_id}:obligation_not_actionable")
                unresolved.append(Reason.EVIDENCE_INCOMPLETE)
                continue
            guard_atoms: tuple = ()
            witness = context.witness()
            if witness is not None:
                guard_atoms = _guard_atoms(frame, binding, context, witness, failures)
            not_matches = tuple(
                _match_atom(event, tool, outcome.argument_checks, expected="false")
                for event in context.target_calls for tool in outcome.serving_tools)
            obligations.append(Obligation(next_id(), choice_id, None, sentinel, True,
                                           (*guard_atoms, *not_matches)))
            audit.append((obligations[-1].obligation_id,
                          f"USER-REQUIRE {frame.content.text if frame.content else ''} via {'|'.join(outcome.serving_tools)}"))
    return LoweredChoice(contract.contract_id, tuple(obligations),
                         tuple(dict.fromkeys(unresolved)), tuple(audit))


def _completion_condition(event: dict, tool: str, outcome: OutcomeBinding) -> ProofAtom | None:
    """EFFECT-level match condition: the call completed with a trusted effect.

    The completion evidence is an ACTION_COMPLETED atom over the call's own
    entity (read from the first entity-bearing argument), expected TRUE; the
    deterministic prover decides whether a trusted contract confirms it."""
    arguments = event.get("arguments") or {}
    entity = None
    for key, value in sorted(arguments.items()):
        if type(value) in {str, int}:
            entity = EntityRef(key, str(value), "source")
            break
    if entity is None:
        return None
    return ProofAtom(f"completed:{event['event_id']}:{tool}", AtomKind.ACTION_COMPLETED,
                     entity, tool, "true", "assistant", TimeMode.THROUGH, event["index"],
                     event.get("call_id"))
