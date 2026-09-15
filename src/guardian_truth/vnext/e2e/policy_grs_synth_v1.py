"""GRS B1 synthesizer (spec 43) and deterministic canonicalizer (spec 47-49).

B1 sees ONLY the policy text and the grounded inventory, and composes the rule
structure using inventory IDs exclusively. The canonicalizer performs strictly
structure-preserving serialization repair (missing RULESET wrapper, whitespace,
canonical ordering, duplicate removal). It can never change modality,
relations, attachments or atoms.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..semantic import SemanticBackend, schema_valid
from .e2e_types_v1 import FrontendCandidate, GroundedInventory
from .policy_grs_dsl_v1 import DslError, DslRule, DslRuleset, parse_dsl, serialize_rule, serialize_ruleset

SYNTH_VERSION = "policy_grs_synth_e2e_v1"
CANONICALIZER_VERSION = "policy_grs_canonicalizer_e2e_v1"

SYNTH_SCHEMA = {
    "type": "object", "additionalProperties": False,
    "required": ["ruleset_dsl"],
    "properties": {"ruleset_dsl": {"type": "string", "minLength": 8}},
}

INSTRUCTIONS = (
    "You see a POLICY text and its grounded semantic inventory (facts F#, modality "
    "markers M#, relation markers R#). Compose the policy rule structure using ONLY the "
    "inventory IDs. Output DSL text exactly in this grammar: "
    "RULESET(RULE(MODALITY, F#, MODIFIER*), ...) where MODALITY is PERMIT, FORBID or "
    "REQUIRE; MODIFIER is WHEN(EXPR), UNLESS(EXPR), ACTOR(F#), BEFORE(EXPR), AFTER(EXPR), "
    "UNTIL(EXPR), SCOPE(F#), TOGETHER(EXPR) or CHOICE(EXPR); EXPR is F#, NOT(F#), "
    "AND(F#,F#,...) or OR(F#,F#,...). You decide modality, target attachment, condition "
    "attachment, exception attachment, actor attachment and temporal relations. Never "
    "invent new IDs; never use free text as a leaf. This is a candidate interpretation, "
    "NOT a verdict. Return one JSON object with key ruleset_dsl containing the DSL text.")


@dataclass(frozen=True)
class SynthResult:
    candidate: FrontendCandidate
    ruleset: DslRuleset | None
    raw_dsl: str | None = None
    canonicalization_notes: tuple[str, ...] = ()


def _canonicalize(raw: str, known_ids: frozenset[str]) -> tuple[DslRuleset, tuple[str, ...]]:
    """Structure-preserving serialization repair only (spec 47-48)."""
    notes = []
    text_value = raw.strip()
    # Repair 1: strip code fences / surrounding prose keeping the DSL body.
    if "RULESET(" in text_value:
        start = text_value.find("RULESET(")
        end = text_value.rfind(")")
        if start > 0 or end < len(text_value) - 1:
            notes.append("trimmed surrounding text")
            text_value = text_value[start:end + 1]
    else:
        # Repair 2: structurally implied RULESET wrapper for bare RULE(...) lists.
        if "RULE(" in text_value:
            text_value = "RULESET(" + text_value.strip().rstrip(",") + ")"
            notes.append("inserted structurally implied RULESET wrapper")
        else:
            raise DslError("no RULE or RULESET construct found")
    ruleset = parse_dsl(text_value, known_ids)
    # Repair 3: canonical ordering of rules and duplicate identical removal.
    ordered = tuple(sorted(ruleset.rules, key=lambda rule: serialize_rule(rule)))
    deduped = tuple(dict.fromkeys(ordered))
    if ordered != ruleset.rules:
        notes.append("canonical rule ordering")
    if len(deduped) != len(ordered):
        notes.append("removed duplicate identical rules")
    return DslRuleset(deduped), tuple(notes)


def synthesize(policy_text: str, inventory: GroundedInventory, backend: SemanticBackend) -> SynthResult:
    known = frozenset(atom.atom_id for atom in inventory.facts)
    if not policy_text.strip() or not inventory.facts:
        return SynthResult(FrontendCandidate("grs_synth", False, "COMPILE", "empty policy or inventory"), None)
    payload = {
        "policy": policy_text,
        "grounded_inventory": {
            "facts": [{"id": atom.atom_id, "kind": atom.kind, "meaning": atom.meaning, "quote": atom.quote}
                      for atom in inventory.facts],
            "modality_markers": [{"id": marker.marker_id, "surface": marker.surface, "quote": marker.quote}
                                 for marker in inventory.modality_markers],
            "relation_markers": [{"id": marker.marker_id, "surface": marker.surface, "quote": marker.quote}
                                 for marker in inventory.relation_markers]},
        "instructions": INSTRUCTIONS}
    proposal = backend.propose("policy_grs_synth", payload, SYNTH_SCHEMA)
    if proposal.transport_status != "SUCCESS":
        return SynthResult(FrontendCandidate("grs_synth", False, "TRANSPORT", proposal.error_category), None)
    if proposal.schema_status != "VALID" or not schema_valid(proposal.value, SYNTH_SCHEMA):
        return SynthResult(FrontendCandidate("grs_synth", False, "SCHEMA"), None)
    raw = proposal.value["ruleset_dsl"]
    try:
        ruleset, notes = _canonicalize(raw, known)
    except DslError as error:
        return SynthResult(FrontendCandidate("grs_synth", False, "COMPILE", str(error)), None, raw)
    return SynthResult(FrontendCandidate("grs_synth", True, None), ruleset, raw, notes)
