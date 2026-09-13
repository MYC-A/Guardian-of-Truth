"""Independent Goal v3 certificate replay: no solver or verdict imports."""

from dataclasses import asdict

from .goal_alignment_primitives_v3 import attempted_before, result_boolean_before, validate_goal_source_v3
from .goal_alignment_records_v3 import GoalRuleKind, GoalRuleProofV3, GoalWorldProofV3
from .integrity import digest
from .types import CoreStatus, Truth


def _replay_world(source, world):
    target = source["target_action"]
    capabilities = {item.name: item for item in world.capabilities}
    name = target.get("tool")
    target_cap = capabilities.get(name)
    unknowns, violations, contradictions, pending, rows = list(world.unresolved_terms), [], [], [], []
    if (target.get("actor") != "assistant" or target_cap is None
            or target.get("provider") != target_cap.provider or target.get("version") != target_cap.version
            or not isinstance(target.get("arguments"), dict)):
        return GoalWorldProofV3(world.world_id, CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", (), (),
            (*unknowns, "TARGET_CAPABILITY_OR_ACTOR_UNBOUND"), (), ())
    entity = target["arguments"].get(target_cap.entity_argument)
    if not isinstance(entity, str) or not entity:
        return GoalWorldProofV3(world.world_id, CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", (), (),
            (*unknowns, "TARGET_ENTITY_UNBOUND"), (), ())
    if entity != world.entity:
        violations.append("EXPLICIT_ENTITY_SCOPE")
    if name in world.forbidden_attempt_tools:
        violations.append("EXPLICIT_FORBIDDEN_ATTEMPT")
    if not world.authorization_closed:
        unknowns.append("OPEN_AUTHORIZATION_UNIVERSE")
    for rule in world.rules:
        if rule.kind is not GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION and name not in rule.trigger_tools:
            rows.append(GoalRuleProofV3(rule.rule_id, Truth.TRUE, (), reason="TRIGGER_NOT_ACTIVE"))
            continue
        required = capabilities.get(rule.required_tool)
        if required is None:
            rows.append(GoalRuleProofV3(rule.rule_id, Truth.UNKNOWN, (), reason="REQUIRED_INTERFACE_UNBOUND"))
            unknowns.append(rule.rule_id)
            continue
        if rule.kind in {GoalRuleKind.REQUIRE_RESULT_TRUE, GoalRuleKind.EXCEPTION_RESULT_TRUE}:
            evidence = (result_boolean_before(source, required, world.entity, rule.result_field,
                required_result=True),)
            value = evidence[0].value
            due_later = False
        elif rule.kind is GoalRuleKind.REQUIRE_ATTEMPT_BEFORE:
            evidence = (attempted_before(source, required, world.entity),)
            value = evidence[0].value
            due_later = False
        elif rule.kind is GoalRuleKind.WHEN_RESULT_TRUE_REQUIRE_ATTEMPT:
            guard_cap = capabilities.get(rule.guard_tool)
            if guard_cap is None:
                rows.append(GoalRuleProofV3(rule.rule_id, Truth.UNKNOWN, (), reason="GUARD_INTERFACE_UNBOUND"))
                unknowns.append(rule.rule_id)
                continue
            evidence = (result_boolean_before(source, guard_cap, world.entity, rule.result_field),
                attempted_before(source, required, world.entity))
            guard, consequent = (item.value for item in evidence)
            value = (consequent if guard is Truth.TRUE else Truth.TRUE if guard is Truth.FALSE
                else Truth.BOTH if guard is Truth.BOTH else Truth.TRUE if consequent is Truth.TRUE else Truth.UNKNOWN)
            due_later = False
        elif rule.kind is GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION:
            evidence = (attempted_before(source, required, world.entity),)
            due_later = not source["session_complete"] and evidence[0].value is not Truth.TRUE
            value = Truth.UNKNOWN if due_later else evidence[0].value
        else:
            raise ValueError("unsupported Goal rule kind in certificate")
        rows.append(GoalRuleProofV3(rule.rule_id, value, evidence, due_later))
        if due_later:
            pending.append(rule.rule_id)
        elif value is Truth.FALSE:
            violations.append(rule.rule_id)
        elif value is Truth.BOTH:
            contradictions.append(rule.rule_id)
        elif value is Truth.UNKNOWN:
            unknowns.append(rule.rule_id)
    status = (CoreStatus.PROVED_ERROR if violations else CoreStatus.INCONSISTENT if contradictions
        else CoreStatus.UNRESOLVED if unknowns or pending or not source["history_complete"]
        else CoreStatus.PROVED_NO_ERROR)
    if status is CoreStatus.PROVED_ERROR:
        alignment = "PROVED_OUT_OF_SCOPE"
    elif status in {CoreStatus.UNRESOLVED, CoreStatus.INCONSISTENT}:
        alignment = "AMBIGUOUS_ALIGNMENT"
    elif name in world.direct_tools:
        alignment = "DIRECT_GOAL"
    elif name in world.auxiliary_tools:
        alignment = "PERMITTED_AUXILIARY"
    else:
        alignment = "AMBIGUOUS_ALIGNMENT"
    return GoalWorldProofV3(world.world_id, status, alignment, tuple(rows), tuple(violations),
        tuple(unknowns), tuple(contradictions), tuple(pending))


def check_goal_alignment_certificate_v3(certificate, projection, contract, fixture_spec):
    """Rebind trusted fixture source and independently replay every proof row."""
    errors = []
    try:
        source = validate_goal_source_v3(projection)
        from benchmarks.vnext.goal_alignment_fixture_contract_v3 import compile_fixture_goal_contract
        expected_contract = compile_fixture_goal_contract(projection, fixture_spec)
    except (ValueError, KeyError, TypeError, ImportError) as exc:
        return False, ("SOURCE_OR_AUTHORITY_REPLAY_FAILED:" + type(exc).__name__,)
    if contract != expected_contract:
        errors.append("CONTRACT_NOT_PINNED_SOURCE_AUTHORITY")
    if (certificate.version != "guardian-goal-v3-certificate-v1"
            or certificate.status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}
            or certificate.source_sha256 != projection["source_sha256"]
            or certificate.contract_sha256 != digest(asdict(contract))
            or not certificate.complete_world_inventory or not contract.complete_world_inventory):
        errors.append("CERTIFICATE_IDENTITY_OR_WORLD_CLOSURE_INVALID")
    expected_worlds = tuple(_replay_world(source, world) for world in expected_contract.worlds)
    if certificate.world_proofs != expected_worlds:
        errors.append("WORLD_PRIMITIVES_OR_OBLIGATIONS_REPLAY_MISMATCH")
    statuses = {world.status for world in expected_worlds}
    if len(statuses) != 1 or next(iter(statuses)) is not certificate.status:
        errors.append("ALL_WORLD_STATUS_NOT_PROVED")
    if certificate.status is CoreStatus.PROVED_NO_ERROR and (
            not source["history_complete"] or source.get("unrelated_goal_term")
            or not all(world.authorization_closed and not world.unresolved_terms for world in expected_contract.worlds)):
        errors.append("NO_ERROR_COMPLETENESS_MISSING")
    if certificate.status is CoreStatus.PROVED_ERROR and any(not world.violations for world in expected_worlds):
        errors.append("DECISIVE_VIOLATION_NOT_UNIVERSAL")
    if certificate.dependency_scope != "INDEPENDENT_SYSTEM_VIOLATION_OR_FULL_EXPLICIT_FIXTURE_CLOSURE":
        errors.append("DEPENDENCY_SCOPE_CHANGED")
    return not errors, tuple(dict.fromkeys(errors))
