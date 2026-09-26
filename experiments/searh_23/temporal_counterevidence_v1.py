"""Narrow source-backed counterevidence for wrong model timing claims.

Only an explicit latest Boolean observation or an earlier reported successful
action can retract the corresponding BROKEN claim. This never proves global
call safety or an external business postcondition. Unknown pairing, entity,
result shape or policy wording stays unresolved.
"""

from __future__ import annotations

from dataclasses import dataclass
import json
import re

from action_trigger_v1 import (_actions, _exact_unique, _target,
                               _tool_description, bind_clause)
from call_scope_v1 import malformed_call


@dataclass(frozen=True)
class CounterEvidence:
    status: str  # REFUTED or UNRESOLVED
    reason: str
    event_ids: tuple[int, ...] = ()


def _json_dict(text: str) -> dict | None:
    try:
        value = json.loads(text)
    except (TypeError, ValueError):
        return None
    return value if isinstance(value, dict) else None


def _observations(item: dict):
    """Only immediately paired assistant calls/results; no guessed FIFO join."""
    pending: dict[str, list[dict]] = {}
    for event in item["history"]:
        name = event.get("name")
        if event["kind"] == "call" and event["role"] == "assistant" and name:
            pending.setdefault(name, []).append(event)
        elif event["kind"] == "result" and event["role"] in {"assistant", "tool"} and name:
            candidates = pending.pop(name, [])
            if len(candidates) != 1:
                continue
            first = candidates[0]
            if event["event_id"] != first["event_id"] + 1:
                continue
            call, result = _json_dict(first["text"]), _json_dict(event["text"])
            if call is not None and result is not None:
                yield first, event, call, result


def _same_entity(target: dict, call: dict, result: dict) -> bool:
    keys = [key for key, value in target.items()
            if key.endswith("_id") and isinstance(value, str) and value
            and key in call and key in result]
    return len(keys) == 1 and all(
        call[key] == result[key] == target[key] for key in keys)


def _fact_spec(quote: str) -> tuple[str, str] | None:
    text = " ".join(quote.lower().split())
    if re.search(r"\b(?:identity|confirmation|authorization|approval)\b", text):
        return None  # A positive stock/address result cannot satisfy a conjunction.
    if (text.startswith("before ") and
            re.search(r"\bcheck that the address is valid\b", text) and
            not re.search(r"\b(?:not|never|unless)\b", text)) or (
            text.startswith("use the latest address-check result") and
            "earlier valid" in text and "later invalid" in text):
        return "address", "valid"
    if (re.search(r"\b(?:replacement|replace|dispatch|send)\b.*\b"
                  r"(?:may be executed|only when)\b", text)
            and "latest" in text and
            re.search(r"\b(?:stock|inventory)\b.*\bavailable\b", text)
            and not re.search(r"\b(?:not|never|unless)\b", text)):
        return "stock", "available"
    return None


def _latest_positive(item: dict, quote: str) -> CounterEvidence:
    spec = _fact_spec(quote)
    if spec is None:
        return CounterEvidence("UNRESOLVED", "unsupported_fact_clause")
    topic, field = spec
    target = item["target"]["arguments"]
    if not isinstance(target, dict):
        return CounterEvidence("UNRESOLVED", "target_arguments_unbound")
    candidates = []
    for call_event, result_event, call, result in _observations(item):
        desc = _tool_description(item["tools"].get(call_event["name"], ""),
                                 call_event["name"])
        if not desc:
            continue
        first = desc.split()[0].lower()
        if first not in {"read", "look", "lookup", "get", "find", "check",
                         "compare", "verify", "search", "retrieve"}:
            continue
        if topic == "address" and "address" not in desc.lower():
            continue
        if topic == "stock" and not re.search(r"\b(?:stock|inventory)\b", desc, re.I):
            continue
        if not _same_entity(target, call, result):
            continue
        candidates.append((result_event["event_id"], result.get(field)))
    if not candidates:
        return CounterEvidence("UNRESOLVED", "no_paired_same_entity_observation")
    latest_id, latest_value = max(candidates)
    # A later source result with the same entity/property but no trusted pair
    # means the chosen result may no longer be the latest observation.
    for event in item["history"]:
        if event["event_id"] <= latest_id or event["kind"] != "result":
            continue
        desc = _tool_description(item["tools"].get(event.get("name"), ""),
                                 event.get("name") or "")
        if not desc or not ("address" in desc.lower() if topic == "address"
                            else re.search(r"\b(?:stock|inventory)\b", desc, re.I)):
            continue
        value = _json_dict(event["text"])
        if not value or field not in value:
            continue
        ids = [key for key in target if key.endswith("_id")
               and key in value and value[key] == target[key]]
        if len(ids) == 1:
            return CounterEvidence("UNRESOLVED", "later_observation_pair_ambiguous")
    if latest_value is True:
        return CounterEvidence("REFUTED", "latest_matching_observation_is_positive",
                               (latest_id,))
    return CounterEvidence("UNRESOLVED", "latest_observation_not_positive")


