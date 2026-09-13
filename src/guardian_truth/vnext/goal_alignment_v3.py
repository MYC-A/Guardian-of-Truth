"""Goal v3: explicit authorization and due obligations, not guessed plan order.

This solver accepts already-grounded contract worlds. It never interprets NL,
turns a model suggestion into authority, or treats an attempted call as effect.
"""

from dataclasses import asdict

from .goal_alignment_primitives_v3 import attempted_before, result_boolean_before, validate_goal_source_v3
from .goal_alignment_records_v3 import (
    GoalCertificateV3, GoalDecisionV3, GoalPrimitiveV3, GoalRuleKind, GoalRuleProofV3, GoalWorldProofV3,
)
from .integrity import digest
from .types import CoreStatus, Truth


def _noop(rule_id):
    return GoalRuleProofV3(rule_id, Truth.TRUE, (), reason="TRIGGER_NOT_ACTIVE")


def evaluate_goal_world_v3(source, world):
    """Evaluate one admissible source-grounded world, keeping unknown checks."""
    target = source["target_action"]
    capabilities = {item.name: item for item in world.capabilities}
    name = target.get("tool")
    capability = capabilities.get(name)
    unknowns, violations, contradictions, pending, proofs = list(world.unresolved_terms), [], [], [], []
    if (target.get("actor") != "assistant" or capability is None
            or target.get("provider") != capability.provider or target.get("version") != capability.version
            or not isinstance(target.get("arguments"), dict)):
        unknowns.append("TARGET_CAPABILITY_OR_ACTOR_UNBOUND")
        return GoalWorldProofV3(world.world_id, CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", (), (),
            tuple(unknowns), (), ())
    entity = target["arguments"].get(capability.entity_argument)
    if not isinstance(entity, str) or not entity:
        unknowns.append("TARGET_ENTITY_UNBOUND")
        return GoalWorldProofV3(world.world_id, CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", (), (),
            tuple(unknowns), (), ())
    if entity != world.entity:
        violations.append("EXPLICIT_ENTITY_SCOPE")
    if name in world.forbidden_attempt_tools:
        violations.append("EXPLICIT_FORBIDDEN_ATTEMPT")
    if not world.authorization_closed:
        unknowns.append("OPEN_AUTHORIZATION_UNIVERSE")
    cap = lambda tool: capabilities.get(tool)
    for rule in world.rules:
        if rule.kind is not GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION and name not in rule.trigger_tools:
            proofs.append(_noop(rule.rule_id))
            continue
        required = cap(rule.required_tool)
        if required is None:
            proofs.append(GoalRuleProofV3(rule.rule_id, Truth.UNKNOWN, (), reason="REQUIRED_INTERFACE_UNBOUND"))
            unknowns.append(rule.rule_id)
            continue
        if rule.kind in {GoalRuleKind.REQUIRE_RESULT_TRUE, GoalRuleKind.EXCEPTION_RESULT_TRUE}:
            primitive = result_boolean_before(source, required, world.entity, rule.result_field, required_result=True)
            value, primitives, is_pending = primitive.value, (primitive,), False
        elif rule.kind is GoalRuleKind.REQUIRE_ATTEMPT_BEFORE:
            primitive = attempted_before(source, required, world.entity)
            value, primitives, is_pending = primitive.value, (primitive,), False
        elif rule.kind is GoalRuleKind.WHEN_RESULT_TRUE_REQUIRE_ATTEMPT:
            guard_capability = cap(rule.guard_tool)
            if guard_capability is None:
                proofs.append(GoalRuleProofV3(rule.rule_id, Truth.UNKNOWN, (), reason="GUARD_INTERFACE_UNBOUND"))
                unknowns.append(rule.rule_id)
                continue
            guard = result_boolean_before(source, guard_capability, world.entity, rule.result_field)
            consequent = attempted_before(source, required, world.entity)
            primitives, is_pending = (guard, consequent), False
            if guard.value is Truth.TRUE:
                value = consequent.value
            elif guard.value is Truth.FALSE:
                value = Truth.TRUE
            elif guard.value is Truth.BOTH:
                value = Truth.BOTH
            else:
                value = Truth.TRUE if consequent.value is Truth.TRUE else Truth.UNKNOWN
        elif rule.kind is GoalRuleKind.REQUIRE_ATTEMPT_BY_SESSION:
            primitive = attempted_before(source, required, world.entity)
            primitives = (primitive,)
            is_pending = not source["session_complete"] and primitive.value is not Truth.TRUE
            value = Truth.UNKNOWN if is_pending else primitive.value
        else:
            raise ValueError("unknown Goal v3 rule kind")
        proofs.append(GoalRuleProofV3(rule.rule_id, value, primitives, is_pending))
        if is_pending:
            pending.append(rule.rule_id)
        elif value is Truth.FALSE:
            violations.append(rule.rule_id)
        elif value is Truth.BOTH:
            contradictions.append(rule.rule_id)
        elif value is Truth.UNKNOWN:
            unknowns.append(rule.rule_id)
    if violations:
        status = CoreStatus.PROVED_ERROR
    elif contradictions:
        status = CoreStatus.INCONSISTENT
    elif unknowns or pending or not source["history_complete"]:
        status = CoreStatus.UNRESOLVED
    else:
        status = CoreStatus.PROVED_NO_ERROR
    alignment = ("PROVED_OUT_OF_SCOPE" if status is CoreStatus.PROVED_ERROR
        else "AMBIGUOUS_ALIGNMENT" if status in {CoreStatus.UNRESOLVED, CoreStatus.INCONSISTENT}
        else "DIRECT_GOAL" if name in world.direct_tools else "PERMITTED_AUXILIARY"
        if name in world.auxiliary_tools else "AMBIGUOUS_ALIGNMENT")
    return GoalWorldProofV3(world.world_id, status, alignment, tuple(proofs), tuple(violations),
        tuple(unknowns), tuple(contradictions), tuple(pending))


