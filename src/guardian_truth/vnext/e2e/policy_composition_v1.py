"""Policy composition: H0 and GRS compile into one behavioral program space
(spec 31, 50, 51, 52). No winner selection, no voting, no confidence. The two
frontends create semantic alternatives; deterministically equivalent readings
are deduped; material disagreements are retained as separate axis choices.
"""

from __future__ import annotations

import re

from ..integrity import canonical, digest
from .e2e_types_v1 import (CompiledCondition, CompiledRule, FrontendCandidate, PolicyFlatStructure,
                            PolicyReading, SemanticLiteral)
from .policy_grs_dsl_v1 import DslRule

_WORD = re.compile(r"[A-Za-z0-9]+")


def _key_from(quote: str, normalized: str | None) -> str:
    if normalized and _WORD.fullmatch(normalized.replace("_", "").replace("-", "")):
        return normalized.strip().lower().replace("-", "_")
    words = [word.lower() for word in _WORD.findall(quote)]
    return "_".join(words[:6]) if words else "unknown_action"


def _quote_value_forms(quote: str) -> tuple[str, ...]:
    """Canonical JSON literal forms of a quoted value (string form, plus
    numeric/boolean form when the quote parses as one)."""
    forms = [canonical(quote).decode("utf-8")]
    stripped = quote.strip()
    if re.fullmatch(r"-?\d+(\.\d+)?", stripped):
        forms.append(canonical(float(stripped) if "." in stripped else int(stripped)).decode("utf-8"))
    elif stripped.lower() in {"true", "false"}:
        forms.append(canonical(stripped.lower() == "true").decode("utf-8"))
    return tuple(dict.fromkeys(forms))


def _condition(key: str, negated: bool, quote: str, literal_kind: str = "ACTION") -> CompiledCondition:
    return CompiledCondition(key=_key_from(quote, key), negated=negated, bound="HISTORY", quote=quote,
                             literal_kind=literal_kind)


def compile_h0(structure: PolicyFlatStructure, state_contract: dict | None,
               tool_catalog: frozenset[str] | set[str]) -> PolicyReading:
    """H0 flat structure -> compiled rules (deterministic, no LLM)."""
    state = state_contract or {}
    rules: list[CompiledRule] = []
    unresolved: list[str] = list(structure.unresolved_terms)
    modality = structure.modality
    relation = structure.relation
    if modality == "UNKNOWN":
        unresolved.append("h0:unknown modality")
    actor = "assistant" if structure.actor.lower() in {"assistant", "agent", "system", "unknown", ""} else structure.actor.lower()
    targets = structure.target_clauses
    conditions = tuple(_condition(c.normalized_key or "", c.polarity == "NEGATED", c.quote, c.kind)
                       for c in structure.condition_literals)
    exceptions = tuple(_condition(e.normalized_key or "", True, e.quote, e.kind)
                       for e in structure.exception_literals)
    # UNLESS relation means the exception disables the prohibition; ONLY_IF means
    # the target is permitted only under the condition (violation when it happens
    # without the condition): both compile to a negated condition.
    if relation == "UNLESS" and structure.exception_literals:
        conditions = conditions + exceptions
        exceptions = ()
    elif relation == "ONLY_IF" and structure.condition_literals:
        conditions = tuple(_condition(c.normalized_key or "", True, c.quote)
                           for c in structure.condition_literals)
    for i, clause in enumerate(targets):
        quotes = tuple(dict.fromkeys([clause.quote, *(q for q in structure.source_quotes if q)]))
        key = _key_from(clause.quote, clause.normalized_key)
        field_hit = None
        for field_name in sorted(state):
            if re.search(r"(?<![\w])" + re.escape(field_name) + r"(?![\w])",
                         clause.quote + " " + (clause.normalized_key or "").replace("_", " ")):
                field_hit = field_name
                break
        if modality == "PERMISSION":
            rules.append(_rule("h0", i, "PERMIT", "PERMIT", key, actor, relation, conditions, exceptions,
                               (), quotes, ()))
            continue
        if clause.kind == "VALUE" and clause.normalized_key:
            if modality == "PROHIBITION":
                # Exact-value prohibition: FORBID calling the tool with this value.
                scope = ((clause.normalized_key, _quote_value_forms(clause.quote)),)
                rules.append(_rule("h0", i, "FORBID_CALL", "FORBID", key, actor, relation, conditions,
                                   exceptions, scope, quotes, ()))
            else:
                rules.append(_rule("h0", i, "REQUIRE_CALL", "REQUIRE", key, actor, relation, conditions,
                                   exceptions, (), quotes,
                                   ("h0:value-scoped requirement not expressible in V1",)))
            continue
        if modality == "PROHIBITION":
            if field_hit is not None:
                # FORBID(modify F) with trusted state contract => REQUIRE(F preserved).
                rules.append(_rule("h0", i, "REQUIRE_PRESERVE", "FORBID", key, actor, relation,
                                   conditions, exceptions,
                                   ((field_hit, tuple(canonical(v).decode("utf-8") for v in state[field_hit])),),
                                   quotes, ()))
            else:
                mentioned = [w for w in _WORD.findall(clause.quote) if w.lower() in {"modify", "change", "alter", "update"}]
                if mentioned and not state:
                    unresolved.append("h0:field modification prohibition without state contract")
                rules.append(_rule("h0", i, "FORBID_CALL", "FORBID", key, actor, relation, conditions,
                                   exceptions, (), quotes, ()))
            continue
        if modality == "REQUIREMENT":
            if relation == "BEFORE" and structure.condition_literals:
                # REQUIRE(A) BEFORE(B): B must not be attempted unless A
                # preceded it => FORBID(B) WHEN NOT(A happened before B).
                b_literal = structure.condition_literals[0]
                b_key = _key_from(b_literal.quote, b_literal.normalized_key)
                rules.append(_rule("h0", i, "FORBID_CALL", "REQUIRE", b_key, actor, relation,
                                   (_condition(key, True, clause.quote),), exceptions, (), quotes, ()))
            else:
                rules.append(_rule("h0", i, "REQUIRE_CALL", "REQUIRE", key, actor, relation, conditions,
                                   exceptions, (), quotes, ()))
            continue
        unresolved.append("h0:uncompilable clause " + clause.quote[:40])
    if structure.quantification in {"EXACTLY_ONE", "AT_LEAST_ONE"} and modality in {"PERMISSION", "REQUIREMENT"}:
        unresolved.append("h0:choice cardinality not expressible in V1 program space")
    return PolicyReading("policy:h0:r0", "h0", tuple(rules), tuple(dict.fromkeys(unresolved)))


