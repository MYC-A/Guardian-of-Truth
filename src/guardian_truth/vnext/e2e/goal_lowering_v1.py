"""Goal lowering (PASS 2): goal contracts -> CompiledRules -> reading options.

The goal axis choices are the goal readings (Conservative / Rule Frames after
deterministic equivalence dedupe). AUTHORIZATION alternatives become
DisjunctiveGroups: per target call, OR over the explicitly allowed
alternatives (allowed alternatives are NOT an instruction to execute all of
them, spec 59). The goal normative text carries the merged explicit scope
suffix so every allowed literal is textually grounded for the operational
binding (the same mechanism the baseline core uses for EXPLICIT_ALLOWED_SCOPE).

Cycle-3 alternative_groups semantics (B2): authorization is not obligation.
* Every binding choice of every allowed alternative contributes its atoms to
  ONE per-call disjunctive group (binding ambiguity is absorbed by the
  disjunction, never by dropping an alternative and degenerating the group).
* A goal REQUIRE rule whose operational binding yields MULTIPLE choices
  lowers into ONE satisfaction group: the goal is satisfied when ANY bound
  alternative operationalization holds (OR over conjunctions), never into
  independent per-choice world obligations (REQUIRE A AND REQUIRE B).
"""

from __future__ import annotations

import json
from itertools import product

from ..grounding import bind_evaluation_hypothesis
from ..integrity import canonical
from ..policy import quote_spans
from ..proof_records import ArgumentConstraint, AtomKind, ProofAtom, TimeMode
from ..types import EntityRef, EvaluationHypothesis
from .e2e_types_v1 import (CompiledRule, DisjunctiveGroup, E2ESemantics, FULL_SEMANTICS,
                           GoalContract, ReadingOption, UnresolvedMarker)
from .goal_composition_v1 import compile_goal_contract
from .policy_lowering_v1 import (LoweredReading, _existential_obligation, _raw_scope,
                                  _rule_conditions_atoms, _grounded_hypothesis, rule_side_spec)

GOAL_LOWERING_VERSION = "goal_lowering_e2e_v1"

def merged_scope(rules) -> dict:
    merged = {}
    for rule in rules:
        for field_name, values in (_raw_scope(rule) or {}).items():
            merged.setdefault(field_name, [])
            for value in values:
                if value not in merged[field_name]:
                    merged[field_name].append(value)
    return merged


def goal_normative_text(user_request: str, rules) -> str:
    scope = merged_scope(rules)
    text_value = user_request
    if scope:
        text_value = text_value + "\nEXPLICIT_ALLOWED_SCOPE=" + canonical(dict(sorted(scope.items()))).decode("utf-8")
    return text_value


def _bind(rule: CompiledRule, normative_text: str, backend, ledger, tool_catalog, action_key=None):
    hypothesis = _grounded_hypothesis(rule, "goal_plan", normative_text, action_key=action_key)
    binding = bind_evaluation_hypothesis(hypothesis, backend, normative_text=normative_text,
                                         ledger=ledger, tool_catalog=tuple(tool_catalog),
                                         allowed_scope=_raw_scope(rule))
    return hypothesis, binding


