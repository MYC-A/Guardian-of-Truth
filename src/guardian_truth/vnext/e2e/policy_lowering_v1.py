"""Policy lowering (PASS 2): compiled rules -> hypotheses -> operational
bindings -> per-reading options with obligations, disjunctive groups and
unresolved markers. Reuses the baseline operational grounding
(`bind_evaluation_hypothesis`) without modification.

Semantics (E2E V1 program space):
  FORBID_CALL        per target call: atom(tool[,scope]) expected true,
                     must_be_false. Other tools => atom FALSE => satisfied.
  REQUIRE_PRESERVE   per target call: obligation(atom(tool+scope), must_be_true,
                     conditions=(tool-match atom, *rule conditions)).
                     Violated iff the tool is called AND the field is outside
                     the trusted allowed set (FORBID(modify F) == REQUIRE(F)).
  REQUIRE_CALL       existential HISTORICAL_ACTION over the whole supplied
                     trace (must_be_true). Absence proven only with complete
                     history and a catalog-matching tool name.
  PERMIT             recorded, no obligation (NO_VIOLATION != PERMITTED).

A rule with ambiguous operational binding yields one alternative per binding
choice (sub-readings). Binding failure with target calls present yields an
UNRESOLVED marker: it blocks PROVED_NO_ERROR but never manufactures an error.
With no target calls at all, attempt-level rules are vacuously satisfied
(the target response document is the complete target output).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from itertools import product

from ..grounding import bind_evaluation_hypothesis
from ..operational_records import OperationalChoice
from ..policy import quote_spans
from ..proof_records import AtomKind, Obligation, ProofAtom, TimeMode
from ..types import EntityRef, EvaluationHypothesis
from .e2e_types_v1 import CompiledRule, PolicyReading, ReadingOption, UnresolvedMarker

POLICY_LOWERING_VERSION = "policy_lowering_e2e_v1"


@dataclass
class LoweredReading:
    options: tuple[ReadingOption, ...] = ()
    hypotheses: tuple = ()
    choices: tuple = ()                    # OperationalChoice records
    choice_rules: dict = field(default_factory=dict)   # choice_id -> {"rule_kind", "conditions", "toolmatch"}
    direct_rules: dict = field(default_factory=dict)   # hypothesis_id -> {"rule_kind"}
    option_contracts: dict = field(default_factory=dict)  # option_id -> rules/obligations/groups
    rules: tuple = ()
    hypothesis_scopes: dict = field(default_factory=dict)  # hypothesis_id -> raw scope dict


def rule_hypothesis(rule: CompiledRule, *, frontend: str, ordinal: int) -> EvaluationHypothesis:
    """Polarity is fixed by the compiled rule KIND (the behavioral program),
    never by the frontend's surface modality wording."""
    if rule.kind == "FORBID_CALL":
        relation = "PROHIBITION"
    elif frontend == "goal_plan":
        relation = "PLAN_OBLIGATION"
    else:
        relation = "REQUIREMENT"
    return EvaluationHypothesis(
        hypothesis_id=f"{frontend}:e2e:{rule.rule_id}:h{ordinal}",
        frontend=frontend,
        behavioral_relation=relation,
        actor="assistant" if rule.actor != "user" else "user",
        action_or_state=rule.action_key or "unknown_action",
        resource=None,
        conditions=(), exceptions=(),
        grounding=(), unresolved_terms=())


def _prerequisite_atom(cond, event_index: int, entity_value: str, atom_id: str) -> ProofAtom:
    expected = "false" if cond.negated else "true"
    namespace = "e2e" if getattr(cond, "literal_kind", "ACTION") == "ACTION" else "e2e-state"
    return ProofAtom(atom_id, AtomKind.CALL_ATTEMPTED, EntityRef("prerequisite", entity_value, namespace),
                     cond.key, expected, "assistant", TimeMode.THROUGH, event_index)


