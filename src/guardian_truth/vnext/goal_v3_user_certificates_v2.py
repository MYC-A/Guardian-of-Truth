"""Independent replay for the exact USER fragment and controlled source format.

No compiler, world evaluator, Policy path or LLM is called here. Parsing is a
shared authority boundary; evaluation and event queries are separate code.
These receipts prove only a Goal-local claim conditional on the trusted
adapter's catalog, pairing, freshness and completeness assertions. They are
not external trace authentication, general NL entailment or Core certificates.
"""

from dataclasses import asdict, dataclass

from .goal_v3_semantics_v2 import (
    GoalAlignmentV2, GoalCandidateDecisionV2, GoalLocalStatusV2, GoalWorldResultV2,
)
from .goal_v3_user_contract_v2 import parse_user_contract_v2
from .integrity import digest
from .types import Truth


SCOPE = "EXACT_USER_FRAGMENT_TRUSTED_ADAPTER_GOAL_LOCAL_V2"


@dataclass(frozen=True)
class GoalReplayFactV2:
    rule_id: str
    query: str
    tool: str
    value: Truth
    evidence_ids: tuple[str, ...]
    absence_basis: str | None = None


@dataclass(frozen=True)
class GoalUserCertificateV2:
    schema_version: str
    scope: str
    source_sha256: str
    contract_sha256: str
    candidate: GoalCandidateDecisionV2
    facts: tuple[GoalReplayFactV2, ...]


