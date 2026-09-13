"""Source-scoped Goal v3 primitives; no policy/goal interpretation or solver."""

from .goal_alignment_records_v3 import GoalPrimitiveV3
from .integrity import digest
from .types import Truth


def validate_goal_source_v3(projection):
    if (not isinstance(projection, dict)
            or projection.get("schema_version") != "guardian-goal-v3-source-projection-v1"
            or not isinstance(projection.get("source"), dict)
            or projection.get("source_sha256") != digest(projection["source"])):
        raise ValueError("exact source-owned Goal v3 projection required")
    source = projection["source"]
    events = source.get("history_prefix")
    if (not isinstance(events, list) or type(source.get("history_complete")) is not bool
            or type(source.get("session_complete")) is not bool
            or source["history_complete"] and not source.get("history_completeness_basis")):
        raise ValueError("explicit ordered source history and completeness premise required")
    for ordinal, event in enumerate(events):
        if (not isinstance(event, dict) or event.get("ordinal") != ordinal
                or event.get("event_id") != f"source-event:{ordinal:04d}"
                or not isinstance(event.get("source"), dict)):
            raise ValueError("source event order/identity mismatch")
    return source


def history_closed(source):
    return source["history_complete"] and bool(source["history_completeness_basis"])


def matching_history(source, capability, entity):
    """Do not select a favorable entity/version/result or include later events."""
    return tuple(event for event in source["history_prefix"]
        if event["source"].get("tool") == capability.name
        and event["source"].get("entity") == entity
        and event["source"].get("provider") == capability.provider
        and event["source"].get("version") == capability.version
        and event["source"].get("before_target") is True)


def attempted_before(source, capability, entity):
    eligible = matching_history(source, capability, entity)
    support = tuple(event["event_id"] for event in eligible
        if (event["source"].get("actor") == "assistant" and event["source"].get("kind") == "call")
        or (event["source"].get("actor") == "tool"
            and event["source"].get("paired_requestor") == "assistant"))
    closed = history_closed(source)
    return GoalPrimitiveV3(f"attempt:{capability.name}:{entity}", Truth.TRUE if support else Truth.FALSE if closed else Truth.UNKNOWN,
        support, (), () if support else ("NO_ELIGIBLE_PRIOR_ATTEMPT",), closed,
        "CALL_ATTEMPTED_OR_SOURCE_PAIRED_RESULT_NOT_BUSINESS_EFFECT")


def result_boolean_before(source, capability, entity, field, *, required_result=False):
    """Only committed, complete, fresh TOOL results establish a Boolean field.

    A closed prefix can prove that a mandatory qualifying RESULT was omitted;
    it cannot prove the external business-state field false from missing data.
    """
    eligible = matching_history(source, capability, entity)
    true_ids, false_ids, uncertain_ids = [], [], []
    for event in eligible:
        row = event["source"]
        if row.get("actor") != "tool" or row.get("paired_requestor") != "assistant":
            continue
        if not all(row.get(key) is True for key in ("committed", "complete", "fresh")):
            uncertain_ids.append(event["event_id"])
            continue
        value = row.get("result", {}).get(field) if isinstance(row.get("result"), dict) else None
        if type(value) is bool:
            (true_ids if value else false_ids).append(event["event_id"])
        else:
            uncertain_ids.append(event["event_id"])
    closed = history_closed(source)
    if true_ids and false_ids:
        truth = Truth.BOTH
    elif uncertain_ids:
        truth = Truth.UNKNOWN
    elif true_ids:
        truth = Truth.TRUE
    elif false_ids:
        truth = Truth.FALSE
    elif required_result and closed:
        truth = Truth.FALSE
    else:
        truth = Truth.UNKNOWN
    missing = () if true_ids or false_ids else (
        ("NONQUALIFYING_PRIOR_RESULT",) if uncertain_ids else ("NO_QUALIFYING_PRIOR_RESULT",))
    return GoalPrimitiveV3(f"result:{capability.name}:{entity}:{field}:required={required_result}", truth,
        tuple(true_ids), tuple(false_ids), missing, closed,
        "QUALIFYING_SOURCE_TOOL_RESULT_FIELD_OR_REQUIRED_RESULT_ABSENCE")
