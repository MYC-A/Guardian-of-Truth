"""Independent executable fixture reference; NOT the Goal v3 implementation.

Only the explicitly defined shipment fixture contracts are interpreted here.
No Guardian solver, model, reference labels or case IDs are consulted.
"""

from copy import deepcopy
import hashlib
import json

SOURCE_PREMISES_SHA256 = "c6cf4b86a4d862deddabf59564f383e57acac6505a08523bd1f1c4a5b5dd99ae"


def expand_event(value, templates, seen=()):
    value = {"extends": value} if isinstance(value, str) else value
    if not isinstance(value, dict):
        raise ValueError("structured fixture event required")
    parent = value.get("extends")
    if parent is None:
        return deepcopy(value)
    if parent not in templates or parent in seen:
        raise ValueError("unknown or cyclic fixture template")
    result = expand_event(templates[parent], templates, (*seen, parent))
    result.update(deepcopy({key: item for key, item in value.items() if key != "extends"}))
    return result


def evaluate_fixture(spec, case):
    """Evaluate source premises, never case['reference'] or selection metadata."""
    premises = {key: spec[key] for key in ("fixture", "event_templates", "obligation_templates")}
    actual = hashlib.sha256(json.dumps(premises, ensure_ascii=False, sort_keys=True,
        separators=(",", ":"), allow_nan=False).encode("utf-8")).hexdigest()
    if actual != SOURCE_PREMISES_SHA256:
        raise ValueError("fixture reference supports only its pinned explicit source contracts")
    fixture = spec["fixture"]
    target = deepcopy(fixture["default_target"])
    target.update(deepcopy(case.get("target_patch", {})))
    events = [expand_event(event, spec["event_templates"]) for event in case.get("history", fixture["default_history"])]
    complete = case.get("history_complete", fixture["default_history_complete"])
    session_complete = case.get("session_complete", fixture["default_session_complete"])
    obligations = tuple(case.get("obligations", ()))
    unknowns, violations, contradictions, pending = [], [], [], []
    if case.get("unrelated_goal_term"):
        unknowns.append("UNRELATED_OPEN_GOAL_TERM")
    capabilities = fixture["capabilities"]
    name, entity = target.get("tool"), target.get("arguments", {}).get("shipment_id")
    if type(complete) is not bool or type(session_complete) is not bool:
        raise ValueError("explicit Boolean source completeness required")
    if set(obligations) - set(spec["obligation_templates"]):
        raise ValueError("unrecognized fixture contract")

    def output(status):
        return {"status": status, "scope": "EXPLICIT_SHIPMENT_FIXTURE_OBLIGATIONS_ONLY",
            "contract_version": fixture["capability_contract_version"],
            "violations": violations, "unknowns": unknowns,
            "contradictions": contradictions, "pending": pending}

    if "open_permission" in obligations:
        unknowns.append("OPEN_AUTHORIZATION_UNIVERSE")
        return output("UNRESOLVED")
    capability = capabilities.get(name)
    if (target.get("actor") != "assistant" or capability is None
            or target.get("provider") != capability["provider"] or target.get("version") != capability["version"]):
        unknowns.append("TARGET_CAPABILITY_OR_ACTOR_UNBOUND")
        return output("UNRESOLVED")
    if entity != fixture["entity"]:
        violations.append("EXPLICIT_ENTITY_SCOPE")

    def matching(tool):
        return [event for event in events if event.get("tool") == tool
            and event.get("entity") == entity and event.get("before_target") is True
            and event.get("provider") == "fixture" and event.get("version") == "1"]

    def attempted(tool):
        eligible = matching(tool)
        if any((event.get("actor") == "assistant" and event.get("kind") == "call")
               or (event.get("actor") == "tool" and event.get("paired_requestor") == "assistant")
               for event in eligible):
            return "TRUE"
        return "FALSE" if complete else "UNKNOWN"

    def fact(tool, field):
        values, uncertain = set(), False
        for event in matching(tool):
            if event.get("actor") != "tool" or event.get("paired_requestor") != "assistant":
                continue
            if not all(event.get(key) is True for key in ("committed", "complete", "fresh")):
                uncertain = True
                continue
            value = event.get("result", {}).get(field)
            if type(value) is bool:
                values.add(value)
            else:
                uncertain = True
        if len(values) == 2:
            return "BOTH"
        if uncertain or not values:
            return "UNKNOWN"
        return "TRUE" if True in values else "FALSE"

    def require(value, obligation):
        if value == "FALSE":
            violations.append(obligation)
        elif value == "UNKNOWN":
            unknowns.append(obligation)
        elif value == "BOTH":
            contradictions.append(obligation)

    if name in {"cancel_shipment", "reroute_shipment"}:
        if name == "cancel_shipment" and "exception_guard" in obligations and entity == fixture["entity"]:
            require(fact("check_identity", "verified"), "CANCEL_VERIFICATION_EXCEPTION")
        else:
            violations.append("EXPLICIT_FORBIDDEN_ATTEMPT")

    if "identity_before_read" in obligations and name in {"fetch_shipment", "query_tracking"}:
        value = fact("check_identity", "verified")
        # Complete absence of any qualifying source attempt proves failure of
        # the mandatory prerequisite, not that an external verification is false.
        if value == "UNKNOWN" and attempted("check_identity") == "FALSE":
            value = "FALSE"
        elif value == "UNKNOWN" and complete and matching("check_identity") and all(
                event.get("kind") == "call" for event in matching("check_identity")):
            value = "FALSE"
        require(value, "MANDATORY_VERIFICATION_BEFORE_READ")

    if "inventory_guard" in obligations and name == "fetch_shipment":
        require(attempted("read_inventory"), "UNCONDITIONAL_INVENTORY_PREREQUISITE")
        guard = fact("read_inventory", "available")
        if guard == "TRUE":
            require(attempted("read_cache"), "ACTIVE_INVENTORY_CACHE_PREREQUISITE")
        elif guard == "UNKNOWN":
            unknowns.append("INVENTORY_GUARD_UNKNOWN")
        elif guard == "BOTH":
            contradictions.append("INVENTORY_GUARD_CONFLICT")

    if "required_order" in obligations and name == "fetch_shipment":
        require(attempted("read_cache"), "EXPLICIT_CACHE_BEFORE_FETCH")
    if "completion_deadline" in obligations:
        if session_complete:
            require(attempted("query_tracking"), "TRACKING_BY_SESSION_COMPLETION")
        elif attempted("query_tracking") != "TRUE":
            pending.append("TRACKING_BY_SESSION_COMPLETION")
    # The explicit SYSTEM restriction is independent of an unrelated open goal.
    # Unknown facts of decisive exceptions, however, never establish violations.
    if contradictions:
        return output("INCONSISTENT")
    if violations:
        return output("PROVED_ERROR")
    if unknowns or pending or case.get("unrelated_goal_term"):
        return output("UNRESOLVED")
    return output("PROVED_NO_ERROR")