def _entity_value_of(event) -> str:
    refs = sorted(event.entity_refs, key=lambda ref: (ref.namespace, ref.key, ref.value))
    return refs[0].value if refs else "*"


def _rule_conditions_atoms(rule: CompiledRule, event) -> tuple[ProofAtom, ...]:
    atoms = []
    for i, cond in enumerate((*rule.conditions, *rule.exceptions)):
        atoms.append(_prerequisite_atom(cond, event.index, _entity_value_of(event),
                                        f"{rule.rule_id}:cond{i}:{event.event_id}"))
    return tuple(atoms)


def _scope_entity_value(rule: CompiledRule) -> str:
    for _, values in rule.scope:
        for value in values:
            parsed = value.strip('"')
            if parsed:
                return parsed
    return "*"


def _existential_obligation(rule: CompiledRule, hypothesis: EvaluationHypothesis,
                            last_index: int) -> Obligation:
    atom = ProofAtom(f"{rule.rule_id}:hist", AtomKind.HISTORICAL_ACTION,
                     EntityRef("resource", _scope_entity_value(rule), "e2e"),
                     rule.action_key or "unknown_action", "true", "assistant", TimeMode.THROUGH, last_index)
    conditions = tuple(_prerequisite_atom(cond, last_index, _scope_entity_value(rule),
                                          f"{rule.rule_id}:cond{i}:hist")
                       for i, cond in enumerate((*rule.conditions, *rule.exceptions)))
    return Obligation(f"{rule.rule_id}:ob", hypothesis.hypothesis_id, None, atom, True, conditions)


def _grounded_hypothesis(rule: CompiledRule, frontend: str, normative_text: str,
                         action_key: str | None = None) -> EvaluationHypothesis:
    base = rule_hypothesis(rule, frontend=frontend, ordinal=0)
    return EvaluationHypothesis(
        hypothesis_id=base.hypothesis_id, frontend=base.frontend,
        behavioral_relation=base.behavioral_relation, actor=base.actor,
        action_or_state=action_key or base.action_or_state, resource=base.resource,
        conditions=(), exceptions=(),
        grounding=quote_spans(normative_text, list(rule.source_quotes), frontend),
        unresolved_terms=())


def lower_rule(rule: CompiledRule, *, frontend: str, normative_text: str, backend, ledger,
               tool_catalog, target_calls):
    """One rule -> (alternatives, hypothesis, choices). Each alternative is
    (obligations, groups, markers); alternatives = binding choices."""
    if rule.kind == "PERMIT" or not rule.action_key:
        return [((), (), ())], None, ()
    hypothesis = _grounded_hypothesis(rule, frontend, normative_text)
    extra_markers = tuple(UnresolvedMarker(f"{rule.rule_id}:term:{term}", "rule unresolved term")
                          for term in rule.unresolved_terms)
    if rule.kind == "REQUIRE_CALL":
        last = len(ledger.events) - 1
        obligation = _existential_obligation(rule, hypothesis, last)
        return [((obligation,), (), extra_markers)], hypothesis, ()
    if not target_calls:
        # Attempt-level rules are vacuously satisfied when the target output
        # contains no attempted call at all (the response document is complete).
        return [((), (), extra_markers)], hypothesis, ()
    binding = bind_evaluation_hypothesis(hypothesis, backend, normative_text=normative_text,
                                         ledger=ledger, tool_catalog=tuple(tool_catalog),
                                         allowed_scope=_raw_scope(rule))
    if not binding.choices:
        reasons = ";".join(sorted({str(reason.value) for reason in binding.failures}
                                  | {detail for _, detail in binding.discarded}))
        marker = UnresolvedMarker(f"{rule.rule_id}:binding", "operational binding unresolved: " + reasons)
        return [((), (), (marker,) + extra_markers)], hypothesis, ()
    alternatives, choices = [], []
    for choice in binding.choices:
        choices.append(choice)
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
            obligations.append(Obligation(f"{choice.choice_id}:o{i}", choice.choice_id, None, atom,
                                           choice.must_be_true, conditions))
        alternatives.append((tuple(obligations), (), extra_markers))
    return alternatives, hypothesis, tuple(choices)