def compile_grs(ruleset, inventory, state_contract: dict | None) -> PolicyReading:
    """GRS DSL ruleset -> compiled rules (deterministic, no LLM)."""
    state = state_contract or {}
    facts = {atom.atom_id: atom for atom in inventory.facts}
    marker_quotes = tuple(dict.fromkeys(m.quote for m in (*inventory.modality_markers, *inventory.relation_markers)))
    rules: list[CompiledRule] = []
    unresolved: list[str] = []
    for i, dsl_rule in enumerate(ruleset.rules):
        target_atom = facts[dsl_rule.target]
        key = _key_from(target_atom.quote, target_atom.meaning)
        quotes = tuple(dict.fromkeys([target_atom.quote, *marker_quotes]))
        conditions, exceptions = [], []
        before_anchor = None
        for name, expr in dsl_rule.modifiers:
            leaves = _expr_leaves(expr)
            negated = expr[0] == "NOT" or (expr[0] == "AND" and any(p[0] == "NOT" for p in expr[1:]))
            for leaf in leaves:
                atom = facts[leaf[1]]
                leaf_key = _key_from(atom.quote, atom.meaning)
                if name in {"WHEN", "TOGETHER"}:
                    conditions.append(_condition(leaf_key, negated, atom.quote, atom.kind))
                elif name in {"UNLESS", "UNTIL"}:
                    conditions.append(_condition(leaf_key, not negated, atom.quote, atom.kind))
                elif name == "ACTOR":
                    if atom.kind == "ACTOR" and "assistant" in atom.quote.lower():
                        pass  # assistant bearer: no extra condition
                    else:
                        unresolved.append("grs:non-assistant actor modifier kept unresolved")
                elif name in {"BEFORE", "AFTER"}:
                    before_anchor = _condition(leaf_key, False, atom.quote)
                elif name == "SCOPE":
                    pass  # scope fact handled below via key match
                elif name == "CHOICE":
                    unresolved.append("grs:CHOICE modifier not expressible in V1 program space")
        field_hit = None
        for field_name in sorted(state):
            hay = target_atom.quote + " " + (target_atom.meaning or "").replace("_", " ")
            for name, expr in dsl_rule.modifiers:
                if name == "SCOPE":
                    hay += " " + " ".join(facts[leaf[1]].quote for leaf in _expr_leaves(expr))
            if re.search(r"(?<![\w])" + re.escape(field_name) + r"(?![\w])", hay):
                field_hit = field_name
                break
        if dsl_rule.modality == "PERMIT":
            rules.append(_rule("grs", i, "PERMIT", "PERMIT", key, "assistant", "NONE",
                               tuple(conditions), tuple(exceptions), (), quotes, ()))
        elif dsl_rule.modality == "FORBID":
            if target_atom.kind == "VALUE" and target_atom.meaning:
                rules.append(_rule("grs", i, "FORBID_CALL", "FORBID", key, "assistant", "NONE",
                                   tuple(conditions), tuple(exceptions),
                                   ((target_atom.meaning, _quote_value_forms(target_atom.quote)),), quotes, ()))
            elif field_hit is not None:
                rules.append(_rule("grs", i, "REQUIRE_PRESERVE", "FORBID", key, "assistant", "NONE",
                                   tuple(conditions), tuple(exceptions),
                                   ((field_hit, tuple(canonical(v).decode("utf-8") for v in state[field_hit])),),
                                   quotes, ()))
            else:
                rules.append(_rule("grs", i, "FORBID_CALL", "FORBID", key, "assistant", "NONE",
                                   tuple(conditions), tuple(exceptions), (), quotes, ()))
        else:  # REQUIRE
            if before_anchor is not None:
                # REQUIRE(A) BEFORE(B): B must not be attempted unless A
                # preceded it => FORBID(B) WHEN NOT(A happened before B).
                rules.append(_rule("grs", i, "FORBID_CALL", "REQUIRE", before_anchor.key, "assistant", "BEFORE",
                                   (_condition(key, True, target_atom.quote),), tuple(exceptions), (), quotes, ()))
            else:
                rules.append(_rule("grs", i, "REQUIRE_CALL", "REQUIRE", key, "assistant", "NONE",
                                   tuple(conditions), tuple(exceptions), (), quotes, ()))
    return PolicyReading("policy:grs:r0", "grs", tuple(rules), tuple(dict.fromkeys(unresolved)))


