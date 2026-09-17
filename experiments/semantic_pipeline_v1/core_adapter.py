"""semantic_pipeline_v1 — Phase 14: thin adapter RuleIR -> incumbent core.

The existing lowerer / solver / certificate are NOT touched: a RuleIR reading
is mapped to the incumbent PolicyFlatStructure and compiled by the incumbent
deterministic compiler (policy_composition_v1.compile_h0).  This is a
representation adapter only.

Feature flag: semantic_pipeline_v1 (default False).  The experiment runner
enables it explicitly; nothing in production changes.

Honest limitations (documented, not hidden):
  - RuleIR comparison/cardinality atoms have NO counterpart in the V1 flat
    structure: they are recorded as unresolved terms (the incumbent lowering
    would otherwise silently drop them);
  - rules whose target stays UNKNOWN/unbound produce no compiled rule (they
    become frontend UNAVAILABLE, never a fabricated obligation);
  - modality UNKNOWN produces no behavioral rule (compile_h0 marks it
    unresolved).
"""

from __future__ import annotations

import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[1]
_SRC = str(REPO / "src")
if _SRC not in sys.path:
    sys.path.insert(0, _SRC)
if str(HERE) not in sys.path:
    sys.path.insert(0, str(HERE))

from rule_ir import RuleIR

from guardian_truth.vnext.e2e.e2e_types_v1 import PolicyFlatStructure, SemanticLiteral

MODALITY_MAP = {"REQUIRE": "REQUIREMENT", "FORBID": "PROHIBITION",
                "ALLOW": "PERMISSION", "UNKNOWN": "UNKNOWN"}

_KIND_MAP = {"ACTION": "ACTION", "STATE": "STATE", "CLAIM": "CLAIM", "UNKNOWN": "ACTION"}

# RuleIR atom kinds -> incumbent literal kinds (CONDITION/VALUE have no V1
# literal kind; conditions lower as STATE predicates)
_ATOM_KIND_MAP = {"ACTION": "ACTION", "STATE": "STATE", "CLAIM": "CLAIM",
                  "VALUE": "VALUE", "CONDITION": "STATE", "ENTITY": "ENTITY",
                  "EVIDENCE": "EVIDENCE", "EFFECT": "EFFECT", "UNKNOWN": "STATE"}


def _literal_kind(atom) -> str:
    return _ATOM_KIND_MAP.get(atom.kind, "STATE")

FEATURE_FLAG_DEFAULT = False   # semantic_pipeline_v1


