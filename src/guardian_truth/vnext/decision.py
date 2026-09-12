"""Certificate-gated Core result. Binary policy belongs to adapters, not here."""

from __future__ import annotations

from dataclasses import dataclass

from .certificates import (CertificateCheck, CertificateContext, check_certificate,
                           completeness_assumptions)
from .ledger import EvidenceLedger
from .proof_records import ProofCertificate, ProofProblem, WorldProof
from .solver import make_certificate, solve
from .tools import ContractRegistry
from .types import CoreStatus, Diagnostics, Disposition, Reason, Truth


@dataclass(frozen=True)
class CertifiedCoreResult:
    status: CoreStatus
    world_proofs: tuple[WorldProof, ...]
    certificate: ProofCertificate | None
    certificate_check: CertificateCheck | None
    diagnostics: Diagnostics

    def __post_init__(self):
        if self.status in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR} and (
                self.certificate is None or self.certificate_check is None or not self.certificate_check.valid
                or self.certificate.status is not self.status):
            raise ValueError("definitive Core verdict requires validated certificate")


def decide(problem: ProofProblem, ledger: EvidenceLedger, registry: ContractRegistry, *,
            context: CertificateContext, semantic_reasons: tuple[Reason, ...] = (),
            missing_evidence: tuple[str, ...] = (), attempted_escalations: tuple[str, ...] = ()) -> CertifiedCoreResult:
    result = solve(problem, ledger, registry)
    certificate = make_certificate(result, problem, ledger, registry, prompt=context.prompt, response=context.response,
        completeness_assumptions=completeness_assumptions(context, problem, ledger), validation_context=context)
    checked = check_certificate(certificate, context, problem, ledger, registry) if certificate else None
    reasons = list(dict.fromkeys((*semantic_reasons, *result.reasons)))
    status = result.status
    if checked and not checked.valid:
        status = CoreStatus.UNRESOLVED
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
        missing_evidence = (*missing_evidence, *checked.errors)
        certificate = None
    if status is CoreStatus.UNRESOLVED and not reasons:
        reasons.append(Reason.EVIDENCE_INCOMPLETE)
    blocked_atoms = {primitive.atom.atom_id for world in result.world_proofs for primitive in world.primitives
                     if primitive.value is Truth.UNKNOWN}
    blocked_claims = tuple(dict.fromkeys(obligation.claim_id for world in problem.worlds for obligation in world.obligations
                          if obligation.claim_id is not None and obligation.atom.atom_id in blocked_atoms))
    blocked_claims = tuple(dict.fromkeys((*blocked_claims,
        *(claim.claim_id for claim in context.claims if claim.disposition is Disposition.UNKNOWN_SEMANTICS))))
    blocked_hypotheses = tuple(dict.fromkeys(obligation.hypothesis_id for world in problem.worlds
                               for obligation in world.obligations if world.unresolved_reasons
                               or obligation.atom.atom_id in blocked_atoms))
    blocked_hypotheses = tuple(dict.fromkeys((*blocked_hypotheses,
        *(choice for world in problem.worlds if world.unresolved_reasons for choice in world.choices))))
    if status is not CoreStatus.UNRESOLVED:
        diagnostics = Diagnostics(None, attempted_escalations=attempted_escalations)
    else:
        priorities = [Reason.TRANSPORT_ERROR, Reason.SCHEMA_ERROR, Reason.CLAIM_UNTYPED,
            Reason.POLICY_NO_INTERPRETATION, Reason.POLICY_OPEN_SEMANTICS, Reason.POLICY_AMBIGUOUS,
            Reason.GOAL_PLAN_AMBIGUOUS, Reason.ENTITY_AMBIGUOUS, Reason.ENTITY_UNBOUND,
            Reason.TIME_UNBOUND, Reason.SOURCE_UNBOUND, Reason.TOOL_VERSION_MISMATCH,
            Reason.TOOL_EFFECT_UNKNOWN, Reason.CAUSALITY_UNPROVED, Reason.TEMPORAL_AMBIGUITY,
            Reason.EVIDENCE_INCOMPLETE]
        unique = tuple(dict.fromkeys(reasons))
        primary = min(unique, key=lambda code: priorities.index(code))
        diagnostics = Diagnostics(primary, tuple(reason for reason in unique if reason is not primary),
            blocked_claims, blocked_hypotheses, tuple(dict.fromkeys((*missing_evidence, *sorted(blocked_atoms)))),
            attempted_escalations)
    return CertifiedCoreResult(status, result.world_proofs, certificate, checked, diagnostics)
