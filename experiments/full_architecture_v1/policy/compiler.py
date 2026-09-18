"""full_architecture_v1 — Phase C: RuleIR -> NeutralInterpretation compiler
(directive §15 "RuleIR -> Clingo policy compiler").

Input:  RuleIR candidates (semantic_pipeline_v1/rule_ir.py) + binding
        resolutions (Phase 11 binder output), all source-grounded.
Output: NeutralInterpretation worlds for the NeutralCoreInput contract.

Lowering rules (ALL conservative — never guess):
  * modality FORBID/REQUIRE  -> obligation (target_level ATTEMPT, the
    incumbent's response-audit convention; actor assistant)
  * modality ALLOW           -> skipped (permission carries no obligation)
  * modality UNKNOWN         -> unresolved marker (blocks the world)
  * target ref BOUND         -> the bound tool/action name
  * target ref AMBIGUOUS     -> LOCAL CHOICE: one variant per candidate
    (directive §16 compact local choices; the compiler materializes the
    cross product CAPPED at MAX_INTERPRETATIONS and records the cap as a
    φ-coverage risk, never silently dropping a choice axis)
  * target ref UNKNOWN       -> unresolved marker
  * STATE-target rules       -> unresolved marker (RULEIR_REPRESENTATION_
    LIMIT: no state-target obligation primitive in the neutral contract)
  * condition atoms:
      ACTION (bound)   -> attempted atom
      comparison       -> comparison atom (lhs bound, rhs literal parsed)
      cardinality      -> cardinality atom
      STATE w/o value  -> unresolved marker + leaf omitted (UNKNOWN conjunct)
      VALUE/CLAIM/ENTITY/EVIDENCE -> unresolved marker (not an S2 query)
  * temporal BEFORE/UNTIL/AFTER -> anchor gate (anchor bound) else marker
  * temporal WHILE/UNKNOWN   -> marker
  * rule.unresolved          -> markers (S8: UNKNOWN conjuncts)

Every marker is a string that names the exact unresolved thing, so the
failure taxonomy (directive §35) can point at the failing layer.
"""

from __future__ import annotations

import json
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

_FULLARCH = Path(__file__).resolve().parents[1]
_BAKEOFF = _FULLARCH.parent / "core_engine_bakeoff_v1"
_SEMANTIC = _FULLARCH.parent / "semantic_pipeline_v1"
for p in (str(_BAKEOFF), str(_SEMANTIC)):
    if p not in sys.path:
        sys.path.insert(0, p)

from neutral_types import (  # noqa: E402
    CondNode, NeutralAtom, NeutralCardinality, NeutralComparison,
    NeutralInterpretation, NeutralRule,
)
from rule_ir import Atom as RuleAtom, ConditionNode, Ref, RuleIR  # noqa: E402

MAX_INTERPRETATIONS = 64          # §16 cap; beyond -> truncation is recorded
_TARGET_KINDS_WITH_OBLIGATION = {"ACTION"}
END = 10**9


@dataclass(frozen=True)
class BindingResolution:
    """One resolved binding for a Ref: tool/action name (action kind) or
    state field (state kind).  Produced by the Phase-11 binder."""
    semantic_text: str
    kind: str                      # action | state
    status: str                    # BOUND | AMBIGUOUS | UNKNOWN
    names: tuple[str, ...] = ()


def _ref_key(ref: Ref) -> str:
    return (ref.ref if ref.ref and ref.ref != "UNKNOWN"
            else f"text:{ref.text}")


def _lookup(resolutions: dict[str, BindingResolution], ref: Ref) \
        -> BindingResolution | None:
    for key in (_ref_key(ref), f"text:{ref.text}", ref.text):
        if key in resolutions:
            return resolutions[key]
    return None


# ------------------------------------------------------------------ lowering

