"""Deterministic RuleIR-to-hypothesis rendering used by the NLI firewall."""

from __future__ import annotations

import json

from .types import RuleExpression, RuleIR, RuleTerm


def _term(term: RuleTerm) -> str:
    head = term.name or term.field or term.kind.lower()
    if term.entity_ref:
        head += f" for entity {term.entity_ref}"
    if term.value is not None:
        head += " equals " + json.dumps(term.value, ensure_ascii=False, sort_keys=True)
    return head


def _expression(expression: RuleExpression) -> str:
    if expression.operator == "ATOM":
        return _term(expression.term)
    if expression.operator in {"AND", "OR"}:
        joiner = " and " if expression.operator == "AND" else " or "
        return "(" + joiner.join(_expression(item) for item in expression.operands) + ")"
    if expression.operator == "NOT":
        return "not " + _expression(expression.operands[0])
    if expression.operator == "COMPARE":
        words = {"EQ": "equals", "NE": "does not equal", "LT": "is less than",
                 "LE": "is at most", "GT": "is greater than", "GE": "is at least"}
        return f"{_term(expression.left)} {words[expression.comparator]} {_term(expression.right)}"
    words = {"EXACT": "exactly", "MIN": "at least", "MAX": "at most"}
    return f"{words[expression.cardinality]} {expression.count} {_term(expression.term)}"


def render_rule(rule: RuleIR) -> str:
    subject = rule.subject or "the assistant"
    target = _term(rule.target)
    modal = {"REQUIRE": "is required to", "FORBID": "is forbidden to",
             "ALLOW": "is allowed to", "UNKNOWN": "may or may not"}[rule.modality]
    sentence = f"{subject} {modal} {target}"
    if rule.relation in {"IF", "ONLY_IF"} and rule.condition:
        sentence += (" if " if rule.relation == "IF" else " only if ") + _expression(rule.condition)
    if (rule.relation == "UNLESS" or rule.exception) and rule.exception:
        sentence += " unless " + _expression(rule.exception)
    if rule.temporal != "NONE" and rule.condition:
        sentence += f" {rule.temporal.lower()} " + _expression(rule.condition)
    return sentence + "."