def _prior_reported_action(item: dict, quote: str) -> CounterEvidence:
    normalized = " ".join(quote.lower().split())
    if not normalized.startswith("after ") or "," not in normalized:
        return CounterEvidence("UNRESOLVED", "not_explicit_after_rule")
    prerequisite = _actions(normalized.split(",", 1)[0])
    if re.search(r"\b(?:and|or)\b", normalized.split(",", 1)[0]):
        return CounterEvidence("UNRESOLVED", "compound_prerequisite_unbound")
    target_kind, target_actions = _target(item)
    if target_kind != "WRITE" or "audit" not in target_actions or not prerequisite:
        return CounterEvidence("UNRESOLVED", "action_pair_unbound")
    target = item["target"]["arguments"]
    if not isinstance(target, dict):
        return CounterEvidence("UNRESOLVED", "target_arguments_unbound")
    for call_event, result_event, call, result in reversed(list(_observations(item))):
        desc = _tool_description(item["tools"].get(call_event["name"], ""),
                                 call_event["name"])
        first = desc.split()[0].lower() if desc else ""
        if (not desc or first in {"record", "log", "write", "read", "get",
                                  "check", "look", "lookup", "verify", "search"}
                or not set(_actions(desc)) & set(prerequisite)
                or not _same_entity(target, call, result)):
            continue
        if (result.get("success") is not False and not result.get("error")
                and str(result.get("status", "")).lower() in {
                    "completed", "succeeded", "success", "dispatched"}):
            return CounterEvidence("REFUTED", "reported_action_success_precedes_audit",
                                   (call_event["event_id"], result_event["event_id"]))
    return CounterEvidence("UNRESOLVED", "no_paired_same_entity_prior_success")


def refute_broken(item: dict, quote: str) -> CounterEvidence:
    if not _exact_unique(item["policy"], quote):
        return CounterEvidence("UNRESOLVED", "policy_quote_not_unique_exact")
    binding = bind_clause(item, quote)
    if binding.status == "EXCLUDED":
        return CounterEvidence("REFUTED", "clause_does_not_govern_target_action")
    for checker in (_latest_positive, _prior_reported_action):
        evidence = checker(item, quote)
        if evidence.status == "REFUTED":
            return evidence
    return CounterEvidence("UNRESOLVED", "no_verified_counterevidence")


def audit_broken(answer: dict, item: dict) -> dict:
    shape_errors = malformed_call(item)
    if shape_errors:
        return {"verdict": "VIOLATION", "structural_errors": shape_errors,
                "counterevidence": []}
    checks = answer.get("checks")
    if answer.get("verdict") != "VIOLATION" or not isinstance(checks, list):
        return {"verdict": answer.get("verdict"), "structural_errors": [],
                "counterevidence": []}
    evidence = [(index, refute_broken(item, str(check.get("policy_quote", ""))))
                for index, check in enumerate(checks)
                if isinstance(check, dict) and check.get("status") == "BROKEN"]
    retained = [entry for entry in evidence if entry[1].status != "REFUTED"]
    verdict = "VIOLATION" if retained else "UNKNOWN"
    return {"verdict": verdict, "structural_errors": [],
            "counterevidence": [{"check": index, **finding.__dict__}
                                for index, finding in evidence]}