def _raw_scope(rule: CompiledRule) -> dict | None:
    import json
    if not rule.scope:
        return None
    out = {}
    for field_name, values in rule.scope:
        raw = []
        for value in values:
            try:
                raw.append(json.loads(value))
            except (ValueError, TypeError):
                raw.append(value)
        out[field_name] = list(dict.fromkeys(raw))
    return out


def rule_side_spec(rule: CompiledRule) -> dict:
    return {"rule_kind": rule.kind,
            "conditions": tuple((cond.key, cond.negated) for cond in (*rule.conditions, *rule.exceptions)),
            "toolmatch": rule.kind == "REQUIRE_PRESERVE"}


def lower_reading(reading: PolicyReading, *, frontend: str, normative_text: str, backend, ledger,
                  tool_catalog, target_calls) -> LoweredReading:
    """One reading -> options (reading x binding alternatives) + side tables."""
    out = LoweredReading(rules=reading.rules)
    per_rule_alternatives = []
    for rule in reading.rules:
        alternatives, hypothesis, choices = lower_rule(rule, frontend=frontend,
                                                       normative_text=normative_text, backend=backend,
                                                       ledger=ledger, tool_catalog=tool_catalog,
                                                       target_calls=target_calls)
        per_rule_alternatives.append([(obs, groups, markers) for obs, groups, markers in alternatives])
        if hypothesis is not None:
            out.hypotheses = out.hypotheses + (hypothesis,)
            out.hypothesis_scopes[hypothesis.hypothesis_id] = _raw_scope(rule) or {}
        out.choices = out.choices + tuple(choices)
        for choice in choices:
            out.choice_rules[choice.choice_id] = rule_side_spec(rule)
        if rule.kind == "REQUIRE_CALL":
            out.direct_rules[hypothesis.hypothesis_id] = {"rule_kind": rule.kind}
    reading_markers = tuple(UnresolvedMarker(f"{reading.reading_id}:term:{term}", "reading unresolved term")
                            for term in reading.unresolved_terms)
    options = []
    if per_rule_alternatives:
        for combo_index, combo in enumerate(product(*per_rule_alternatives)):
            obligations, groups, markers = [], [], list(reading_markers)
            for obs, grp, mrk in combo:
                obligations.extend(obs)
                groups.extend(grp)
                markers.extend(mrk)
            options.append(ReadingOption(f"{reading.reading_id}#{combo_index}", tuple(obligations),
                                          tuple(groups), tuple(dict.fromkeys(markers))))
    if not options:
        options = [ReadingOption(reading.reading_id + "#0", (), (), reading_markers)]
    for option in options:
        rules_contract = {}
        for rule in reading.rules:
            rules_contract[rule.rule_id] = {"obligations": [], "groups": []}
        for obligation in option.obligations:
            rule_id = _owning_rule_id(obligation, reading)
            if rule_id and rule_id in rules_contract:
                rules_contract[rule_id]["obligations"].append(obligation.obligation_id)
        for group in option.disjunctive_groups:
            if group.rule_id in rules_contract:
                rules_contract[group.rule_id]["groups"].append(group.group_id)
        out.option_contracts[option.option_id] = {"rules": rules_contract}
    out.options = tuple(options)
    return out


def _owning_rule_id(obligation, reading: PolicyReading) -> str | None:
    for rule in reading.rules:
        if obligation.obligation_id.startswith(rule.rule_id + ":ob") and rule.kind == "REQUIRE_CALL":
            return rule.rule_id
        if obligation.hypothesis_id.startswith(f"policy:e2e:{rule.rule_id}:") or \
           obligation.hypothesis_id.startswith(f"goal_plan:e2e:{rule.rule_id}:") or \
           obligation.hypothesis_id.startswith(f"goal:e2e:{rule.rule_id}:"):
            return rule.rule_id
    return None