def _atom_lower(atom: RuleAtom, resolutions, markers: list[str],
                rule_id: str) -> NeutralAtom | None:
    """Lower ONE RuleIR condition atom; unresolved -> marker, None."""
    if atom.comparison is not None:
        lhs = atom.comparison.lhs
        resolution = _lookup(resolutions, lhs)
        if resolution is None or resolution.status != "BOUND" or not resolution.names:
            markers.append(f"rule:{rule_id}:cmp-lhs-unbound:{lhs.text}")
            return None
        try:
            rhs = json.loads(atom.comparison.rhs_literal)
        except ValueError:
            markers.append(f"rule:{rule_id}:cmp-rhs-literal:{atom.comparison.rhs_literal}")
            return None
        return NeutralAtom(
            atom_id=f"a:{rule_id}:{atom.atom_key()}", kind="comparison",
            entity="*", predicate=resolution.names[0],
            comparison=NeutralComparison(
                predicate=resolution.names[0], op=atom.comparison.op,
                rhs_literal=rhs))
    if atom.cardinality is not None and atom.cardinality.op != "NONE":
        subject = atom.cardinality.subject
        resolution = _lookup(resolutions, subject)
        if resolution is None or resolution.status != "BOUND" or not resolution.names:
            markers.append(f"rule:{rule_id}:card-subject-unbound:{subject.text}")
            return None
        if atom.cardinality.count is None:
            markers.append(f"rule:{rule_id}:card-count-missing:{subject.text}")
            return None
        return NeutralAtom(
            atom_id=f"a:{rule_id}:{atom.atom_key()}", kind="cardinality",
            entity="*", actor="assistant",
            action=resolution.names[0],
            cardinality=NeutralCardinality(
                subject=resolution.names[0], op=atom.cardinality.op,
                count=atom.cardinality.count))
    if atom.kind == "ACTION":
        resolution = _lookup(resolutions, Ref(kind="ACTION", text=atom.text,
                                              ref=atom.ref))
        if resolution is not None and resolution.status in ("BOUND", "AMBIGUOUS") \
                and resolution.names:
            # inside a fixed interpretation variant the local choice was
            # already materialized by the rule-level splitter; take the
            # first candidate (the AMBIGUOUS case is handled at target level)
            return NeutralAtom(
                atom_id=f"a:{rule_id}:{atom.atom_key()}", kind="attempted",
                entity="*", actor="assistant", action=resolution.names[0],
                time_index=END)
        markers.append(f"rule:{rule_id}:action-unbound:{atom.text}")
        return None
    # STATE / VALUE / CLAIM / ENTITY / EVIDENCE without a comparison or
    # cardinality: no S2 query primitive carries "bare state" — honest marker
    markers.append(f"rule:{rule_id}:atom-not-representable:{atom.kind}:{atom.text}")
    return None


def _tree_lower(node: ConditionNode | None, resolutions, markers: list[str],
                rule_id: str) -> CondNode | None:
    """Lower a RuleIR condition tree; drops unresolvable leaves (their
    markers already make the world UNKNOWN — dropping only the leaf keeps
    the remaining structure evaluable instead of collapsing to nothing)."""
    if node is None:
        return None
    if node.atom is not None:
        atom = _atom_lower(node.atom, resolutions, markers, rule_id)
        if atom is None:
            return None
        return CondNode(atom=atom)
    if node.not_ is not None:
        child = _tree_lower(node.not_, resolutions, markers, rule_id)
        if child is None:
            return None
        return CondNode(not_=child)
    children_all = node.all_
    children_any = node.any_
    if children_all is not None:
        lowered = [_tree_lower(child, resolutions, markers, rule_id)
                   for child in children_all]
        lowered = [child for child in lowered if child is not None]
        if not lowered:
            return None
        return CondNode(all_=tuple(lowered))
    if children_any is not None:
        lowered = [_tree_lower(child, resolutions, markers, rule_id)
                   for child in children_any]
        lowered = [child for child in lowered if child is not None]
        if not lowered:
            return None
        return CondNode(any_=tuple(lowered))
    return None


def _rule_variants(rule: RuleIR, resolutions) -> list[NeutralRule] | None:
    """One variant per ambiguous TARGET binding; markers otherwise.

    Returns None + markers when the rule cannot lower at all (the caller
    turns the rule into unresolved markers only)."""
    if rule.modality not in ("FORBID", "REQUIRE"):
        return None
    if rule.target.kind not in _TARGET_KINDS_WITH_OBLIGATION:
        return None
    resolution = _lookup(resolutions, rule.target)
    names: tuple[str, ...] = ()
    if resolution is not None:
        if resolution.status == "BOUND" and resolution.names:
            names = (resolution.names[0],)
        elif resolution.status == "AMBIGUOUS" and resolution.names:
            names = tuple(resolution.names)     # local choice (§16)
    if not names:
        return None

    temporal = "NONE"
    anchor_action = ""
    anchor_entity = "*"
    if rule.temporal.relation in ("BEFORE", "UNTIL", "AFTER"):
        temporal = rule.temporal.relation
        if rule.temporal.anchor is not None:
            anchor_resolution = _lookup(resolutions, rule.temporal.anchor)
            if anchor_resolution is not None and anchor_resolution.names:
                anchor_action = anchor_resolution.names[0]
        if not anchor_action:
            return None                          # anchor unbound -> markers

    out = []
    for name in names:
        out.append(NeutralRule(
            rule_id=rule.rule_id, modality=rule.modality, action=name,
            entity="*", actor="assistant", target_level="ATTEMPT"))
    return out