def _alternative_group(rule: CompiledRule, normative_text: str, backend, ledger, tool_catalog,
                       target_calls, lowered: LoweredReading, semantics: E2ESemantics):
    """GOAL_ALTERNATIVES: OR over allowed alternatives per target call."""
    per_call = {}
    markers = []
    for alt_index, alternative in enumerate(rule.alternatives or (rule.action_key,)):
        alt_rule = CompiledRule(rule.rule_id + f":alt{alt_index}", "GOAL_CALL", rule.modality, alternative,
                                rule.actor, rule.relation, (), (), rule.scope, rule.source_quotes, (), "goal")
        hypothesis, binding = _bind(alt_rule, normative_text, backend, ledger, tool_catalog)
        lowered.hypotheses = lowered.hypotheses + (hypothesis,)
        lowered.hypothesis_scopes[hypothesis.hypothesis_id] = _raw_scope(alt_rule) or {}
        if not binding.choices:
            markers.append(UnresolvedMarker(f"{rule.rule_id}:alt{alt_index}:binding",
                                            "alternative binding ambiguous or unresolved"))
            continue
        if len(binding.choices) != 1 and not semantics.alternative_groups:
            markers.append(UnresolvedMarker(f"{rule.rule_id}:alt{alt_index}:binding",
                                            "alternative binding ambiguous or unresolved"))
            continue
        # alternative_groups: EVERY binding choice of the alternative
        # contributes its atoms; the group disjunction absorbs binding
        # ambiguity instead of dropping the alternative (a dropped
        # alternative degenerated the group into a single FALSE atom).
        for choice in binding.choices:
            lowered.choices = lowered.choices + (choice,)
            lowered.choice_rules[choice.choice_id] = rule_side_spec(alt_rule)
            for atom in choice.atoms:
                event = next((call for call in target_calls if call.event_id == atom.entity.value), None)
                if event is not None:
                    per_call.setdefault(event.event_id, []).append(atom)
    if rule.conditions or rule.exceptions:
        markers.append(UnresolvedMarker(f"{rule.rule_id}:conditions",
                                        "conditions on alternatives not expressible in V1"))
    for term in rule.unresolved_terms:
        markers.append(UnresolvedMarker(f"{rule.rule_id}:term:{term}", "rule unresolved term"))
    group = DisjunctiveGroup(f"{rule.rule_id}:group0", rule.rule_id, True,
                             tuple((event_id, tuple(atoms)) for event_id, atoms in sorted(per_call.items())))
    return group, markers


