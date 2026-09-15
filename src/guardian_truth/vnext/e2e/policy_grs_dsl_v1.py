"""GRS DSL: closed grammar, parser and validator (spec 44, 45, 40).

Grammar (frozen; never extended during an evaluation):
  RULESET := RULE(...) | RULE(...), RULE(...), ...
  RULE := RULE(MODALITY, TARGET, MODIFIER*)
  MODALITY := PERMIT | FORBID | REQUIRE
  TARGET := F#
  MODIFIER := WHEN(EXPR) | UNLESS(EXPR) | ACTOR(F#) | BEFORE(EXPR) | AFTER(EXPR)
            | UNTIL(EXPR) | SCOPE(F#) | TOGETHER(EXPR) | CHOICE(EXPR)
  EXPR := F# | NOT(F#) | AND(F#, ...) | OR(F#, ...)

Expressions are serialized canonically as s-expressions inside the DSL text,
e.g. AND(F1,F2). Parsing is strictly syntax-driven; unknown inventory IDs and
free-text leaves are INVALID (closed vocabulary invariant).
"""

from __future__ import annotations

import re

from .e2e_types_v1 import DslRule, DslRuleset

DSL_VERSION = "policy_grs_dsl_e2e_v1"

MODIFIERS = {"WHEN", "UNLESS", "ACTOR", "BEFORE", "AFTER", "UNTIL", "SCOPE", "TOGETHER", "CHOICE"}
MODALITIES = {"PERMIT", "FORBID", "REQUIRE"}

_TOKEN = re.compile(r"\s*(RULESET|RULE|PERMIT|FORBID|REQUIRE|WHEN|UNLESS|ACTOR|BEFORE|AFTER|UNTIL|SCOPE|TOGETHER|CHOICE|NOT|AND|OR|F\d+|[(),])")


class DslError(ValueError):
    pass


def _tokenize(text_value: str):
    pos, tokens = 0, []
    while pos < len(text_value):
        match = _TOKEN.match(text_value, pos)
        if not match:
            if text_value[pos].isspace():
                pos += 1
                continue
            raise DslError("unexpected character at %d" % pos)
        tokens.append(match.group(1))
        pos = match.end()
    return tokens


class _Parser:
    def __init__(self, tokens):
        self.tokens = tokens
        self.pos = 0

    def peek(self):
        return self.tokens[self.pos] if self.pos < len(self.tokens) else None

    def take(self, expected=None):
        token = self.peek()
        if token is None or (expected and token != expected):
            raise DslError("expected %s, got %s" % (expected, token))
        self.pos += 1
        return token

    def expr(self):
        head = self.take()
        if head.startswith("F"):
            return ("F", head)
        if head in {"NOT", "AND", "OR"}:
            self.take("(")
            parts = [self.expr()]
            while self.peek() == ",":
                self.take(",")
                parts.append(self.expr())
            self.take(")")
            if head == "NOT" and len(parts) != 1:
                raise DslError("NOT is unary")
            if head == "AND" and len(parts) < 2:
                raise DslError("AND needs at least two operands")
            if head == "OR" and len(parts) < 2:
                raise DslError("OR needs at least two operands")
            return (head, *parts)
        raise DslError("expected expression, got %s" % head)

    def modifier(self):
        name = self.take()
        if name not in MODIFIERS:
            raise DslError("unknown modifier %s" % name)
        self.take("(")
        inner = self.expr()
        self.take(")")
        return (name, inner)

    def rule(self):
        self.take("RULE")
        self.take("(")
        modality = self.take()
        if modality not in MODALITIES:
            raise DslError("unknown modality %s" % modality)
        self.take(",")
        target = self.take()
        if not target.startswith("F"):
            raise DslError("target must be an inventory fact ID")
        modifiers = []
        while self.peek() == ",":
            self.take(",")
            modifiers.append(self.modifier())
        self.take(")")
        return DslRule(modality, target, tuple(modifiers))

    def ruleset(self):
        self.take("RULESET")
        self.take("(")
        rules = [self.rule()]
        while self.peek() == ",":
            self.take(",")
            rules.append(self.rule())
        self.take(")")
        if self.peek() is not None:
            raise DslError("trailing tokens after RULESET")
        return DslRuleset(tuple(rules))


def parse_dsl(text_value: str, known_ids: frozenset[str] | set[str]) -> DslRuleset:
    """Parse and validate a closed-vocabulary ruleset. Raises DslError."""
    if not text_value or not text_value.strip():
        raise DslError("empty DSL")
    ruleset = _Parser(_tokenize(text_value.strip())).ruleset()
    if not ruleset.rules:
        raise DslError("empty ruleset")

    def check(expr):
        if expr[0] == "F":
            if expr[1] not in known_ids:
                raise DslError("unknown inventory ID %s" % expr[1])
            return
        for part in expr[1:]:
            check(part)

    for rule in ruleset.rules:
        if rule.target not in known_ids:
            raise DslError("unknown inventory ID %s" % rule.target)
        seen = set()
        for name, expr in rule.modifiers:
            if name in seen:
                raise DslError("duplicate modifier %s" % name)
            seen.add(name)
            if name == "ACTOR" and expr[0] != "F":
                raise DslError("ACTOR takes a fact ID")
            check(expr)
    return ruleset


def serialize_expr(expr) -> str:
    if expr[0] == "F":
        return expr[1]
    return expr[0] + "(" + ",".join(serialize_expr(part) for part in expr[1:]) + ")"


def serialize_rule(rule: DslRule) -> str:
    parts = [rule.modality, rule.target]
    parts.extend(name + "(" + serialize_expr(expr) + ")" for name, expr in rule.modifiers)
    return "RULE(" + ",".join(parts) + ")"


def serialize_ruleset(ruleset: DslRuleset) -> str:
    return "RULESET(" + ",".join(serialize_rule(rule) for rule in ruleset.rules) + ")"
