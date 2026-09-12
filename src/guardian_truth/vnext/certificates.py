"""Independent deterministic proof-certificate checker, with no solver import."""

from __future__ import annotations

from dataclasses import asdict, dataclass
import itertools

from guardian_truth.cycle2.claims import response_spans
from .binder import bind_claim
from .integrity import digest
from .ledger import EvidenceLedger, LedgerIndex
from .normalize import normalize
from .proof_evidence import prove_atom
from .proof_records import ProofCertificate, ProofProblem, conjunction, disjunction, negate
from .tools import ContractRegistry
from .types import CoreStatus, Disposition, EvaluationHypothesis, ToolIdentity, Truth, TypedClaim


@dataclass(frozen=True)
class AuthoritativeAxis:
    name: str
    choice_ids: tuple[str, ...]
    source_id: str
    authority_basis: str

    def __post_init__(self):
        if self.authority_basis not in {"AUTHORITATIVE_CLOSED_UNIVERSE", "EXPLICIT_SOURCE_IDENTITY", "EXPLICIT_STRUCTURED_ABSENCE", "EMPIRICAL_CANDIDATE_SET"}:
            raise ValueError("a schema, challenger or LLM confidence is not semantic closure")


@dataclass(frozen=True)
class CertificateContext:
    prompt: str
    response: str
    tool_metadata: tuple[ToolIdentity, ...]
    claims: tuple[TypedClaim, ...]
    authoritative_axes: tuple[AuthoritativeAxis, ...]
    hypotheses: tuple[EvaluationHypothesis, ...] = ()
    policy_text: str = ""
    goal_plan_text: str = ""


@dataclass(frozen=True)
class CertificateCheck:
    valid: bool
    errors: tuple[str, ...]


def material_claims_covered(context: CertificateContext) -> bool:
    inventory = response_spans(context.response)
    expected = {span["span_id"]: (span["start"], span["end"]) for span in inventory}
    if (len(context.claims) != len(expected) or len({claim.claim_id for claim in context.claims}) != len(context.claims)):
        return False
    for claim in context.claims:
        if expected.get(claim.claim_id) != (claim.span.start, claim.span.end) or claim.span.document != "response":
            return False
        if claim.disposition is Disposition.UNKNOWN_SEMANTICS:
            return False
        if claim.disposition is Disposition.VERIFIABLE_TYPED and claim.unknown_fields:
            return False
    return True


def completeness_assumptions(context: CertificateContext, problem: ProofProblem,
                              ledger: EvidenceLedger) -> tuple[tuple[str, str], ...]:
    index = LedgerIndex(ledger)
    material = [claim for claim in context.claims if claim.disposition is Disposition.VERIFIABLE_TYPED]
    bindings_closed = all(bind_claim(claim, ledger, index).candidate_search.candidate_set_complete for claim in material)
    expected = {(axis.name, axis.choice_ids, axis.source_id) for axis in context.authoritative_axes}
    actual = {(axis.name, axis.choice_ids, axis.universe_source) for axis in problem.axes if axis.enumeration_complete is True}
    axes_covered = expected == actual and len(expected) == len(problem.axes)
    axes_closed = axes_covered and all(axis.authority_basis != "EMPIRICAL_CANDIDATE_SET" for axis in context.authoritative_axes)
    return (("MATERIAL_RESPONSE_COVERED", "validated deterministic span inventory" if material_claims_covered(context) else "NOT_ESTABLISHED"),
            ("SOURCE_HISTORY_COMPLETE", ledger.completeness_basis if ledger.history_complete else "NOT_ESTABLISHED"),
            ("BINDING_SPACE_COMPLETE", "explicit exact identity candidates" if bindings_closed else "NOT_ESTABLISHED"),
            ("SEMANTIC_CANDIDATES_COVERED", "all supplied admissible candidates enumerated; not an assertion of unrestricted NL completeness" if axes_covered else "NOT_ESTABLISHED"),
            ("SEMANTIC_SPACE_PROVABLY_CLOSED", "independently supplied authoritative axes" if axes_closed else "NOT_ESTABLISHED"),
            ("ABSENCE_SCOPE_REQUIREMENT", "all absence premises individually checked; retrieval miss is not absence"))