def lower_goal_contract(contract: GoalContract, *, user_request: str, state_contract: dict | None,
                        backend, ledger, tool_catalog, target_calls,
                        normative_text: str | None = None,
                        semantics: E2ESemantics = FULL_SEMANTICS) -> LoweredReading:
    rules, unresolved = compile_goal_contract(contract, state_contract)
    lowered = LoweredReading(rules=rules)
    if normative_text is None:
        normative_text = goal_normative_text(user_request, rules)
    authorized_alternatives = sorted({alternative for other in rules
                                      if other.kind == "GOAL_ALTERNATIVES"
                                      for alternative in other.alternatives})
    per_rule_alternatives = []
    for rule in rules:
        if rule.kind == "GOAL_ALTERNATIVES":
            group, markers = _alternative_group(rule, normative_text, backend, ledger, tool_catalog,
                                                target_calls, lowered, semantics)
            per_rule_alternatives.append([(((), (group,), tuple(markers)))])
            continue
        if rule.kind == "PERMIT" or not rule.action_key:
            per_rule_alternatives.append([((), (), ())])
            continue
        hypothesis, binding = _bind(rule, normative_text, backend, ledger, tool_catalog)
        lowered.hypotheses = lowered.hypotheses + (hypothesis,)
        lowered.hypothesis_scopes[hypothesis.hypothesis_id] = _raw_scope(rule) or {}
        extra_markers = tuple(UnresolvedMarker(f"{rule.rule_id}:term:{term}", "rule unresolved term")
                              for term in rule.unresolved_terms)
        if rule.kind == "REQUIRE_CALL":
            obligation = _existential_obligation(rule, hypothesis, len(ledger.events) - 1)
            lowered.direct_rules[hypothesis.hypothesis_id] = {"rule_kind": rule.kind}
            per_rule_alternatives.append([((obligation,), (), extra_markers)])
            continue
        if not target_calls:
            per_rule_alternatives.append([((), (), extra_markers)])
            continue
        if not binding.choices:
            reasons = ";".join(sorted({str(reason.value) for reason in binding.failures}
                                      | {detail for _, detail in binding.discarded}))
            marker = UnresolvedMarker(f"{rule.rule_id}:binding", "operational binding unresolved: " + reasons)
            per_rule_alternatives.append([((), (), (marker,) + extra_markers)])
            continue
        if (semantics.alternative_groups and rule.modality == "REQUIRE"
                and (len(binding.choices) > 1 or authorized_alternatives)
                and all(choice.must_be_true for choice in binding.choices)):
            # ONE satisfaction group: the goal is satisfied by ANY bound
            # alternative operationalization, extended with the explicitly
            # AUTHORIZED alternative tools of the same request (the user's own
            # ANY_OF words, never an invented reading). Authorization
            # alternatives are never independent obligations.
            satisfaction = []
            for choice in binding.choices:
                lowered.choices = lowered.choices + (choice,)
                lowered.choice_rules[choice.choice_id] = rule_side_spec(rule)
                atoms = tuple(atom for atom in choice.atoms
                              if any(call.event_id == atom.entity.value for call in target_calls))
                satisfaction.append(atoms)
            for alternative in authorized_alternatives:
                for event in target_calls:
                    constraints = tuple(ArgumentConstraint((field_name,), tuple(values))
                                        for field_name, values in rule.scope)
                    alt_atom = ProofAtom(f"{rule.rule_id}:authalt:{alternative}:{event.event_id}",
                                         AtomKind.TARGET_CALL_MATCH,
                                         EntityRef("event_id", event.event_id, "ledger"),
                                         alternative, "true", "assistant", TimeMode.AT,
                                         event.index, call_id=event.call_id,
                                         argument_constraints=constraints)
                    satisfaction.append((alt_atom,))
            if any(atoms for atoms in satisfaction):
                group = DisjunctiveGroup(f"{rule.rule_id}:satisfaction", rule.rule_id, True, (),
                                        tuple(satisfaction))
                per_rule_alternatives.append([(((), (group,), extra_markers))])
                continue
        alternatives = []
        for choice in binding.choices:
            lowered.choices = lowered.choices + (choice,)
            lowered.choice_rules[choice.choice_id] = rule_side_spec(rule)
            obligations = []
            for i, atom in enumerate(choice.atoms):
                event = next((call for call in target_calls if call.event_id == atom.entity.value), None)
                if event is None:
                    continue
                conditions = _rule_conditions_atoms(rule, event)
                if rule.kind == "REQUIRE_PRESERVE":
                    tool_match = ProofAtom(f"{rule.rule_id}:toolmatch:{event.event_id}",
                                           AtomKind.TARGET_CALL_MATCH, EntityRef("event_id", event.event_id, "ledger"),
                                           atom.predicate, "true", "assistant", TimeMode.AT, event.index,
                                           call_id=atom.call_id)
                    conditions = (tool_match,) + conditions
                from ..proof_records import Obligation
                obligations.append(Obligation(f"{choice.choice_id}:o{i}", choice.choice_id, None, atom,
                                              choice.must_be_true, conditions))
            alternatives.append((tuple(obligations), (), extra_markers))
        per_rule_alternatives.append(alternatives)
    contract_markers = tuple(UnresolvedMarker(f"{contract.contract_id}:term:{term}", "contract unresolved term")
                             for term in unresolved)
    options = []
    if per_rule_alternatives:
        for combo_index, combo in enumerate(product(*per_rule_alternatives)):
            obligations, groups, markers = [], [], list(contract_markers)
            for obs, grp, mrk in combo:
                obligations.extend(obs)
                groups.extend(grp)
                markers.extend(mrk)
            options.append(ReadingOption(f"{contract.contract_id}#{combo_index}", tuple(obligations),
                                          tuple(groups), tuple(dict.fromkeys(markers))))
    if not options:
        options = [ReadingOption(contract.contract_id + "#0", (), (), contract_markers)]
    for option in options:
        rules_contract = {rule.rule_id: {"obligations": [], "groups": []} for rule in rules}
        for obligation in option.obligations:
            rule_id = _owning_rule_id(obligation, rules)
            if rule_id and rule_id in rules_contract:
                rules_contract[rule_id]["obligations"].append(obligation.obligation_id)
        for group in option.disjunctive_groups:
            if group.rule_id in rules_contract:
                rules_contract[group.rule_id]["groups"].append(group.group_id)
        lowered.option_contracts[option.option_id] = {"rules": rules_contract}
    lowered.options = tuple(options)
    return lowered


def _owning_rule_id(obligation, rules):
    for rule in rules:
        if obligation.obligation_id.startswith(rule.rule_id + ":ob") and rule.kind == "REQUIRE_CALL":
            return rule.rule_id
        if obligation.hypothesis_id.startswith(f"goal_plan:e2e:{rule.rule_id}:"):
            return rule.rule_id
    return None
