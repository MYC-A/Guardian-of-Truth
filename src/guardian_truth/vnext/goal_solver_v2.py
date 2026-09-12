"""Certificate-gated Goal-layer solver; no binary fallback inside reasoning."""

from dataclasses import asdict

from .goal_certificate_v2 import check_goal_certificate
from .goal_formula import compile_goal_clause, evaluate_compiled_clause
from .goal_grounding_v2 import goal_context_errors
from .goal_progress_v2 import PlanProgressAtom, prove_plan_progress
from .goal_proof_records_v2 import ASSUMPTIONS, GoalLayerDecision, GoalProofCertificate, GoalWorldProof
from .integrity import digest
from .ledger import LedgerIndex
from .proof_evidence import prove_atom
from .proof_records import conjunction, negate
from .types import CoreStatus, Reason, Truth, consensus


def decide_goal_layer(context, ledger, registry, *, max_worlds=4096):
    if type(max_worlds) is not int or max_worlds < 1:
        raise ValueError("positive material-world budget required")
    grounding_errors = goal_context_errors(context, ledger, registry)
    if grounding_errors or len(context.choices) > max_worlds:
        errors = grounding_errors + (("WORLD_BUDGET_EXCEEDED",) if len(context.choices) > max_worlds else ())
        return GoalLayerDecision(CoreStatus.UNRESOLVED, (), (Reason.GOAL_PLAN_AMBIGUOUS, Reason.EVIDENCE_INCOMPLETE),
                                 None, None, errors)
    readings = {reading.reading_id: reading for reading in context.parsed.readings}
    index, worlds, reasons = LedgerIndex(ledger), [], []
    for choice in context.choices:
        reading = readings[choice.reading_id]
        primitives = tuple(prove_plan_progress(binding.atom, context, ledger)
                           if isinstance(binding.atom, PlanProgressAtom)
                           else prove_atom(binding.atom, ledger, index, registry, context.absence_scopes)
                           for binding in choice.bindings)
        by_atom = {primitive.atom.atom_id: primitive for primitive in primitives}
        bindings = {(binding.source_id, binding.role): binding.atom for binding in choice.bindings}
        if len(by_atom) != len(primitives):
            return GoalLayerDecision(CoreStatus.UNRESOLVED, (), (Reason.ENTITY_AMBIGUOUS,), None, None,
                                     ("DUPLICATED_PRIMITIVE_IDENTITY",))
        compiled = tuple(compile_goal_clause(clause, bindings) for clause in reading.clauses)
        safety = tuple((item.clause.clause_id, evaluate_compiled_clause(item, lambda atom: by_atom[atom.atom_id].value))
                       for item in compiled)
        missing = any(item.unresolved_terms for item in compiled) or any(value is Truth.UNKNOWN for _, value in safety)
        # A known violation cannot hide another material untyped obligation.
        error = Truth.UNKNOWN if missing else negate(conjunction(tuple(value for _, value in safety)))
        worlds.append(GoalWorldProof(choice.choice_id, choice.reading_id, safety, primitives, error))
        for primitive in primitives:
            reasons.extend(primitive.reasons)
        if missing:
            reasons.append(Reason.EVIDENCE_INCOMPLETE)
    status = consensus(tuple(world.error_value for world in worlds), material_space_complete=True)
    certificate = None
    if status is CoreStatus.PROVED_NO_ERROR:
        # EMPIRICALLY_COVERED is not an authoritative closed NL universe.
        status = CoreStatus.UNRESOLVED
        reasons.append(Reason.GOAL_PLAN_AMBIGUOUS)
    if status is not CoreStatus.PROVED_ERROR:
        if status is CoreStatus.UNRESOLVED and not reasons:
            reasons.append(Reason.GOAL_PLAN_AMBIGUOUS)
        return GoalLayerDecision(status, tuple(worlds), tuple(dict.fromkeys(reasons)), None, None)
    certificate = GoalProofCertificate("guardian-vnext-goal-proof-v2", status, digest(asdict(context)),
        digest(asdict(ledger)), digest([asdict(contract) for contract in registry.contracts]), tuple(worlds), ASSUMPTIONS)
    check = check_goal_certificate(certificate, context, ledger, registry)
    if not check.valid:
        return GoalLayerDecision(CoreStatus.UNRESOLVED, tuple(worlds), (Reason.EVIDENCE_INCOMPLETE,),
                                 certificate, False, check.errors)
    return GoalLayerDecision(status, tuple(worlds), tuple(dict.fromkeys(reasons)), certificate, True)
