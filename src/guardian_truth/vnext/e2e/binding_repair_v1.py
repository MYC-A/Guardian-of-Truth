"""E2E-agent-1 causal repair A3: source-backed catalog-identity binding.

THE BOTTLENECK: the semantic binding pass abstains on policy atoms that no
trajectory call exercises (verify_sender, approve_exception, hold_shipment,
...), so the lowering marks the affected rules POLICY_OPEN_SEMANTICS and
their obligations are never constructed — at-least-once requirements and
gated prohibitions over those atoms become invisible.

THE REPAIR: for an UNBOUND semantic atom of kind ACTION/EVENT whose suffix
is EXACTLY a catalog tool name, establish the correspondence

    semantic atom X  <->  tool T          (catalog-identity)

This correspondence is schema-grounded (the atom catalog and the tool
catalog are both supplied sources) and strictly deterministic: exact name
identity only, no fuzzy matching, no semantic guessing.  The rule

    catalog tool identity  !=  observed action

is enforced by construction: the candidate carries NO argument checks and
NO entity path, so the deterministic prover still decides from the ledger
alone whether T was called (a CALL_ATTEMPTED proof needs an actual ledger
call; absence of a call is proven only under a complete-history absence
scope).  The candidate only gives the lowering the tool IDENTITY it needs
to build its obligations.

Safety shape:
  - at-least-once requirements scan the real ledger (satisfied only by an
    actual assistant call to T);
  - target-prohibition matches still require an actual call event;
  - entity-scoping is NOT invented: event-atoms from catalog-identity
    candidates use the E2E V1 wildcard entity (any assistant call to T),
    which can only under-trigger (an unrelated same-tool call satisfies a
    gate) — never over-trigger;
  - STATE atoms never get catalog-identity candidates (state evidence
    needs an observation binding, which no catalog name can supply).

Every repair is logged, hashed into the certificate context, and the
checker re-verifies each rule before trusting the repaired binding.
"""
from __future__ import annotations

from dataclasses import dataclass

from .goal_types_v1 import AtomBindingCandidate, BindingLevel, BindingRecord

CATALOG_IDENTITY_KINDS = ("action", "event")


@dataclass(frozen=True)
class BindingRepair:
    unit_id: str
    tool: str
    rule: str = "CATALOG_IDENTITY"


def apply_catalog_identity_binding(binding: BindingRecord,
                                   tool_catalog: tuple[str, ...],
                                   known_units: tuple[str, ...] = ()):
    """Return (repaired_binding, repairs).  The original record is untouched.

    A unit is repaired only when it is currently UNBOUND — either listed in
    unbound_units or absent from the record entirely (both are semantic-pass
    abstention shapes) — never when the pass produced genuine candidates or
    genuine ambiguity; its kind prefix must be action:/event: and its
    suffix must be exactly a catalog tool name."""
    tools = set(tool_catalog)
    bound = {unit for unit, _ in binding.atom_bindings}
    unbound_listed = set(binding.unbound_units)
    universe = tuple(dict.fromkeys((*binding.unbound_units, *known_units)))
    repaired_candidates = list(binding.atom_bindings)
    still_unbound = []
    repairs: list[BindingRepair] = []
    for unit in universe:
        prefix, _, suffix = unit.partition(":")
        repairable = (unit not in bound and prefix in CATALOG_IDENTITY_KINDS
                      and suffix in tools)
        if not repairable:
            if unit in unbound_listed:
                still_unbound.append(unit)
            continue
        candidate = AtomBindingCandidate(
            unit, suffix, BindingLevel.CATALOG_IDENTITY, (), None, None, None, (), ())
        repaired_candidates.append((unit, (candidate,)))
        repairs.append(BindingRepair(unit, suffix))
    if not repairs:
        return binding, ()
    # deterministic order: by unit id, appended after the original bindings
    repaired_candidates.sort(key=lambda pair: pair[0])
    repaired = BindingRecord(tuple(repaired_candidates), binding.outcome_bindings,
                             tuple(still_unbound), binding.failures)
    return repaired, tuple(repairs)


def repair_rules_ok(repairs, binding: BindingRecord, tool_catalog: tuple[str, ...]) -> tuple[str, ...]:
    """Checker-side re-verification of every declared repair rule."""
    errors = []
    tools = set(tool_catalog)
    bound_units = {unit for unit, _ in binding.atom_bindings}
    for repair in repairs:
        prefix, _, suffix = repair.unit_id.partition(":")
        if repair.rule != "CATALOG_IDENTITY":
            errors.append("UNKNOWN_BINDING_REPAIR_RULE:" + repair.unit_id)
            continue
        if prefix not in CATALOG_IDENTITY_KINDS:
            errors.append("BINDING_REPAIR_KIND_NOT_CATALOGABLE:" + repair.unit_id)
        if suffix != repair.tool or repair.tool not in tools:
            errors.append("BINDING_REPAIR_TOOL_NOT_CATALOG_IDENTITY:" + repair.unit_id)
        if repair.unit_id not in bound_units:
            errors.append("BINDING_REPAIR_NOT_APPLIED:" + repair.unit_id)
        else:
            candidates = next(candidates for unit, candidates in binding.atom_bindings
                              if unit == repair.unit_id)
            if len(candidates) != 1 or candidates[0].tool != repair.tool \
                    or candidates[0].level is not BindingLevel.CATALOG_IDENTITY \
                    or candidates[0].argument_checks or candidates[0].observation is not None \
                    or candidates[0].entity_path:
                errors.append("BINDING_REPAIR_CANDIDATE_SHAPE_INVALID:" + repair.unit_id)
    return tuple(dict.fromkeys(errors))