def rule_to_flat_structure(rule: RuleIR, normative_text: str) -> PolicyFlatStructure | None:
    """RuleIR -> incumbent PolicyFlatStructure.  Returns None when the rule
    cannot be represented without changing its meaning (abstain, never
    fabricate).  All quotes must be verbatim substrings of normative_text so
    the incumbent grounding discipline holds."""
    if rule.modality == "UNKNOWN":
        return None
    target = rule.target
    if target.kind == "UNKNOWN" and target.ref == "UNKNOWN":
        return None
    quote = target.text if target.text and target.text in normative_text else None
    if quote is None:
        return None
    normalized_key = target.ref if target.ref and target.ref != "UNKNOWN" and target.ref in normative_text else None
    target_literal = SemanticLiteral(_KIND_MAP.get(target.kind, "ACTION"), "POSITIVE",
                                     normalized_key, quote)

    condition_literals: list[SemanticLiteral] = []
    exception_literals: list[SemanticLiteral] = []
    unresolved = list(rule.unresolved)

    def emit_atoms(node, sink: list, negate: bool):
        if node is None:
            return
        for atom in node.leaves():
            atom_quote = atom.text if atom.text and atom.text in normative_text else None
            if atom_quote is None:
                unresolved.append(f"ungroundable atom {atom.ref}")
                continue
            atom_key = atom.ref if atom.ref and atom.ref != "UNKNOWN" and atom.ref in normative_text else None
            polarity = "NEGATED" if negate else "POSITIVE"
            sink.append(SemanticLiteral(_literal_kind(atom), polarity, atom_key, atom_quote))
            if atom.comparison is not None:
                unresolved.append(
                    f"comparison {atom.comparison.lhs.ref} {atom.comparison.op} "
                    f"{atom.comparison.rhs_literal} not expressible in V1 lowering")
            if atom.cardinality is not None and atom.cardinality.op != "NONE":
                unresolved.append(
                    f"cardinality {atom.cardinality.subject.ref} {atom.cardinality.op} "
                    f"{atom.cardinality.count} not expressible in V1 lowering")

    emit_atoms(rule.conditions, condition_literals, negate=False)
    # exceptions in the flat structure are compiled by compile_h0 into NEGATED
    # conditions (UNLESS semantics); keep them as positive literals with
    # relation UNLESS so the incumbent compiler applies its own semantics.
    for exception_node in rule.exceptions:
        emit_atoms(exception_node, exception_literals, negate=False)

    relation = "NONE"
    if rule.temporal.relation in {"BEFORE", "AFTER", "UNTIL", "WHILE"}:
        relation = rule.temporal.relation
        anchor = rule.temporal.anchor
        if anchor is not None and anchor.text and anchor.text in normative_text:
            # with relation BEFORE the TARGET is the action that must happen
            # first (incumbent H0 convention); the anchor becomes a condition
            anchor_key = anchor.ref if anchor.ref and anchor.ref != "UNKNOWN" and anchor.ref in normative_text else None
            condition_literals.append(
                SemanticLiteral("ACTION", "POSITIVE", anchor_key, anchor.text))
    elif exception_literals:
        relation = "UNLESS"
    elif condition_literals:
        relation = "ONLY_IF"

    quotes = [quote] + [literal.quote for literal in condition_literals] + \
        [literal.quote for literal in exception_literals]
    return PolicyFlatStructure(
        modality=MODALITY_MAP[rule.modality],
        actor=rule.actor or "UNKNOWN",
        regulated_kind=_KIND_MAP.get(target.kind, "ACTION"),
        facet="PRIMARY",
        relation=relation,
        target_clauses=(target_literal,),
        condition_literals=tuple(sorted(set(condition_literals),
                                        key=lambda literal: (literal.kind, literal.quote))),
        exception_literals=tuple(sorted(set(exception_literals),
                                        key=lambda literal: (literal.kind, literal.quote))),
        condition_mode="ALL",
        exception_mode="ALL",
        quantification="ALL",
        source_quotes=tuple(dict.fromkeys(quotes)),
        unresolved_terms=tuple(dict.fromkeys(unresolved)))


def compile_rule_ir_reading(rules: list[RuleIR], normative_text: str, state_contract: dict | None,
                            tool_catalog, reading_id: str = "policy:semantic_pipeline:r0"):
    """Compile the Phi rule set into ONE PolicyReading via the incumbent
    deterministic compiler.  Returns (PolicyReading | None, notes).  Merged
    rules are renumbered so every obligation id stays unique."""
    from dataclasses import replace as _replace
    from guardian_truth.vnext.e2e.e2e_types_v1 import PolicyReading
    from guardian_truth.vnext.e2e.policy_composition_v1 import compile_h0
    structures = []
    notes = {"rules_in": len(rules), "compiled": 0, "abstained": 0}
    for rule in rules:
        structure = rule_to_flat_structure(rule, normative_text)
        if structure is None:
            notes["abstained"] += 1
            continue
        structures.append(structure)
    if not structures:
        return None, notes
    merged_rules = []
    merged_unresolved: list[str] = []
    for index, structure in enumerate(structures):
        reading = compile_h0(structure, state_contract, tool_catalog,
                             reading_id=f"{reading_id}:s{index}")
        merged_unresolved.extend(reading.unresolved_terms)
        for rule in reading.rules:
            # renumber to keep obligation ids unique across merged structures
            merged_rules.append(_replace(rule, rule_id=f"policy:sp:rule{len(merged_rules)}"))
    notes["compiled"] = len(merged_rules)
    merged = PolicyReading(reading_id, "semantic_pipeline", tuple(merged_rules),
                           tuple(dict.fromkeys(merged_unresolved)))
    return merged, notes