def _replay(source):
    contract = parse_user_contract_v2(source)
    if contract is None:
        return None
    events = source.get("history_prefix")
    if (not isinstance(events, list) or type(source.get("history_complete")) is not bool
            or type(source.get("session_complete")) is not bool):
        return None
    seen = set()
    for event in events:
        if not isinstance(event, dict):
            return None
        eid = event.get("event_id")
        if (not isinstance(eid, str) or not eid or eid in seen
                or not isinstance(event.get("actor"), str)
                or event["actor"] not in {"assistant", "user", "tool"}
                or not isinstance(event.get("kind"), str)
                or type(event.get("before_target")) is not bool):
            return None
        seen.add(eid)
        if event["kind"] in {"call", "result"} and any(
                not isinstance(event.get(key), str) or not event[key]
                for key in ("tool", "entity", "provider", "version")):
            return None
    target = source.get("target_action")
    if not isinstance(target, dict) or not isinstance(target.get("tool"), str):
        return None
    tool = target["tool"]
    catalog = source["tool_catalog"]
    cap = catalog.get(tool)
    if (not isinstance(cap, dict) or target.get("actor") != "assistant"
            or target.get("kind") != "tool_call"
            or not isinstance(target.get("entity"), str) or not target["entity"]
            or any(not isinstance(cap.get(key), str) or not cap[key]
                or target.get(key) != cap[key] for key in ("provider", "version"))):
        return None
    facts = []

    def matching(name):
        binding = catalog[name]
        return [event for event in events if event.get("tool") == name
            and event.get("entity") == contract.entity and event["before_target"]
            and all(event.get(key) == binding[key] for key in ("provider", "version"))]

    def attempt(rule, name):
        ids = tuple(event["event_id"] for event in matching(name)
            if (event["actor"] == "assistant" and event["kind"] == "call")
            or (event["actor"] == "tool" and event["kind"] == "result"
                and event.get("paired_requestor") == "assistant"))
        value = Truth.TRUE if ids else Truth.FALSE if source["history_complete"] else Truth.UNKNOWN
        return GoalReplayFactV2(rule, "ASSISTANT_ATTEMPT_BEFORE_TARGET", name, value, ids,
            "COMPLETE_TRUSTED_SOURCE_PREFIX" if value is Truth.FALSE else None)

    def boolean(rule, name, field):
        observations = []
        for event in matching(name):
            result = event.get("result")
            if (event["actor"] == "tool" and event["kind"] == "result"
                    and event.get("paired_requestor") == "assistant"
                    and all(event.get(key) is True for key in ("fresh", "complete", "committed"))
                    and event.get("call_status") == "SUCCESS" and isinstance(result, dict)
                    and type(result.get(field)) is bool):
                observations.append((event["event_id"], result[field]))
        positive = any(value for _, value in observations)
        negative = any(not value for _, value in observations)
        value = (Truth.BOTH if positive and negative else Truth.TRUE if positive
            else Truth.FALSE if negative else Truth.UNKNOWN)
        return GoalReplayFactV2(rule, "FRESH_COMMITTED_BOOLEAN:" + field, name, value,
            tuple(eid for eid, _ in observations))

    def effect(rule, name):
        semantic = catalog[name].get("effect_contract")
        expected = semantic.get("confirmed_when") if isinstance(semantic, dict) else None
        if (not isinstance(expected, dict) or expected.get("call_status") != "SUCCESS"
                or expected.get("committed") is not True or expected.get("equals") is not True
                or not isinstance(expected.get("result_field"), str)):
            return GoalReplayFactV2(rule, "CONFIRMED_EFFECT", name, Truth.UNKNOWN, ())
        observed = boolean(rule, name, expected["result_field"])
        tried = attempt(rule, name)
        value = observed.value if observed.value in {Truth.TRUE, Truth.BOTH} else (
            Truth.FALSE if tried.value is Truth.FALSE else Truth.UNKNOWN)
        return GoalReplayFactV2(rule, "CONFIRMED_EFFECT", name, value, observed.evidence_ids,
            tried.absence_basis if value is Truth.FALSE else None)

    direct = set()
    auxiliary = set()
    forbidden = set()
    mandatory_kinds = {"REQUIRE_ATTEMPT_BEFORE", "REQUIRE_RESULT_TRUE",
        "WHEN_RESULT_TRUE_REQUIRE_ATTEMPT", "REQUIRE_EFFECT_BY_SESSION"}
    for rule in contract.clauses:
        if rule.kind == "DIRECT_TOOLS":
            direct.update(rule.tools)
        elif rule.kind == "AUXILIARY_TOOLS":
            auxiliary.update(rule.tools)
        elif rule.kind == "FORBID_ATTEMPT":
            forbidden.add(rule.required_tool)
    # No undeclared precedence for contradictory permission/prohibition text.
    # The current single-world compiler is insufficient to certify this input.
    if forbidden & (direct | auxiliary):
        return None
    for rule in contract.clauses:
        if rule.kind in mandatory_kinds:
            auxiliary.add(rule.required_tool)
        if rule.guard_tool:
            auxiliary.add(rule.guard_tool)
    closed = any(rule.kind == "CLOSE_AUTHORIZATION" for rule in contract.clauses)
    same_entity = target["entity"] == contract.entity
    scope_error = closed and not (same_entity and tool in direct | auxiliary)
    prohibition_error = same_entity and tool in forbidden
    fields = cap.get("goal_fields")
    alignment = (GoalAlignmentV2.OUT_OF_SCOPE if scope_error or prohibition_error
        else GoalAlignmentV2.DIRECT if same_entity and tool in direct
            and isinstance(fields, list) and contract.desired_field in fields
        else GoalAlignmentV2.AUXILIARY if same_entity and tool in auxiliary
        else GoalAlignmentV2.AMBIGUOUS)
    violations = (["SCOPE"] if scope_error else []) + (["PROHIBITION"] if prohibition_error else [])
    conflicts, unknown, pending = [], [], []
    for rule in contract.clauses:
        if rule.kind not in mandatory_kinds:
            continue
        deadline = rule.kind == "REQUIRE_EFFECT_BY_SESSION"
        applies = Truth.TRUE if deadline or same_entity and rule.trigger_tool == tool else Truth.FALSE
        due = not deadline or source["session_complete"]
        fact = (effect(rule.rule_id, rule.required_tool) if deadline else
            boolean(rule.rule_id, rule.required_tool, rule.result_field)
            if rule.kind == "REQUIRE_RESULT_TRUE" else attempt(rule.rule_id, rule.required_tool))
        facts.append(fact)
        if rule.guard_tool and applies is Truth.TRUE:
            guard = boolean(rule.rule_id, rule.guard_tool, rule.result_field)
            facts.append(guard)
            applies = guard.value
        if applies is Truth.FALSE:
            continue
        if applies is Truth.BOTH or fact.value is Truth.BOTH:
            conflicts.append(rule.rule_id)
        elif fact.value is Truth.TRUE:
            continue
        elif applies is Truth.UNKNOWN:
            unknown.append(rule.rule_id)
        elif not due:
            pending.append(rule.rule_id)
        elif fact.value is Truth.UNKNOWN:
            unknown.append(rule.rule_id)
        else:
            violations.append(rule.rule_id)
    status = (GoalLocalStatusV2.ERROR if violations else GoalLocalStatusV2.INCONSISTENT
        if conflicts else GoalLocalStatusV2.UNRESOLVED if unknown or not closed
            or not source["history_complete"] or alignment in
                {GoalAlignmentV2.AMBIGUOUS, GoalAlignmentV2.OUT_OF_SCOPE}
        else GoalLocalStatusV2.NO_ERROR)
    unrelated = () if source.get("unrelated_state") is None else ("unrelated_state",)
    world = GoalWorldResultV2("user-fragment:0", status, alignment, tuple(violations),
        tuple(conflicts), tuple(unknown), tuple(pending), unrelated)
    return contract, GoalCandidateDecisionV2(status, alignment, (world,), True), tuple(facts)


def issue_user_certificate_v2(source, candidate):
    """Accept a candidate only after independent whole-source replay."""
    if not isinstance(candidate, GoalCandidateDecisionV2):
        return None
    replay = _replay(source)
    if replay is None:
        return None
    contract, expected, facts = replay
    if candidate != expected or expected.status not in {GoalLocalStatusV2.ERROR, GoalLocalStatusV2.NO_ERROR}:
        return None
    return GoalUserCertificateV2("guardian-goal-user-certificate-v2", SCOPE, digest(source),
        digest(asdict(contract)), candidate, facts)


def check_user_certificate_v2(certificate, source):
    """Recompute evidence, omitted alternatives, closure and local consequence."""
    if not isinstance(certificate, GoalUserCertificateV2):
        return False, ("CERTIFICATE_TYPE",)
    replayed = issue_user_certificate_v2(source, certificate.candidate)
    if replayed is None:
        return False, ("SOURCE_OR_CANDIDATE_NOT_CERTIFIABLE",)
    if certificate != replayed:
        return False, ("CERTIFICATE_REPLAY_MISMATCH",)
    return True, ()