def compile_rule_set(rules: list[RuleIR],
                     resolutions: dict[str, BindingResolution],
                     case_id: str = "case") -> tuple[tuple[NeutralInterpretation, ...],
                                                     dict[str, Any]]:
    """Compile a whole candidate rule set into interpretation worlds.

    Choice axes: each rule with an AMBIGUOUS target contributes its
    candidate set; interpretations are the cross product (capped, §16).
    All other rules join EVERY interpretation unchanged.
    """
    fixed_rules: list[NeutralRule] = []
    fixed_markers: list[str] = []
    choice_rules: list[list[NeutralRule]] = []
    choice_labels: list[str] = []

    for rule in rules:
        markers: list[str] = list(rule.unresolved)
        variants = _rule_variants(rule, resolutions)
        if variants is None:
            # rule cannot lower as an obligation: record why (markers only)
            if rule.modality == "UNKNOWN":
                markers.append(f"rule:{rule.rule_id}:modality-unknown")
            elif rule.modality == "ALLOW":
                pass                        # permission: no obligation, no marker
            elif rule.target.kind not in _TARGET_KINDS_WITH_OBLIGATION:
                markers.append(
                    f"rule:{rule.rule_id}:target-kind-not-representable:"
                    f"{rule.target.kind}")
            else:
                markers.append(f"rule:{rule.rule_id}:target-unbound:"
                               f"{rule.target.text}")
            if rule.temporal.relation in ("WHILE", "UNKNOWN"):
                markers.append(f"rule:{rule.rule_id}:temporal-unknown")
            fixed_markers.extend(markers)
            continue

        # lower conditions/exceptions ONCE per variant target name
        per_variant: list[NeutralRule] = []
        variant_markers: list[str] = list(rule.unresolved)
        for variant in variants:
            conditions = _tree_lower(rule.conditions, resolutions,
                                     variant_markers, rule.rule_id)
            exceptions = tuple(
                lowered for lowered in (
                    _tree_lower(exception, resolutions, variant_markers,
                                rule.rule_id)
                    for exception in rule.exceptions)
                if lowered is not None)
            if rule.temporal.relation in ("WHILE", "UNKNOWN"):
                variant_markers.append(f"rule:{rule.rule_id}:temporal-unknown")
            per_variant.append(NeutralRule(
                rule_id=variant.rule_id, modality=variant.modality,
                action=variant.action, entity=variant.entity,
                actor=variant.actor, target_level=variant.target_level,
                conditions=conditions, exceptions=exceptions,
                temporal=variant.temporal,
                temporal_anchor_action=variant.temporal_anchor_action,
                temporal_anchor_entity=variant.temporal_anchor_entity))
        if len(per_variant) == 1:
            fixed_rules.append(per_variant[0])
            fixed_markers.extend(variant_markers)
        else:
            choice_rules.append(per_variant)
            choice_labels.append(rule.rule_id)
            fixed_markers.extend(variant_markers)   # markers shared by all variants

    # cross product with cap
    combos: list[tuple[NeutralRule, ...]] = [()]
    truncated = False
    for variants in choice_rules:
        combos = [combo + (variant,) for combo in combos
                  for variant in variants]
        if len(combos) > MAX_INTERPRETATIONS:
            combos = combos[:MAX_INTERPRETATIONS]
            truncated = True
            break

    interpretations: list[NeutralInterpretation] = []
    for index, combo in enumerate(combos):
        interp_rules = tuple(fixed_rules) + tuple(combo)
        markers = list(fixed_markers)
        if truncated:
            markers.append("phi-coverage:interpretation-cap-reached:"
                           f"{MAX_INTERPRETATIONS}")
        interpretations.append(NeutralInterpretation(
            interp_id=f"i{index}", rules=interp_rules,
            unresolved=tuple(markers)))

    if not interpretations:
        interpretations.append(NeutralInterpretation(
            interp_id="i0", rules=(), unresolved=tuple(fixed_markers) or
            ("phi-empty:no-rules-extracted",)))

    stats = {
        "rules_total": len(rules),
        "rules_lowered": len(fixed_rules) + sum(len(v) for v in choice_rules),
        "choice_axes": choice_labels,
        "interpretations": len(interpretations),
        "interpretation_cap_truncated": truncated,
        "markers": fixed_markers,
    }
    return tuple(interpretations), stats


def source_refs_from_rules(rules: list[RuleIR]) -> dict[str, dict]:
    """rule_id -> source span records for the certificate layer (§17)."""
    out: dict[str, dict] = {}
    for rule in rules:
        spans = []
        for span in rule.source_spans:
            spans.append({"document": span.document, "start": span.start,
                          "end": span.end, "quote": span.quote})
        if spans:
            out[rule.rule_id] = {"spans": spans,
                                  "target_text": rule.target.text}
    return out
