"""Deterministic four-valued obligations and exhaustive interpretation aggregation."""

from __future__ import annotations

from dataclasses import asdict
import itertools

from .integrity import digest
from .ledger import EvidenceLedger, LedgerIndex
from .proof_evidence import prove_atom
from .proof_records import (ProofCertificate, ProofProblem, SolverResult, WorldProof,
                            conjunction, disjunction, negate)
from .tools import ContractRegistry
from .types import CoreStatus, Reason, Truth, consensus


def world_space_complete(problem: ProofProblem) -> bool:
    if (len({axis.name for axis in problem.axes}) != len(problem.axes)
            or any(not axis.choice_ids or len(set(axis.choice_ids)) != len(axis.choice_ids)
                   or not axis.universe_source or axis.enumeration_complete is not True for axis in problem.axes)):
        return False
    expected = set(itertools.product(*(axis.choice_ids for axis in problem.axes)))
    actual = [world.choices for world in problem.worlds]
    return bool(problem.worlds) and len({world.world_id for world in problem.worlds}) == len(problem.worlds) and len(actual) == len(set(actual)) and set(actual) == expected


def solve(problem: ProofProblem, ledger: EvidenceLedger, registry: ContractRegistry) -> SolverResult:
    index = LedgerIndex(ledger)
    proofs, reasons = [], []
    for world in problem.worlds:
        primitives, safety = [], []
        if world.unresolved_reasons:
            reasons.extend(world.unresolved_reasons)
        for obligation in world.obligations:
            condition_proofs = tuple(prove_atom(atom, ledger, index, registry, problem.absence_scopes)
                                     for atom in obligation.conditions)
            atom_proof = prove_atom(obligation.atom, ledger, index, registry, problem.absence_scopes)
            primitives.extend((*condition_proofs, atom_proof))
            required = atom_proof.value if obligation.must_be_true else negate(atom_proof.value)
            # Material implication over explicit positive/negative evidence.
            antecedent = conjunction(tuple(item.value for item in condition_proofs))
            obligation_safety = disjunction((negate(antecedent), required))
            safety.append((obligation.obligation_id, obligation_safety))
            for primitive in (*condition_proofs, atom_proof):
                reasons.extend(primitive.reasons)
        # Unknown material obligations cannot be erased by an empty plan.
        values = tuple(value for _, value in safety) + ((Truth.UNKNOWN,) if world.unresolved_reasons else ())
        error = Truth.UNKNOWN if world.unresolved_reasons else negate(conjunction(values))
        proofs.append(WorldProof(world.world_id, world.choices, error, tuple(safety), tuple(primitives)))
    complete = world_space_complete(problem)
    if not complete:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    status = consensus(tuple(proof.error_value for proof in proofs), material_space_complete=complete)
    if status is CoreStatus.UNRESOLVED and not reasons:
        reasons.append(Reason.POLICY_AMBIGUOUS)
    return SolverResult(status, tuple(proofs), tuple(dict.fromkeys(reasons)))


def make_certificate(result: SolverResult, problem: ProofProblem, ledger: EvidenceLedger,
                     registry: ContractRegistry, *, prompt: str, response: str,
                     completeness_assumptions: tuple[tuple[str, str], ...],
                     validation_context) -> ProofCertificate | None:
    if result.status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return None
    return ProofCertificate("guardian-vnext-proof-v1", result.status,
        digest(asdict(validation_context)), digest(asdict(ledger)),
        digest([asdict(contract) for contract in registry.contracts]), digest(asdict(problem)),
        result.world_proofs, completeness_assumptions)