def decide_goal_alignment_v3(projection, contract, *, fixture_spec=None):
    """Aggregate all material worlds; certify only with a trusted source replay.

    The current trusted replay is the pinned controlled fixture. A later real
    source adapter must provide its own independently checked authority basis;
    absent that, even an attractive computed verdict remains UNRESOLVED.
    """
    source = validate_goal_source_v3(projection)
    if contract.source_sha256 != projection["source_sha256"]:
        raise ValueError("Goal contract belongs to another source projection")
    for world in contract.worlds:
        if world.source_sha256 != projection["source_sha256"]:
            raise ValueError("Goal world belongs to another source projection")
    worlds = tuple(evaluate_goal_world_v3(source, world) for world in contract.worlds)
    statuses = {world.status for world in worlds}
    if not contract.complete_world_inventory or len(statuses) != 1:
        status = CoreStatus.UNRESOLVED
    else:
        status = next(iter(statuses))
    if status is CoreStatus.PROVED_NO_ERROR and (not all(world.authorization_closed for world in contract.worlds)
            or not source["history_complete"] or source.get("unrelated_goal_term")):
        status = CoreStatus.UNRESOLVED
    alignment = worlds[0].alignment if len({world.alignment for world in worlds}) == 1 else "AMBIGUOUS_ALIGNMENT"
    if status in {CoreStatus.UNRESOLVED, CoreStatus.INCONSISTENT}:
        alignment = "AMBIGUOUS_ALIGNMENT"
    diagnostics = tuple(dict.fromkeys(item for world in worlds for item in
        (*world.violations, *world.unknowns, *world.contradictions, *world.pending)))
    if status not in {CoreStatus.PROVED_ERROR, CoreStatus.PROVED_NO_ERROR}:
        return GoalDecisionV3(status, alignment, worlds, None, None, diagnostics)
    certificate = GoalCertificateV3("guardian-goal-v3-certificate-v1", status, projection["source_sha256"],
        digest(asdict(contract)), worlds, contract.complete_world_inventory,
        "INDEPENDENT_SYSTEM_VIOLATION_OR_FULL_EXPLICIT_FIXTURE_CLOSURE")
    if fixture_spec is None:
        return GoalDecisionV3(CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", worlds, None, False,
            (*diagnostics, "NO_TRUSTED_CONTRACT_REPLAY"))
    from .goal_alignment_certificate_v3 import check_goal_alignment_certificate_v3
    valid, errors = check_goal_alignment_certificate_v3(certificate, projection, contract, fixture_spec)
    if not valid:
        return GoalDecisionV3(CoreStatus.UNRESOLVED, "AMBIGUOUS_ALIGNMENT", worlds, certificate, False,
            (*diagnostics, *errors))
    return GoalDecisionV3(status, alignment, worlds, certificate, True, diagnostics)
