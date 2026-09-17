"""Thin, conservative adapter from Phi into the unchanged Guardian E2E core."""

from __future__ import annotations

from dataclasses import replace

from guardian_truth.vnext.e2e.core_v1 import GuardianE2EV1

from .types import RuleExpression, RuleIR, SemanticInterpretationSet


def _simple_atoms(expression: RuleExpression | None):
    if expression is None:
        return [], []
    if expression.operator == "ATOM" and expression.term and expression.term.name:
        return [[expression.term.name, False]], []
    if expression.operator == "NOT" and len(expression.operands) == 1:
        child = expression.operands[0]
        if child.operator == "ATOM" and child.term and child.term.name:
            return [[child.term.name, True]], []
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


def phi_to_policy_readings(phi: SemanticInterpretationSet) -> tuple[tuple[dict, ...], tuple[str, ...]]:
    readings, unresolved = [], list(phi.unresolved)
    for candidate in phi.interpretations:
        row, issues = rule_to_core_row(candidate.rule)
        if row is None or issues:
            unresolved.extend(f"{candidate.candidate_id}:{issue}" for issue in issues)
            continue
        quotes = [span.quote for span in candidate.source_spans]
        row["quotes"] = quotes
        readings.append({"rules": [row], "unresolved": list(candidate.unresolved_components)})
    return tuple(readings), tuple(dict.fromkeys(unresolved))


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
