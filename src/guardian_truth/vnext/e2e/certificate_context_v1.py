"""E2E V1 certificate context + independent checker extension.

The baseline CertificateContext is extended (subclass) with the E2E evidence:
retained policy readings (compiled programs), goal contracts, the binding
record, the lowering-context inputs and the arm configuration.  Everything is
hashed into source_sha256 via dataclass asdict, so any post-hoc mutation of
the e2e evidence invalidates the certificate exactly like the baseline.

check_certificate_e2e re-implements the baseline checker algorithm
(certificates.py) with a FOURTH obligation class — E2E rule obligations —
which is validated by full deterministic re-derivation: the lowering is a
pure function of (readings, binding, trajectory facts), so the checker
re-lowers and compares the obligation sets byte-exactly.  Baseline obligation
classes (factual claims) keep their baseline validation.  No LLM, no solver
prose, no model confidence (spec sections 104-107).
"""
from __future__ import annotations

import itertools
from dataclasses import asdict, dataclass, field

from ..certificates import (CertificateCheck, CertificateContext,
                            completeness_assumptions, material_claims_covered)
from ..integrity import digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..normalize import normalize
from ..proof_evidence import prove_atom
from ..proof_records import ProofCertificate, ProofProblem, conjunction, disjunction, negate
from ..tools import ContractRegistry
from ..types import CoreStatus, Disposition, Truth
from .goal_types_v1 import (BindingRecord, E5Resolution, ExtractiveRef, FrameKind,
                            GoalContract, GoalFrame, GroundedProposition,
                            TargetLevel)
from .policy_lowering_v1 import LoweringContext


E2E_CERTIFICATE_VERSION = "guardian-e2e-vnext-proof-v1"


@dataclass(frozen=True)
class E2ECertificateContext(CertificateContext):
    """Baseline context + E2E evidence (all hashed into source_sha256)."""

    e2e_policy_readings: tuple = ()      # serializable reading records
    e2e_goal_contracts: tuple = ()       # serializable contract records
    e2e_binding: dict = field(default_factory=dict)          # serializable binding record
    e2e_lowering_inputs: dict = field(default_factory=dict)  # target calls + end index
    e2e_arm: str = ""
    e2e_case_id: str = ""
    e2e_choice_audits: tuple = ()        # (choice_id, ((obligation_id, description), ...))


def make_e2e_certificate(result, problem, ledger, registry, *, context):
    """Versioned certificate builder (same hashes as the baseline builder)."""
    if result.status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return None
    return ProofCertificate(E2E_CERTIFICATE_VERSION, result.status,
                            digest(asdict(context)), digest(asdict(ledger)),
                            digest([asdict(contract) for contract in registry.contracts]),
                            digest(asdict(problem)), result.world_proofs,
                            completeness_assumptions(context, problem, ledger))


def _rederive_obligations(context: E2ECertificateContext, choice_id: str):
    """Re-run the deterministic lowering for one axis choice from the hashed
    e2e evidence.  Returns (obligations, unresolved_reasons) or None."""
    from .policy_composition_v1 import PolicyReading
    from .policy_lowering_v1 import lower_policy_reading
    from .goal_lowering_v1 import lower_goal_contract

    binding = _binding_from_json(context.e2e_binding)
    target_calls = tuple(context.e2e_lowering_inputs.get("target_calls", ()))
    all_calls = tuple(context.e2e_lowering_inputs.get("all_calls", ()))
    end_index = int(context.e2e_lowering_inputs.get("end_index", 0))
    lowering_context = LoweringContext(target_calls, end_index, all_calls)
    base_id = choice_id.split("|bind[")[0]
    if base_id.startswith("policy:"):
        for record in context.e2e_policy_readings:
            if record["reading_id"] != base_id:
                continue
            reading = PolicyReading(record["reading_id"], record["frontend"],
                                    tuple(record["programs"]), ())
            view = binding
            if "|bind[" in choice_id:
                signature = choice_id.split("|bind[")[1].rstrip("]")
                combo = {}
                for item in signature.split("|"):
                    atom, index = item.rsplit(":", 1)
                    combo[atom] = int(index)
                from .world_integration_v1 import combo_binding_view
                view = combo_binding_view(binding, combo)
            lowered = lower_policy_reading(reading, view, lowering_context)
            return lowered.obligations, lowered.unresolved_reasons
    elif base_id.startswith("goal:"):
        for record in context.e2e_goal_contracts:
            if record["contract_id"] != base_id:
                continue
            contract = _contract_from_json(record)
            lowered = lower_goal_contract(contract, binding, lowering_context)
            return lowered.obligations, lowered.unresolved_reasons
    return None


