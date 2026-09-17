"""Validation and canonicalization for the compositional RuleIR."""

from __future__ import annotations

import hashlib

from .cache import canonical_json
from .types import RuleExpression, RuleIR, RuleTerm, to_wire


MODALITIES = {"REQUIRE", "FORBID", "ALLOW", "UNKNOWN"}
TARGET_KINDS = {"ACTION", "STATE", "CLAIM", "INFORMATION", "EFFECT"}
RELATIONS = {"IF", "ONLY_IF", "UNLESS", "NONE"}
TEMPORAL = {"BEFORE", "AFTER", "UNTIL", "WHILE", "NONE"}
COMPARATORS = {"EQ", "NE", "LT", "LE", "GT", "GE"}
CARDINALITIES = {"EXACT", "MIN", "MAX"}
OPERATORS = {"ATOM", "AND", "OR", "NOT", "COMPARE", "CARDINALITY"}


def validate_expression(expression: RuleExpression | None) -> tuple[str, ...]:
    if expression is None:
        return ()
    issues = []
    if expression.operator not in OPERATORS:
        issues.append(f"unknown expression operator:{expression.operator}")
    if expression.operator == "ATOM" and expression.term is None:
        issues.append("ATOM requires term")
    if expression.operator in {"AND", "OR"} and len(expression.operands) < 2:
        issues.append(f"{expression.operator} requires at least two operands")
    if expression.operator == "NOT" and len(expression.operands) != 1:
        issues.append("NOT requires exactly one operand")
    if expression.operator == "COMPARE" and (
            expression.comparator not in COMPARATORS or expression.left is None
            or expression.right is None):
        issues.append("COMPARE requires comparator, left, and right")
    if expression.operator == "CARDINALITY" and (
            expression.cardinality not in CARDINALITIES or expression.count is None
            or expression.count < 0 or expression.term is None):
        issues.append("CARDINALITY requires kind, non-negative count, and term")
    for operand in expression.operands:
        issues.extend(validate_expression(operand))
    return tuple(issues)


def validate_rule(rule: RuleIR) -> tuple[str, ...]:
    issues = []
    if rule.modality not in MODALITIES:
        issues.append(f"unknown modality:{rule.modality}")
    if rule.target.kind not in TARGET_KINDS:
        issues.append(f"unknown target kind:{rule.target.kind}")
    if rule.relation not in RELATIONS:
        issues.append(f"unknown relation:{rule.relation}")
    if rule.temporal not in TEMPORAL:
        issues.append(f"unknown temporal:{rule.temporal}")
    issues.extend(validate_expression(rule.condition))
    issues.extend(validate_expression(rule.exception))
    return tuple(issues)


def rule_digest(rule: RuleIR) -> str:
    return hashlib.sha256(canonical_json(to_wire(rule)).encode("utf-8")).hexdigest()


def _term(value: dict | None) -> RuleTerm | None:
    if value is None:
        return None
    return RuleTerm(kind=value["kind"], name=value.get("name"), value=value.get("value"),
                    entity_ref=value.get("entity_ref"), field=value.get("field"))


def _expression(value: dict | None) -> RuleExpression | None:
    if value is None:
        return None
    return RuleExpression(
        operator=value["operator"], term=_term(value.get("term")),
        operands=tuple(_expression(item) for item in value.get("operands", ())),
        comparator=value.get("comparator"), left=_term(value.get("left")),
        right=_term(value.get("right")), cardinality=value.get("cardinality"),
        count=value.get("count"))


def rule_from_dict(value: dict) -> RuleIR:
    rule = RuleIR(
        modality=value["modality"], subject=value.get("subject"),
        target=_term(value["target"]), relation=value.get("relation", "NONE"),
        condition=_expression(value.get("condition")), exception=_expression(value.get("exception")),
        temporal=value.get("temporal", "NONE"), values=tuple(value.get("values", ())),
        entity_references=tuple(value.get("entity_references", ())),
        unresolved_references=tuple(value.get("unresolved_references", ())))
    issues = validate_rule(rule)
    if issues:
        raise ValueError("; ".join(issues))
    return rule


RULE_IR_SCHEMA = {
    "type": "object", "additionalProperties": False, "required": ["rules"],
    "properties": {"rules": {"type": "array", "items": {
        "type": "object", "required": ["modality", "target"],
        "properties": {
            "modality": {"enum": sorted(MODALITIES)}, "subject": {"type": ["string", "null"]},
            "target": {"type": "object"}, "relation": {"enum": sorted(RELATIONS)},
            "condition": {"type": ["object", "null"]},
            "exception": {"type": ["object", "null"]},
            "temporal": {"enum": sorted(TEMPORAL)}, "values": {"type": "array"},
            "entity_references": {"type": "array", "items": {"type": "string"}},
            "unresolved_references": {"type": "array", "items": {"type": "string"}},
            "source_spans": {"type": "array", "items": {"type": "object"}},
        }}}}}