def check_certificate(certificate: ProofCertificate, context: CertificateContext,
                       problem: ProofProblem, ledger: EvidenceLedger,
                       registry: ContractRegistry) -> CertificateCheck:
    errors = []
    if certificate.version != "guardian-vnext-proof-v1" or certificate.status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return CertificateCheck(False, ("INVALID_CERTIFICATE_KIND",))
    hashes = {"source_sha256": digest(asdict(context)),
              "ledger_sha256": digest(asdict(ledger)), "problem_sha256": digest(asdict(problem)),
              "registry_sha256": digest([asdict(contract) for contract in registry.contracts])}
    for field, expected in hashes.items():
        if getattr(certificate, field) != expected:
            errors.append("HASH_MISMATCH:" + field)
    if normalize(context.prompt, context.response, tool_identities=context.tool_metadata) != ledger.events:
        errors.append("LEDGER_SOURCE_RECONSTRUCTION_FAILED")
    assumptions = completeness_assumptions(context, problem, ledger)
    if certificate.completeness_assumptions != assumptions:
        errors.append("COMPLETENESS_ASSUMPTIONS_MISMATCH")
    required_assumptions = {"MATERIAL_RESPONSE_COVERED", "SEMANTIC_CANDIDATES_COVERED"}
    if certificate.status is CoreStatus.PROVED_NO_ERROR:
        required_assumptions.update({"SOURCE_HISTORY_COMPLETE", "BINDING_SPACE_COMPLETE", "SEMANTIC_SPACE_PROVABLY_CLOSED"})
    if any(value in {None, "NOT_ESTABLISHED"} for key, value in assumptions if key in required_assumptions):
        errors.append("COMPLETENESS_UNPROVED")
    if len({axis.name for axis in problem.axes}) != len(problem.axes):
        errors.append("DUPLICATE_AXIS")
    if any(not axis.choice_ids or len(set(axis.choice_ids)) != len(axis.choice_ids) for axis in problem.axes):
        errors.append("INVALID_AXIS_CHOICES")
    expected_choices = set(itertools.product(*(axis.choice_ids for axis in problem.axes)))
    plans = {world.world_id: world for world in problem.worlds}
    proofs = {proof.world_id: proof for proof in certificate.world_proofs}
    if (not plans or len(plans) != len(problem.worlds) or len(proofs) != len(certificate.world_proofs)
            or set(plans) != set(proofs) or len({world.choices for world in problem.worlds}) != len(plans)
            or {world.choices for world in problem.worlds} != expected_choices):
        errors.append("INTERPRETATION_SPACE_INCOMPLETE_OR_DUPLICATED")
    index = LedgerIndex(ledger)
    for wid, plan in plans.items():
        proof = proofs.get(wid)
        if proof is None:
            continue
        if proof.choices != plan.choices or plan.unresolved_reasons:
            errors.append("UNRESOLVED_OR_MISMATCHED_WORLD:" + wid)
        primitives, safety = [], []
        for obligation in plan.obligations:
            condition_proofs = tuple(prove_atom(atom, ledger, index, registry, problem.absence_scopes) for atom in obligation.conditions)
            value = prove_atom(obligation.atom, ledger, index, registry, problem.absence_scopes)
            primitives.extend((*condition_proofs, value))
            condition = conjunction(tuple(item.value for item in condition_proofs))
            consequence = value.value if obligation.must_be_true else negate(value.value)
            safety.append((obligation.obligation_id, disjunction((negate(condition), consequence))))
            if obligation.claim_id is not None and obligation.claim_id not in {claim.claim_id for claim in context.claims}:
                errors.append("UNKNOWN_CLAIM_WITNESS:" + obligation.obligation_id)
            # Hypotheses must occur in some declared semantic/binding/effect axis,
            # or be the explicit fixed factual-consistency product obligation.
            if obligation.hypothesis_id != "GUARDIAN_FACTUAL_CONSISTENCY_V1" and obligation.hypothesis_id not in plan.choices:
                errors.append("UNKNOWN_APPLICABLE_HYPOTHESIS:" + obligation.obligation_id)
            if obligation.hypothesis_id == "GUARDIAN_FACTUAL_CONSISTENCY_V1":
                claim = next((item for item in context.claims if item.claim_id == obligation.claim_id), None)
                if (claim is None or obligation.must_be_true is not True or obligation.conditions
                        or claim.predicate != obligation.atom.predicate
                        or obligation.atom.entity.value not in claim.entity_refs):
                    errors.append("FACTUAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
                else:
                    from .proof_records import AtomKind
                    from .types import ClaimKind
                    mapping = {ClaimKind.ACTION_COMPLETED: AtomKind.ACTION_COMPLETED,
                        ClaimKind.ABSENCE: AtomKind.HISTORICAL_ACTION, ClaimKind.STATE: AtomKind.OBSERVED_STATE,
                        ClaimKind.ATTRIBUTION: AtomKind.RESULT_FIELD, ClaimKind.CAUSAL_ATTRIBUTION: AtomKind.CAUSAL_ATTRIBUTION}
                    if (mapping.get(claim.kind) is not obligation.atom.kind
                            or obligation.atom.expected_json != ("false" if claim.polarity == "NEGATIVE" else "true")
                            or claim.kind in {ClaimKind.ACTION_COMPLETED, ClaimKind.CAUSAL_ATTRIBUTION} and claim.actor != obligation.atom.actor):
                        errors.append("CLAIM_TYPE_POLARITY_OR_ACTOR_MISMATCH:" + obligation.obligation_id)
            else:
                hypothesis = next((item for item in context.hypotheses if item.hypothesis_id == obligation.hypothesis_id), None)
                required_polarity = {"PROHIBITION": False, "REQUIREMENT": True, "PLAN_OBLIGATION": True}
                if (hypothesis is None or hypothesis.behavioral_relation not in required_polarity
                        or obligation.must_be_true is not required_polarity.get(hypothesis.behavioral_relation)
                        or hypothesis.action_or_state != obligation.atom.predicate
                        or hypothesis.actor != obligation.atom.actor or hypothesis.conditions or hypothesis.exceptions):
                    errors.append("OBLIGATION_NOT_AUTHORIZED_BY_HYPOTHESIS:" + obligation.obligation_id)
                elif not hypothesis.grounding or hypothesis.unresolved_terms:
                    errors.append("APPLICABLE_HYPOTHESIS_NOT_GROUNDED:" + obligation.obligation_id)
                else:
                    text = context.policy_text if hypothesis.frontend == "policy" else context.goal_plan_text
                    if (hypothesis.resource not in {None, "", "*", obligation.atom.entity.value}
                            or any(span.document != hypothesis.frontend or span.end > len(text) for span in hypothesis.grounding)):
                        errors.append("HYPOTHESIS_SCOPE_OR_SOURCE_MISMATCH:" + obligation.obligation_id)
        if tuple(primitives) != proof.primitives or tuple(safety) != proof.obligation_safety:
            errors.append("PRIMITIVE_OR_OBLIGATION_WITNESS_MISMATCH:" + wid)
        error_value = negate(conjunction(tuple(value for _, value in safety)))
        if error_value != proof.error_value:
            errors.append("WORLD_VERDICT_MISMATCH:" + wid)
        expected_error = Truth.TRUE if certificate.status is CoreStatus.PROVED_ERROR else Truth.FALSE
        if error_value is not expected_error:
            errors.append("WORLD_DOES_NOT_PROVE_CERTIFIED_VERDICT:" + wid)
        if certificate.status is CoreStatus.PROVED_ERROR and not any(value is Truth.FALSE for _, value in safety):
            errors.append("MISSING_VIOLATION_WITNESS:" + wid)
        if certificate.status is CoreStatus.PROVED_NO_ERROR:
            checked_claims = {ob.claim_id for ob in plan.obligations if ob.hypothesis_id == "GUARDIAN_FACTUAL_CONSISTENCY_V1"}
            material_claims = {claim.claim_id for claim in context.claims if claim.disposition is Disposition.VERIFIABLE_TYPED}
            if not material_claims <= checked_claims:
                errors.append("SAFETY_MATERIAL_OBLIGATIONS_INCOMPLETE:" + wid)
            for hypothesis in context.hypotheses:
                if (hypothesis.hypothesis_id in plan.choices
                        and hypothesis.behavioral_relation in {"PROHIBITION", "REQUIREMENT", "PLAN_OBLIGATION"}
                        and not any(ob.hypothesis_id == hypothesis.hypothesis_id for ob in plan.obligations)):
                    errors.append("SAFETY_APPLICABLE_OBLIGATION_MISSING:" + hypothesis.hypothesis_id)
    return CertificateCheck(not errors, tuple(dict.fromkeys(errors)))