def _binding_from_json(data: dict) -> BindingRecord:
    from .goal_types_v1 import (AtomBindingCandidate, BindingCheck, BindingLevel,
                                ObservationBinding, OutcomeBinding)
    atom_bindings = []
    for unit, candidates in data.get("atom_bindings", ()):
        parsed = []
        for candidate in candidates:
            observation = None
            if candidate.get("observation"):
                observation = ObservationBinding(candidate["observation"]["tool"],
                                                 tuple(candidate["observation"]["path"]),
                                                 candidate["observation"]["expected_json"],
                                                 tuple(candidate["observation"].get("entity_path", ())))
            parsed.append(AtomBindingCandidate(
                candidate["unit_id"], candidate["tool"], BindingLevel(candidate["level"]),
                tuple(BindingCheck(tuple(check["path"]), tuple(check["allowed_json"]),
                                   check.get("presence_only", False), check.get("quote", ""))
                      for check in candidate.get("argument_checks", ())),
                observation, candidate.get("event_tool"), candidate.get("actor_role"),
                tuple(candidate.get("entity_path", ())), tuple(candidate.get("quotes", ()))))
        atom_bindings.append((unit, tuple(parsed)))
    outcome_bindings = []
    for unit, candidates in data.get("outcome_bindings", ()):
        parsed = []
        for candidate in candidates:
            parsed.append(OutcomeBinding(
                candidate["unit_id"], tuple(candidate["serving_tools"]),
                BindingLevel(candidate["level"]),
                tuple(BindingCheck(tuple(check["path"]), tuple(check["allowed_json"]),
                                   check.get("presence_only", False), check.get("quote", ""))
                      for check in candidate.get("argument_checks", ())),
                candidate.get("action_servable", True), tuple(candidate.get("quotes", ()))))
        outcome_bindings.append((unit, tuple(parsed)))
    return BindingRecord(tuple(atom_bindings), tuple(outcome_bindings),
                         tuple(data.get("unbound_units", ())), tuple(data.get("failures", ())))


def _contract_from_json(record: dict) -> GoalContract:
    frames = []
    for frame in record["frames"]:
        def proposition(item):
            if item is None:
                return None
            anchor = ExtractiveRef(item["anchor"]["source_id"], item["anchor"]["start"],
                                   item["anchor"]["end"], item["anchor"]["quote"])
            return GroundedProposition(item["text"], anchor, E5Resolution(item["resolution"]))
        frames.append(GoalFrame(
            frame["frame_id"], frame["frontend"], FrameKind(frame["kind"]),
            proposition(frame["content"]), proposition(frame["bearer"]),
            proposition(frame["entity"]),
            tuple(proposition(item) for item in frame["conditions"]),
            tuple(proposition(item) for item in frame["exceptions"]),
            tuple(proposition(item) for item in frame["alternatives"]),
            frame["temporal"], proposition(frame["temporal_event"]),
            frame["coordination"], frame["choice"], TargetLevel(frame["target_level"]),
            tuple(ExtractiveRef(item["source_id"], item["start"], item["end"], item["quote"])
                  for item in frame["source_support"])))
    return GoalContract(record["contract_id"], record["frontend"],
                        tuple(record["source_ids"]), tuple(frames),
                        tuple((item[0], item[1]) for item in record["rejected_frames"]),
                        tuple(record["unresolved_fields"]))


def check_certificate_e2e(certificate: ProofCertificate, context: E2ECertificateContext,
                          problem: ProofProblem, ledger: EvidenceLedger,
                          registry: ContractRegistry) -> CertificateCheck:
    """Baseline checker algorithm + the E2E re-derivation obligation class."""
    errors = []
    if certificate.version != E2E_CERTIFICATE_VERSION or certificate.status not in {
            CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
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
        required_assumptions.update({"SOURCE_HISTORY_COMPLETE", "BINDING_SPACE_COMPLETE",
                                     "SEMANTIC_SPACE_PROVABLY_CLOSED"})
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
    e2e_cache = {}
    for wid, plan in plans.items():
        proof = proofs.get(wid)
        if proof is None:
            continue
        if proof.choices != plan.choices or plan.unresolved_reasons:
            errors.append("UNRESOLVED_OR_MISMATCHED_WORLD:" + wid)
        primitives, safety = [], []
        for obligation in plan.obligations:
            condition_proofs = tuple(prove_atom(atom, ledger, index, registry, problem.absence_scopes)
                                     for atom in obligation.conditions)
            value = prove_atom(obligation.atom, ledger, index, registry, problem.absence_scopes)
            primitives.extend((*condition_proofs, value))
            condition = conjunction(tuple(item.value for item in condition_proofs))
            consequence = value.value if obligation.must_be_true else negate(value.value)
            safety.append((obligation.obligation_id, disjunction((negate(condition), consequence))))
            if obligation.hypothesis_id == "GUARDIAN_FACTUAL_CONSISTENCY_V1":
                claim = next((item for item in context.claims if item.claim_id == obligation.claim_id), None)
                if claim is None or obligation.must_be_true is not True or obligation.conditions:
                    errors.append("FACTUAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
            elif obligation.hypothesis_id in plan.choices:
                # E2E rule obligation: full deterministic re-derivation
                if obligation.hypothesis_id not in e2e_cache:
                    e2e_cache[obligation.hypothesis_id] = _rederive_obligations(
                        context, obligation.hypothesis_id)
                derived = e2e_cache[obligation.hypothesis_id]
                if derived is None or all(obligation != other for other in derived[0]):
                    errors.append("E2E_OBLIGATION_NOT_REDERIVABLE:" + obligation.obligation_id)
                from ..proof_records import AtomKind
                if (obligation.atom.kind is AtomKind.TARGET_CALL_MATCH
                        and obligation.atom.predicate.startswith("goal:")
                        and obligation.atom.predicate != "goal:unaddressed"):
                    errors.append("RESERVED_PREDICATE_MISUSE:" + obligation.obligation_id)
            else:
                errors.append("UNKNOWN_OBLIGATION_CLASS:" + obligation.obligation_id)
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
            checked_claims = {ob.claim_id for ob in plan.obligations
                              if ob.hypothesis_id == "GUARDIAN_FACTUAL_CONSISTENCY_V1"}
            material_claims = {claim.claim_id for claim in context.claims
                               if claim.disposition is Disposition.VERIFIABLE_TYPED}
            if not material_claims <= checked_claims:
                errors.append("SAFETY_MATERIAL_OBLIGATIONS_INCOMPLETE:" + wid)
    return CertificateCheck(not errors, tuple(dict.fromkeys(errors)))