def _expr_leaves(expr):
    if expr[0] == "F":
        return [expr]
    out = []
    for part in expr[1:]:
        out.extend(_expr_leaves(part))
    return out


def _rule(frontend, index, kind, modality, action_key, actor, relation, conditions, exceptions, scope, quotes, extra):
    return CompiledRule(
        rule_id=f"policy:{frontend}:rule{index}", kind=kind, modality=modality, action_key=action_key,
        actor=actor if actor in {"assistant", "user", "UNKNOWN"} else "UNKNOWN", relation=relation,
        conditions=tuple(conditions), exceptions=tuple(exceptions), scope=tuple(scope),
        source_quotes=tuple(quotes), unresolved_terms=tuple(extra), frontend=frontend)


def reading_canonical_key(reading: PolicyReading) -> str:
    """Canonical structural form ignoring IDs/order (spec 51 steps 1-3)."""
    rows = []
    for rule in reading.rules:
        rows.append({"kind": rule.kind, "modality": rule.modality, "action_key": rule.action_key,
                     "actor": rule.actor, "relation": rule.relation,
                     "conditions": sorted((c.key, c.negated) for c in rule.conditions),
                     "exceptions": sorted((c.key, c.negated) for c in rule.exceptions),
                     "scope": sorted((field, sorted(values)) for field, values in rule.scope)})
    return digest({"rules": sorted(rows, key=canonical), "unresolved": sorted(reading.unresolved_terms)})


def dedupe_readings(readings: tuple[PolicyReading, ...]) -> tuple[PolicyReading, ...]:
    """Deterministic equivalence dedupe (spec 78): canonical-equal readings merge."""
    kept, seen = [], {}
    for reading in readings:
        key = reading_canonical_key(reading)
        if key in seen:
            continue
        seen[key] = reading
        kept.append(reading)
    return tuple(kept)


def reading_from_rows(authoritative_readings, policy_text: str) -> tuple[PolicyReading, ...]:
    """Oracle substitution: authoritative reading rows -> PolicyReading records.
    Rows: {"rules": [row...], "unresolved": [...]}, row fields as in
    reading_canonical_key. Source quotes default to the whole policy text."""
    readings = []
    for index, supplied in enumerate(authoritative_readings):
        rules = supplied.get("rules", supplied) if isinstance(supplied, dict) else supplied
        unresolved = supplied.get("unresolved", []) if isinstance(supplied, dict) else []
        compiled = []
        for i, row in enumerate(rules):
            conditions = tuple(CompiledCondition(key, bool(negated), policy_text)
                               for key, negated in row.get("conditions", []))
            exceptions = tuple(CompiledCondition(key, bool(negated), policy_text)
                               for key, negated in row.get("exceptions", []))
            scope = tuple((field_name, tuple(values))
                          for field_name, values in row.get("scope", []))
            quotes = tuple(row.get("quotes", ())) or (policy_text,)
            compiled.append(CompiledRule(
                rule_id=f"policy:oracle:rule{index}:{i}", kind=row.get("kind", "FORBID_CALL"),
                modality=row.get("modality", "FORBID"), action_key=row.get("action_key"),
                actor=row.get("actor", "assistant"), relation=row.get("relation", "NONE"),
                conditions=conditions, exceptions=exceptions, scope=scope,
                source_quotes=quotes, unresolved_terms=tuple(row.get("unresolved_terms", ())),
                frontend="oracle"))
        readings.append(PolicyReading(f"policy:oracle:r{index}", "oracle", tuple(compiled),
                                       tuple(unresolved)))
    return tuple(readings)
