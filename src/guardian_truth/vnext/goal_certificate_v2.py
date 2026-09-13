"""Independent Goal certificate checker: no solver/compiler/evaluator imports."""

from dataclasses import asdict

from .certificates import CertificateCheck
from .goal_grounding_v2 import goal_context_errors
from .goal_native import GoalOperator
from .goal_call_membership_v2 import GoalCallMembershipAtom, prove_call_membership
from .goal_progress_v2 import PlanProgressAtom, PlanProgressKind, prove_plan_progress
from .goal_proof_records_v2 import ASSUMPTIONS
from .integrity import digest
from .ledger import LedgerIndex
from .proof_evidence import prove_atom
from .proof_records import AtomKind, ProofAtom, TimeMode, conjunction, disjunction, negate
from .types import CoreStatus, Truth


def checked_clause_value(clause, bindings, primitives):
    """Recompute the obligation directly from source-owned operator records."""
    def leaf(source, role):
        binding = bindings.get((source, role))
        return primitives[binding.atom.atom_id].value if binding else Truth.UNKNOWN
    def implies(left, right):
        return disjunction((negate(left), right))
    op, ids = clause.operator, clause.operands
    arities = {GoalOperator.PLAN_STEP: 1, GoalOperator.SCOPE: 1,
        GoalOperator.BEFORE: 2, GoalOperator.REQUIRES: 1, GoalOperator.FORBIDS: 1,
        GoalOperator.IF: 2, GoalOperator.ONLY_IF: 2, GoalOperator.UNLESS: 2,
        GoalOperator.NO_EXTRA_CONSTRAINT: 0}
    if op not in arities or len(ids) != arities[op] or clause.unresolved_terms or not clause.source_ids:
        return Truth.UNKNOWN
    if op is GoalOperator.PLAN_STEP:
        needed = ((ids[0], "active_step"), (ids[0], "step_satisfied"))
    elif op is GoalOperator.SCOPE:
        needed = ((ids[0], "scope_applicable"), (ids[0], "scope_compliant"))
    elif op is GoalOperator.BEFORE:
        needed = ((ids[0], "prior_completion"), (ids[1], "current_attempt"))
    else:
        needed = tuple((sid, "proposition") for sid in ids)
    if any(key not in bindings for key in needed):
        return Truth.UNKNOWN
    if op is GoalOperator.PLAN_STEP:
        return implies(leaf(ids[0], "active_step"), leaf(ids[0], "step_satisfied"))
    if op is GoalOperator.SCOPE:
        return implies(leaf(ids[0], "scope_applicable"), leaf(ids[0], "scope_compliant"))
    if op is GoalOperator.BEFORE:
        earlier, later = (bindings[key].atom for key in needed)
        prior_valid = (isinstance(earlier, PlanProgressAtom) and earlier.kind is PlanProgressKind.COMPLETED_STEP) or (
            isinstance(earlier, ProofAtom) and earlier.kind in {AtomKind.ACTION_COMPLETED, AtomKind.HISTORICAL_ACTION})
        current_valid = isinstance(later, GoalCallMembershipAtom) or (
            isinstance(later, ProofAtom) and later.kind in {AtomKind.CALL_ATTEMPTED, AtomKind.TARGET_CALL_MATCH}
            and later.time_mode is TimeMode.AT)
        if (not prior_valid or not current_valid or earlier.actor != later.actor
                or earlier.time_index >= later.time_index):
            return Truth.UNKNOWN
        return implies(leaf(ids[1], "current_attempt"), leaf(ids[0], "prior_completion"))
    if op is GoalOperator.REQUIRES:
        return leaf(ids[0], "proposition")
    if op is GoalOperator.FORBIDS:
        return negate(leaf(ids[0], "proposition"))
    if op in {GoalOperator.IF, GoalOperator.ONLY_IF}:
        return implies(leaf(ids[0], "proposition"), leaf(ids[1], "proposition"))
    if op is GoalOperator.UNLESS:
        return implies(negate(leaf(ids[0], "proposition")), negate(leaf(ids[1], "proposition")))
    return Truth.TRUE


def check_goal_certificate(certificate, context, ledger, registry):
    if certificate.version != "guardian-vnext-goal-proof-v2" or certificate.status is not CoreStatus.PROVED_ERROR:
        # This format does not contain authoritative NL closure for NO_ERROR.
        return CertificateCheck(False, ("INVALID_GOAL_CERTIFICATE_KIND_OR_SAFETY_CLOSURE",))
    errors = list(goal_context_errors(context, ledger, registry))
    expected_hashes = {"source_sha256": digest(asdict(context)), "ledger_sha256": digest(asdict(ledger)),
        "registry_sha256": digest([asdict(contract) for contract in registry.contracts])}
    for field, expected in expected_hashes.items():
        if getattr(certificate, field) != expected:
            errors.append("HASH_MISMATCH:" + field)
    if certificate.assumptions != ASSUMPTIONS:
        errors.append("CONDITIONAL_ASSUMPTIONS_CHANGED")
    choices = {choice.choice_id: choice for choice in context.choices}
    proofs = {proof.choice_id: proof for proof in certificate.world_proofs}
    if len(proofs) != len(certificate.world_proofs) or set(proofs) != set(choices):
        errors.append("BINDING_WORLD_DROPPED_OR_DUPLICATED")
    readings = {reading.reading_id: reading for reading in context.parsed.readings}
    index = LedgerIndex(ledger)
    for cid, choice in choices.items():
        proof, reading = proofs.get(cid), readings.get(choice.reading_id)
        if proof is None or reading is None:
            continue
        if proof.reading_id != choice.reading_id:
            errors.append("WORLD_READING_MISMATCH")
        expected_primitives = tuple(prove_plan_progress(binding.atom, context, ledger)
                                    if isinstance(binding.atom, PlanProgressAtom)
                                    else prove_call_membership(binding.atom, ledger)
                                    if isinstance(binding.atom, GoalCallMembershipAtom)
                                    else prove_atom(binding.atom, ledger, index, registry, context.absence_scopes)
                                    for binding in choice.bindings)
        if proof.primitives != expected_primitives:
            errors.append("PRIMITIVE_PROOF_RECHECK_FAILED")
        by_atom = {item.atom.atom_id: item for item in expected_primitives}
        if len(by_atom) != len(expected_primitives):
            errors.append("DUPLICATED_PRIMITIVE_IDENTITY")
            continue
        bindings = {(binding.source_id, binding.role): binding for binding in choice.bindings}
        safety = tuple((clause.clause_id, checked_clause_value(clause, bindings, by_atom)) for clause in reading.clauses)
        error = negate(conjunction(tuple(value for _, value in safety)))
        if proof.clause_safety != safety or proof.error_value is not error:
            errors.append("FORMULA_OR_AGGREGATION_RECHECK_FAILED")
        if error is not Truth.TRUE or any(value is Truth.UNKNOWN for _, value in safety):
            errors.append("WORLD_NOT_PROVED_ERROR_OR_MATERIAL_UNKNOWN")
    return CertificateCheck(not errors, tuple(dict.fromkeys(errors)))
