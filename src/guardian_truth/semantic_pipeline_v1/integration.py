"""Thin, conservative adapter from Phi into the unchanged Guardian E2E core."""

from __future__ import annotations

from dataclasses import replace

from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1

from .types import RuleExpression, RuleIR, SemanticInterpretationSet


def _term_loss(term) -> list[str]:
    """Core atoms carry only a name: any value/field/entity operand would be lost."""
    lost = [part for part in ("value", "field", "entity_ref") if getattr(term, part) not in (None, "", ())]
    return [f"core-term-operand-not-lossless:{part}" for part in lost]


def _simple_atoms(expression: RuleExpression | None):
    if expression is None:
        return [], []
    if expression.operator == "ATOM" and expression.term and expression.term.name:
        return [[expression.term.name, False]], _term_loss(expression.term)
    if expression.operator == "NOT" and len(expression.operands) == 1:
        child = expression.operands[0]
        if child.operator == "ATOM" and child.term and child.term.name:
            return [[child.term.name, True]], _term_loss(child.term)
    if expression.operator == "AND":
        atoms, unresolved = [], []
        for child in expression.operands:
            child_atoms, child_unresolved = _simple_atoms(child)
            atoms.extend(child_atoms); unresolved.extend(child_unresolved)
        return atoms, unresolved
    return [], [f"core-cannot-losslessly-lower:{expression.operator}"]


def rule_to_core_row(rule: RuleIR) -> tuple[dict | None, tuple[str, ...]]:
    unresolved = list(rule.unresolved_references)
    if rule.target.kind != "ACTION" or not rule.target.name:
        return None, tuple((*unresolved, f"core-target-unsupported:{rule.target.kind}"))
    kind = {"FORBID": "FORBID_CALL", "REQUIRE": "REQUIRE_CALL", "ALLOW": "PERMIT",
            "UNKNOWN": None}[rule.modality]
    if kind is None:
        return None, tuple((*unresolved, "core-modality-unknown"))
    # Operand scope (which entity/field/value the action touches) has no core slot:
    # refuse instead of lowering two different rules to one identical row.
    unresolved.extend(_term_loss(rule.target))
    if rule.values:
        unresolved.append("core-rule-values-not-lossless")
    if rule.entity_references:
        unresolved.append("core-rule-entity-scope-not-lossless")
    conditions, condition_unresolved = _simple_atoms(rule.condition)
    exceptions, exception_unresolved = _simple_atoms(rule.exception)
    unresolved.extend(condition_unresolved); unresolved.extend(exception_unresolved)
    if rule.temporal != "NONE":
        unresolved.append(f"core-temporal-not-lossless:{rule.temporal}")
    if rule.relation not in {"NONE", "IF", "ONLY_IF", "UNLESS"}:
        unresolved.append(f"core-relation-not-lossless:{rule.relation}")
    if unresolved:
        return None, tuple(dict.fromkeys(unresolved))
    return {"kind": kind, "modality": rule.modality, "action_key": rule.target.name,
            "actor": rule.subject or "assistant", "relation": rule.relation,
            "conditions": conditions, "exceptions": exceptions, "scope": [],
            "unresolved_terms": []}, ()


MAX_ALTERNATIVE_READINGS = 16


def phi_to_policy_readings(phi: SemanticInterpretationSet) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    """Candidates of the SAME source segments are alternative interpretations;
    candidates of DIFFERENT segments are jointly active norms. Each returned
    reading therefore holds one alternative per segment group, conjoined."""
    from itertools import product
    groups, unresolved = {}, list(phi.unresolved)
    for candidate in phi.interpretations:
        row, issues = rule_to_core_row(candidate.rule)
        if row is None or issues:
            unresolved.extend(f"{candidate.candidate_id}:{issue}" for issue in issues)
            continue
        row["quotes"] = [span.quote for span in candidate.source_spans]
        key = tuple(sorted(candidate.source_segment_ids)) or (candidate.candidate_id,)
        groups.setdefault(key, []).append((row, list(candidate.unresolved_components)))
    if not groups:
        return (), tuple(dict.fromkeys(unresolved))
    combos = 1
    for alternatives in groups.values():
        combos *= len(alternatives)
    if combos > MAX_ALTERNATIVE_READINGS:
        unresolved.append(f"core-alternative-readings-exceed-cap:{combos}")
        return (), tuple(dict.fromkeys(unresolved))
    readings = []
    for choice in product(*groups.values()):
        readings.append({"rules": [row for row, _ in choice],
                         "unresolved": [item for _, items in choice for item in items]})
    return tuple(readings), tuple(dict.fromkeys(unresolved))


def policy_trust(unresolved: tuple[str, ...]) -> str:
    """A lowered subset is never the reviewed complete policy."""
    return "PARTIAL_UNREVIEWED_POLICY" if unresolved else "LOWERED_SUBSET_UNREVIEWED"


def bounded_core_decision(prediction, unresolved: tuple[str, ...]) -> dict:
    """ERROR from a supported subset stands; a clean result over a partial policy
    is not proven clean (UNKNOWN, projected to 0 by the competition contract)."""
    if prediction == 1:
        return {"decision": "ERROR", "binary": 1, "trust": policy_trust(unresolved)}
    if unresolved:
        return {"decision": "UNKNOWN", "binary": 0, "trust": policy_trust(unresolved)}
    return {"decision": "NO_ERROR_MODEL_LOWERED", "binary": 0, "trust": policy_trust(unresolved)}


def run_existing_core(case, phi: SemanticInterpretationSet, *, backend,
                      policy_segment_ids: frozenset[str] | None = None,
                      additional_normative_texts: tuple[str, ...] = (), **core_options):
    if policy_segment_ids is None:
        policy_phi = phi
        routing_unresolved = ()
    else:
        accepted, rejected = [], []
        for candidate in phi.interpretations:
            if set(candidate.source_segment_ids) & policy_segment_ids:
                accepted.append(candidate)
            else:
                rejected.append(f"{candidate.candidate_id}:core-routing-unsupported-source")
        policy_phi = SemanticInterpretationSet(tuple(accepted), phi.unresolved, phi.source_coverage)
        routing_unresolved = tuple(rejected)
    readings, unresolved = phi_to_policy_readings(policy_phi)
    normative_text = case.system_policy
    for text in additional_normative_texts:
        if text and text not in normative_text:
            normative_text += "\n" + text
    adapted = replace(case, system_policy=normative_text, authoritative_policy_readings=readings)
    core = GuardianE2EV1(backend, oracle_policy=True, **core_options)
    analysis = core.analyze_e2e_v1(adapted)
    return analysis, tuple(dict.fromkeys((*unresolved, *routing_unresolved)))
