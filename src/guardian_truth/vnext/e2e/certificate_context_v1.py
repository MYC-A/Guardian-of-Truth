"""E2E V1 certificate context, builder and independent deterministic checker.

The checker never calls an LLM, never trusts solver prose, model confidence,
tool names as effects or schemas as effect contracts. It recomputes every
primitive proof, every world verdict, the closure premises and the obligation
grounding from the immutable records. A rejected certificate downgrades the
Core output to UNRESOLVED (spec 104-107).
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

from ..binder import bind_claim
from ..certificates import CertificateCheck, CertificateContext, material_claims_covered
from ..integrity import digest
from ..ledger import EvidenceLedger, LedgerIndex
from ..normalize import normalize
from ..proof_records import (AtomKind, ProofCertificate, ProofProblem, TimeMode,
                             conjunction, disjunction, negate)
from ..tools import ContractRegistry
from ..types import (ClaimKind, CoreStatus, Disposition, EffectStatus, Reason, ToolIdentity, Truth)
from .e2e_types_v1 import E2ESemantics, FULL_SEMANTICS
from .world_integration_v1 import E2EProblem, solve_world

E2E_CERT_VERSION = "guardian-e2e-v1-proof-v1"
CLAIM_OBLIGATION_HYPOTHESIS = "GUARDIAN_FACTUAL_CONSISTENCY_V1"


@dataclass(frozen=True)
class E2EBundle:
    """Everything the independent checker needs, all immutable."""
    context: CertificateContext
    problem: E2EProblem
    option_contracts: dict          # option_id -> {"rules": {rule_id: {"obligations": [ids], "groups": [ids]}}}
    choice_rules: dict              # choice_id -> {"rule_kind": str, "conditions": [(key, negated)], "toolmatch": bool}
    direct_rules: dict              # hypothesis_id -> {"rule_kind": str}
    policy_closure: dict            # {"supplied": bool, "actual_keys": [...], "authoritative_keys": [...]}
    goal_closure: dict
    frontend_failures: tuple        # [(component, kind)]
    semantics: E2ESemantics = FULL_SEMANTICS   # cycle-3 gates the checker MUST reuse

    def source_digest(self) -> str:
        from dataclasses import asdict as _asdict
        return digest({"context": asdict(self.context),
                       "option_contracts": self.option_contracts,
                       "choice_rules": self.choice_rules,
                       "direct_rules": self.direct_rules,
                       "policy_closure": self.policy_closure,
                       "goal_closure": self.goal_closure,
                       "frontend_failures": list(self.frontend_failures),
                       "semantics": _asdict(self.semantics)})


def problem_digest(problem: E2EProblem) -> str:
    return digest({"axes": [asdict(axis) for axis in problem.axes],
                   "worlds": [asdict(plan) for plan in problem.problems],
                   "side": problem.side_sha256})


def e2e_completeness_assumptions(bundle: E2EBundle, ledger: EvidenceLedger) -> tuple[tuple[str, str], ...]:
    context = bundle.context
    index = LedgerIndex(ledger)
    material = [claim for claim in context.claims if claim.disposition is Disposition.VERIFIABLE_TYPED]
    bindings_closed = all(bind_claim(claim, ledger, index).candidate_search.candidate_set_complete
                          for claim in material)
    expected = {(axis.name, axis.choice_ids, axis.source_id) for axis in context.authoritative_axes}
    actual = {(axis.name, axis.choice_ids, axis.universe_source) for axis in bundle.problem.axes
              if axis.enumeration_complete is True}
    axes_covered = expected == actual and len(expected) == len(bundle.problem.axes)
    axes_closed = axes_covered and all(axis.authority_basis != "EMPIRICAL_CANDIDATE_SET"
                                       for axis in context.authoritative_axes)
    return (("MATERIAL_RESPONSE_COVERED", "validated deterministic span inventory" if material_claims_covered(context) else "NOT_ESTABLISHED"),
            ("SOURCE_HISTORY_COMPLETE", ledger.completeness_basis if ledger.history_complete else "NOT_ESTABLISHED"),
            ("BINDING_SPACE_COMPLETE", "explicit exact identity candidates" if bindings_closed else "NOT_ESTABLISHED"),
            ("SEMANTIC_CANDIDATES_COVERED", "all supplied admissible candidates enumerated; not an assertion of unrestricted NL completeness" if axes_covered else "NOT_ESTABLISHED"),
            ("SEMANTIC_SPACE_PROVABLY_CLOSED", "independently supplied authoritative axes" if axes_closed else "NOT_ESTABLISHED"),
            ("FRESH_STATE_EVIDENCE", "latest supporting observations not superseded by later attempted calls"
             if _state_evidence_fresh(context, ledger) else "NOT_ESTABLISHED"),
            ("ABSENCE_SCOPE_REQUIREMENT", "all absence premises individually checked; retrieval miss is not absence"),
            ("EFFECTS_TRUSTED_ONLY", "no untrusted T2 effect axis present" if _no_t2_axes(bundle) else "NOT_ESTABLISHED"))


def _state_evidence_fresh(context, ledger) -> bool:
    """A material STATE/ATTRIBUTION claim can only certify safety when its
    latest supporting observation is not superseded by any later attempted
    call: an attempted mutation invalidates a stale state claim."""
    call_indexes = [event.index for event in ledger.events if event.kind == "call"]
    if not call_indexes:
        return True
    last_call = max(call_indexes)
    material = [claim for claim in context.claims
                if claim.disposition is Disposition.VERIFIABLE_TYPED
                and claim.kind in {ClaimKind.STATE, ClaimKind.ATTRIBUTION}]
    for claim in material:
        latest = [obs.index for obs in ledger.observations
                  if claim.predicate == obs.predicate
                  and any(ref.value in claim.entity_refs for ref in obs.entity_refs)]
        positions = {event.event_id: event.index for event in ledger.events}
        latest.extend(positions[effect.event_id] for effect in ledger.effects
                      if effect.predicate == claim.predicate and effect.status is EffectStatus.TRUSTED_EFFECT
                      and any(ref.value in claim.entity_refs for ref in (effect.entity,)))
        if not latest or max(latest) < last_call:
            return False
    return True


def _no_t2_axes(bundle: E2EBundle) -> bool:
    return all(not axis.name.startswith("effect:") for axis in bundle.problem.axes)


def make_e2e_certificate(status: CoreStatus, bundle: E2EBundle, ledger: EvidenceLedger,
                         registry: ContractRegistry,
                         semantics: E2ESemantics = FULL_SEMANTICS) -> ProofCertificate | None:
    if status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return None
    return ProofCertificate(E2E_CERT_VERSION, status, bundle.source_digest(),
                            digest(asdict(ledger)), digest([asdict(contract) for contract in registry.contracts]),
                            problem_digest(bundle.problem), bundle.problem.worlds and
                            tuple(proof for proof in _world_proofs(bundle, ledger, registry, semantics)),
                            e2e_completeness_assumptions(bundle, ledger))


def _world_proofs(bundle: E2EBundle, ledger: EvidenceLedger, registry: ContractRegistry,
                  semantics: E2ESemantics):
    from .world_integration_v1 import solve_e2e
    result = solve_e2e(bundle.problem, ledger, registry, semantics)
    return result.world_proofs


def check_e2e_certificate(certificate: ProofCertificate, bundle: E2EBundle, ledger: EvidenceLedger,
                          registry: ContractRegistry) -> CertificateCheck:
    errors: list[str] = []
    context = bundle.context
    problem = bundle.problem
    if certificate.version != E2E_CERT_VERSION or certificate.status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return CertificateCheck(False, ("INVALID_CERTIFICATE_KIND",))
    hashes = {"source_sha256": bundle.source_digest(),
              "ledger_sha256": digest(asdict(ledger)),
              "registry_sha256": digest([asdict(contract) for contract in registry.contracts]),
              "problem_sha256": problem_digest(problem)}
    for field_name, expected in hashes.items():
        if getattr(certificate, field_name) != expected:
            errors.append("HASH_MISMATCH:" + field_name)
    if normalize(context.prompt, context.response, tool_identities=context.tool_metadata) != ledger.events:
        errors.append("LEDGER_SOURCE_RECONSTRUCTION_FAILED")
    assumptions = e2e_completeness_assumptions(bundle, ledger)
    if certificate.completeness_assumptions != assumptions:
        errors.append("COMPLETENESS_ASSUMPTIONS_MISMATCH")
    # PROVED_ERROR needs one certified violation witness in every world; a
    # certified independent violation is never masked by unrelated unknowns
    # (spec 96, 100, 125), so response-claim coverage and closure premises are
    # NOT required for it. PROVED_NO_ERROR needs the full closure set: every
    # material claim checked, complete history, closed bindings, provably
    # closed semantics and fresh state evidence (spec 101).
    required = {"SEMANTIC_CANDIDATES_COVERED"}
    if certificate.status is CoreStatus.PROVED_NO_ERROR:
        required |= {"MATERIAL_RESPONSE_COVERED", "SOURCE_HISTORY_COMPLETE", "BINDING_SPACE_COMPLETE",
                     "SEMANTIC_SPACE_PROVABLY_CLOSED", "FRESH_STATE_EVIDENCE"}
    if any(value in {None, "NOT_ESTABLISHED"} for key, value in assumptions if key in required):
        errors.append("COMPLETENESS_UNPROVED")
    if len({axis.name for axis in problem.axes}) != len(problem.axes):
        errors.append("DUPLICATE_AXIS")
    if any(not axis.choice_ids or len(set(axis.choice_ids)) != len(axis.choice_ids) for axis in problem.axes):
        errors.append("INVALID_AXIS_CHOICES")
    proofs = {proof.world_id: proof for proof in certificate.world_proofs}
    worlds = {world.world_id: world for world in problem.worlds}
    if set(proofs) != set(worlds) or not worlds:
        errors.append("WORLD_INVENTORY_MISMATCH")
    index = LedgerIndex(ledger)
    semantics = bundle.semantics
    claim_ids = {claim.claim_id for claim in context.claims}
    choice_ids = {choice.choice_id for choice in context.operational_choices}
    for world in worlds.values():
        proof = proofs.get(world.world_id)
        if proof is None:
            continue
        recomputed = solve_world(world, ledger, index, registry, semantics)
        if tuple(recomputed.primitives) != proof.primitives or tuple(recomputed.obligation_safety) != proof.obligation_safety:
            errors.append("PRIMITIVE_OR_OBLIGATION_WITNESS_MISMATCH:" + world.world_id)
        if recomputed.error_value != proof.error_value:
            errors.append("WORLD_VERDICT_MISMATCH:" + world.world_id)
        expected_error = Truth.TRUE if certificate.status is CoreStatus.PROVED_ERROR else Truth.FALSE
        if recomputed.error_value is not expected_error:
            errors.append("WORLD_DOES_NOT_PROVE_CERTIFIED_VERDICT:" + world.world_id)
        if certificate.status is CoreStatus.PROVED_ERROR and not any(
                value is Truth.FALSE for _, value in recomputed.obligation_safety):
            errors.append("MISSING_VIOLATION_WITNESS:" + world.world_id)
        # Obligation grounding and reading coverage.
        selected_options = {component_choice for component_choice in world.choices}
        option_ids = [choice for choice in world.choices]
        allowed_obligation_ids = set()
        for option_id in option_ids:
            contract = bundle.option_contracts.get(option_id, {})
            for rule_id, spec in contract.get("rules", {}).items():
                allowed_obligation_ids.update(spec.get("obligations", ()))
            allowed_obligation_ids.update(contract.get("claim_obligations", ()))
        for obligation in world.obligations:
            if obligation.obligation_id not in allowed_obligation_ids:
                errors.append("FOREIGN_OBLIGATION:" + obligation.obligation_id)
            if obligation.hypothesis_id == CLAIM_OBLIGATION_HYPOTHESIS:
                _check_claim_obligation(obligation, context, errors, semantics)
            elif obligation.hypothesis_id in choice_ids:
                _check_choice_obligation(obligation, bundle, context, ledger, errors)
            else:
                _check_direct_obligation(obligation, context, bundle, errors)
        for group in world.groups:
            rule = bundle.choice_rules.get(group.rule_id) or bundle.direct_rules.get(group.rule_id)
            if rule is None and group.rule_id not in bundle.option_contracts.get(
                    option_ids[0] if option_ids else "", {}).get("rules", {}):
                # groups belong to a rule of one of the selected options
                if not any(group.rule_id in bundle.option_contracts.get(oid, {}).get("rules", {})
                           for oid in option_ids):
                    errors.append("FOREIGN_GROUP:" + group.group_id)
        # Selected reading coverage: all contracted obligations present.
        for option_id in option_ids:
            contract = bundle.option_contracts.get(option_id, {})
            for rule_id, spec in contract.get("rules", {}).items():
                missing = [oid for oid in spec.get("obligations", ()) if oid not in
                           {obligation.obligation_id for obligation in world.obligations}]
                if missing:
                    errors.append("READING_OBLIGATION_COVERAGE_INCOMPLETE:" + option_id + ":" + rule_id)
        if certificate.status is CoreStatus.PROVED_NO_ERROR:
            material_claims = {claim.claim_id for claim in context.claims
                               if claim.disposition is Disposition.VERIFIABLE_TYPED}
            checked = {obligation.claim_id for obligation in world.obligations
                       if obligation.hypothesis_id == CLAIM_OBLIGATION_HYPOTHESIS}
            if not material_claims <= checked:
                errors.append("SAFETY_MATERIAL_OBLIGATIONS_INCOMPLETE:" + world.world_id)
    return CertificateCheck(not errors, tuple(dict.fromkeys(errors)))


def _check_claim_obligation(obligation, context, errors, semantics: E2ESemantics = FULL_SEMANTICS):
    claim = next((item for item in context.claims if item.claim_id == obligation.claim_id), None)
    if (claim is None or obligation.must_be_true is not True or obligation.conditions
            or claim.predicate != obligation.atom.predicate
            or obligation.atom.entity.value not in claim.entity_refs):
        errors.append("FACTUAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
        return
    from .claim_adapter_v1 import claim_expected_json
    mapping = {ClaimKind.ACTION_COMPLETED: AtomKind.ACTION_COMPLETED,
               ClaimKind.ABSENCE: AtomKind.HISTORICAL_ACTION, ClaimKind.STATE: AtomKind.OBSERVED_STATE,
               ClaimKind.ATTRIBUTION: AtomKind.RESULT_FIELD, ClaimKind.CAUSAL_ATTRIBUTION: AtomKind.CAUSAL_ATTRIBUTION}
    if (mapping.get(claim.kind) is not obligation.atom.kind
            or obligation.atom.expected_json != claim_expected_json(claim, typing_v2=semantics.claim_typing)
            or claim.kind in {ClaimKind.ACTION_COMPLETED, ClaimKind.CAUSAL_ATTRIBUTION} and claim.actor != obligation.atom.actor):
        errors.append("CLAIM_TYPE_POLARITY_OR_ACTOR_MISMATCH:" + obligation.obligation_id)


def _check_choice_obligation(obligation, bundle, context, ledger, errors):
    choice = next((item for item in context.operational_choices if item.choice_id == obligation.hypothesis_id), None)
    rule = bundle.choice_rules.get(obligation.hypothesis_id, {})
    if choice is None:
        errors.append("UNKNOWN_OPERATIONAL_CHOICE:" + obligation.obligation_id)
        return
    from ..certificates import operational_choice_valid
    if not operational_choice_valid(choice, context, ledger):
        errors.append("OPERATIONAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
        return
    if obligation.atom not in choice.atoms or obligation.must_be_true is not choice.must_be_true:
        errors.append("OPERATIONAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
        return
    if obligation.claim_id is not None:
        errors.append("OPERATIONAL_OBLIGATION_NOT_GROUNDED:" + obligation.obligation_id)
        return
    expected_conditions = []
    if rule.get("toolmatch"):
        event = next((event for event in ledger.events
                      if event.event_id == obligation.atom.entity.value), None)
        if event is not None:
            expected_conditions.append(("toolmatch", obligation.atom.predicate, event.event_id))
    for key, negated in rule.get("conditions", ()):
        expected_conditions.append(("prerequisite", key, bool(negated)))
    actual = []
    for atom in obligation.conditions:
        if atom.kind is AtomKind.TARGET_CALL_MATCH:
            actual.append(("toolmatch", atom.predicate, atom.entity.value))
        elif atom.kind is AtomKind.CALL_ATTEMPTED and atom.entity.namespace in {"e2e", "e2e-state"}:
            actual.append(("prerequisite", atom.predicate, atom.expected_json == "false"))
        else:
            errors.append("UNSUPPORTED_CONDITION_ATOM:" + obligation.obligation_id)
    if len(actual) != len(expected_conditions):
        errors.append("CONDITION_WITNESS_MISMATCH:" + obligation.obligation_id)
        return
    for expected in expected_conditions:
        if expected not in actual:
            errors.append("CONDITION_WITNESS_MISMATCH:" + obligation.obligation_id)
            return
    for atom in obligation.conditions:
        if atom.kind is AtomKind.CALL_ATTEMPTED:
            event = next((event for event in ledger.events if event.event_id == obligation.atom.entity.value), None)
            if event is None or atom.time_index != event.index or atom.actor != "assistant":
                errors.append("PREREQUISITE_TIME_OR_ACTOR_MISMATCH:" + obligation.obligation_id)
        elif atom.kind is AtomKind.TARGET_CALL_MATCH and (
                atom.time_index != (next((event.index for event in ledger.events
                                          if event.event_id == obligation.atom.entity.value), -1))):
            errors.append("TOOLMATCH_TIME_MISMATCH:" + obligation.obligation_id)


def _check_direct_obligation(obligation, context, bundle, errors):
    hypothesis = next((item for item in context.hypotheses
                       if item.hypothesis_id == obligation.hypothesis_id), None)
    rule = bundle.direct_rules.get(obligation.hypothesis_id, {})
    if hypothesis is None or rule.get("rule_kind") != "REQUIRE_CALL":
        errors.append("OBLIGATION_NOT_AUTHORIZED_BY_HYPOTHESIS:" + obligation.obligation_id)
        return
    required_polarity = {"PROHIBITION": False, "REQUIREMENT": True, "PLAN_OBLIGATION": True}
    if (hypothesis.behavioral_relation not in required_polarity
            or obligation.must_be_true is not required_polarity[hypothesis.behavioral_relation]
            or hypothesis.action_or_state != obligation.atom.predicate
            or hypothesis.actor != obligation.atom.actor or hypothesis.conditions or hypothesis.exceptions):
        errors.append("OBLIGATION_NOT_AUTHORIZED_BY_HYPOTHESIS:" + obligation.obligation_id)
        return
    if not hypothesis.grounding or hypothesis.unresolved_terms:
        errors.append("APPLICABLE_HYPOTHESIS_NOT_GROUNDED:" + obligation.obligation_id)
        return
    text = context.policy_text if hypothesis.frontend == "policy" else context.goal_plan_text
    if (hypothesis.resource not in {None, "", "*", obligation.atom.entity.value}
            or any(span.document != hypothesis.frontend or span.end > len(text) for span in hypothesis.grounding)):
        errors.append("HYPOTHESIS_SCOPE_OR_SOURCE_MISMATCH:" + obligation.obligation_id)
        return
    if obligation.atom.kind is not AtomKind.HISTORICAL_ACTION or obligation.atom.time_mode is not TimeMode.THROUGH:
        errors.append("EXISTENTIAL_ATOM_KIND_MISMATCH:" + obligation.obligation_id)
