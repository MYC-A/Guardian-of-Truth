"""Small source-linked action graph for a deliberately bounded policy family.

The compiler accepts only three explicit policy patterns. Every policy bullet
must compile before SAFE is possible. It never treats a model's unverified
summary, a tool call without its result, or another entity as a witness.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
import re

from action_trigger_v1 import _WRITE, _actions, _target, _tool_description
from call_scope_v1 import malformed_call
from temporal_counterevidence_v1 import _json_dict, _observations, _same_entity


@dataclass(frozen=True)
class Rule:
    rule_id: str
    kind: str  # PRECONDITION, LATEST, AFTER_SUCCESS
    quote: str
    action: str
    entity: str
    topic: str = ""
    state: str = ""


def _bullets(policy: str) -> list[str] | None:
    bullets: list[str] = []
    for line in policy.splitlines():
        line = line.strip()
        if not line:
            continue
        if line.startswith("#"):
            if not re.fullmatch(r"#+\s+[\w ]+policy", line, re.I):
                return None
            continue
        if line.startswith("- "):
            bullets.append(line[2:])
        elif bullets:
            bullets[-1] += " " + line
        else:
            return None
    return bullets or None


def compile_policy(policy: str) -> tuple[list[Rule], list[str]]:
    bullets = _bullets(policy)
    if bullets is None:
        return [], ["policy_bullets_unbound"]
    rules: list[Rule] = []
    errors: list[str] = []
    pre = re.compile(
        r"Before (?P<verb>\w+) any \w+, check that the (?P<topic>[\w-]+) is "
        r"(?P<state>\w+) for the SAME (?P<entity>\w+)\. "
        r"A check for a different (?P=entity) does not satisfy this condition\.", re.I)
    latest = re.compile(
        r"Use the latest (?P<topic>[\w-]+)-check result for that (?P<entity>\w+)\. "
        r"An earlier (?P<state>\w+) result cannot override a later (?P<negative>\w+) result\.", re.I)
    after = re.compile(
        r"After a (?P<object>\w+) has been (?P<verb>\w+) successfully, "
        r"record a [\w ]+ audit for the SAME (?P<entity>\w+)\. "
        r"Do not record the audit before successful (?P<noun>\w+)\.", re.I)
    for index, quote in enumerate(bullets):
        match = pre.fullmatch(quote)
        if match:
            action = _actions(match["verb"])
            if len(action) == 1:
                rules.append(Rule(f"p{index}", "PRECONDITION", quote, action[0],
                                  match["entity"].lower(), match["topic"].lower(),
                                  match["state"].lower()))
                continue
        match = latest.fullmatch(quote)
        if match and match["negative"].lower() == "in" + match["state"].lower():
            rules.append(Rule(f"p{index}", "LATEST", quote, "",
                              match["entity"].lower(), match["topic"].lower(),
                              match["state"].lower()))
            continue
        match = after.fullmatch(quote)
        if match:
            action = _actions(match["verb"])
            noun_action = _actions(match["noun"])
            if len(action) == 1 and action == noun_action:
                rules.append(Rule(f"p{index}", "AFTER_SUCCESS", quote, "audit",
                                  match["entity"].lower(), state=action[0]))
                continue
        errors.append(f"unsupported_policy_bullet:{index}")
    # A latest modifier must attach to exactly one source-backed precondition.
    for rule in rules:
        if rule.kind == "LATEST":
            matching = [other for other in rules if other.kind == "PRECONDITION"
                        and (other.entity, other.topic, other.state) ==
                        (rule.entity, rule.topic, rule.state)]
            if len(matching) != 1:
                errors.append(f"latest_clause_unbound:{rule.rule_id}")
    return rules, errors


def _same_target_id(target: dict, call: dict) -> bool:
    keys = [key for key, value in target.items()
            if key.endswith("_id") and isinstance(value, str) and value]
    return len(keys) == 1 and call.get(keys[0]) == target[keys[0]]


def _is_check(item: dict, name: str, topic: str) -> bool:
    desc = _tool_description(item["tools"].get(name, ""), name)
    if not desc:
        return False
    head = desc.split()[0].lower()
    return head in {"check", "verify", "read", "lookup", "get", "inspect"} and topic in desc.lower()


def _is_reported_effect_tool(item: dict, name: str, action: str) -> bool:
    desc = _tool_description(item["tools"].get(name, ""), name)
    if not desc or action not in _actions(desc):
        return False
    head = desc.split()[0].lower()
    return head in {"replace", "swap", "exchange", "refund", "dispatch", "send",
                    "transfer", "cancel", "perform", "execute", "process", "issue"}


def _check_precondition(item: dict, rule: Rule) -> tuple[str, str, list[int], list[dict]]:
    target = item["target"]["arguments"]
    if not isinstance(target, dict):
        return "UNKNOWN", "target_arguments_unbound", [], []
    paired = list(_observations(item))
    paired_calls = {call_event["event_id"] for call_event, *_ in paired}
    paired_results = {result_event["event_id"] for _, result_event, *_ in paired}
    candidates: list[tuple[int, bool, int]] = []
    unresolved: list[int] = []
    for event in item["history"]:
        if event.get("kind") != "call" or event.get("role") != "assistant":
            continue
        if not _is_check(item, event.get("name") or "", rule.topic):
            continue
        args = _json_dict(event.get("text", ""))
        if args is None:
            unresolved.append(event["event_id"])
            continue
        if not _same_target_id(target, args):
            continue
        if event["event_id"] not in paired_calls:
            unresolved.append(event["event_id"])
    for event in item["history"]:
        if event.get("kind") != "result" or event["event_id"] in paired_results:
            continue
        if not _is_check(item, event.get("name") or "", rule.topic):
            continue
        result = _json_dict(event.get("text", ""))
        if (result is None or _same_target_id(target, result)
                or rule.state in result and not any(key.endswith("_id") for key in result)):
            unresolved.append(event["event_id"])
    for call_event, result_event, call, result in paired:
        if not _is_check(item, call_event["name"], rule.topic):
            continue
        if not _same_target_id(target, call):
            continue
        if not _same_entity(target, call, result):
            unresolved.append(call_event["event_id"])
            continue
        value = result.get(rule.state)
        if type(value) is not bool:
            unresolved.append(result_event["event_id"])
            continue
        candidates.append((result_event["event_id"], value, call_event["event_id"]))
    if unresolved and (not candidates or max(unresolved) > max(row[0] for row in candidates)):
        return "UNKNOWN", "newest_relevant_check_unresolved", sorted(unresolved), []
    if not candidates:
        return "BROKEN", "no_paired_same_entity_check", [], []
    latest_id, value, call_id = max(candidates)
    edges = [{"from": f"e{call_id}", "to": f"e{latest_id}", "type": "paired_result"},
             {"from": f"e{latest_id}", "to": rule.rule_id,
              "type": "satisfies" if value else "contradicts"}]
    for old_id, _, _ in candidates:
        if old_id != latest_id:
            edges.append({"from": f"e{old_id}", "to": f"e{latest_id}",
                          "type": "superseded_by"})
    return ("SATISFIED" if value else "BROKEN"), "latest_paired_same_entity_check", [call_id, latest_id], edges


def _check_after_success(item: dict, rule: Rule) -> tuple[str, str, list[int], list[dict]]:
    target = item["target"]["arguments"]
    if not isinstance(target, dict):
        return "UNKNOWN", "target_arguments_unbound", [], []
    unresolved: list[int] = []
    for call_event, result_event, call, result in reversed(list(_observations(item))):
        if (not _is_reported_effect_tool(item, call_event["name"], rule.state)
                or not _same_target_id(target, call)):
            continue
        if not _same_entity(target, call, result):
            unresolved.append(call_event["event_id"])
            continue
        if result.get("success") is False or result.get("error") or str(result.get("status", "")).lower() in {"failed", "error"}:
            continue
        if result.get("success") is True or str(result.get("status", "")).lower() in {"completed", "succeeded", "success", "dispatched"}:
            ids = [call_event["event_id"], result_event["event_id"]]
            return "SATISFIED", "prior_same_entity_reported_success", ids, [
                {"from": f"e{ids[0]}", "to": f"e{ids[1]}", "type": "paired_result"},
                {"from": f"e{ids[1]}", "to": rule.rule_id, "type": "satisfies"}]
        unresolved.append(result_event["event_id"])
    # An unpaired relevant call also blocks an absence claim.
    paired_ids = {c[0]["event_id"] for c in _observations(item)}
    for event in item["history"]:
        if event.get("kind") != "call" or event["event_id"] in paired_ids:
            continue
        name = event.get("name") or ""
        call = _json_dict(event.get("text", ""))
        if _is_reported_effect_tool(item, name, rule.state) and (call is None or _same_target_id(target, call)):
            unresolved.append(event["event_id"])
    if unresolved:
        return "UNKNOWN", "prior_action_result_unresolved", sorted(unresolved), []
    return "BROKEN", "no_prior_same_entity_success", [], []


def analyze(item: dict) -> dict:
    """Return a certificate only for a fully compiled, explicitly closed family."""
    structural = malformed_call(item)
    if structural:
        return {"verdict": "VIOLATION", "coverage": "STRUCTURAL", "errors": structural,
                "nodes": [], "edges": [], "checks": []}
    rules, errors = compile_policy(item.get("policy", ""))
    kind, actions = _target(item)
    target_desc = _tool_description(item["tools"].get(item["target"]["tool"], ""),
                                    item["target"]["tool"])
    if (target_desc and (kind == "READ" and _actions(target_desc)
            or re.search(r"\b(?:and|then)\s+(?:perform|execute|"
                         + "|".join(sorted(_WRITE)) + r")\b", target_desc, re.I))):
        kind = "UNKNOWN"
    if kind == "UNKNOWN":
        errors.append("target_action_unbound")
    nodes = [{"id": "target", "type": "action", "tool": item["target"]["tool"],
              "kind": kind, "actions": list(actions)}]
    nodes.extend({"id": rule.rule_id, "type": "policy", "kind": rule.kind,
                  "quote": rule.quote} for rule in rules)
    edges: list[dict] = []
    checks: list[dict] = []
    applicable = []
    for rule in rules:
        if rule.kind == "LATEST":
            continue
        if kind == "WRITE" and rule.action in actions:
            applicable.append(rule)
            edges.append({"from": rule.rule_id, "to": "target", "type": "governs"})
    for rule in applicable:
        if rule.kind == "PRECONDITION":
            status, reason, event_ids, proof_edges = _check_precondition(item, rule)
        else:
            status, reason, event_ids, proof_edges = _check_after_success(item, rule)
        checks.append({"rule_id": rule.rule_id, "status": status,
                       "reason": reason, "event_ids": event_ids})
        edges.extend(proof_edges)
        for event_id in event_ids:
            if not any(node["id"] == f"e{event_id}" for node in nodes):
                event = next(e for e in item["history"] if e["event_id"] == event_id)
                nodes.append({"id": f"e{event_id}", "type": "event",
                              "kind": event["kind"], "tool": event.get("name")})
    # Unsupported policy text can contain another applicable restriction.
    # Even a visible broken check is not promoted if the policy was not fully
    # interpreted, because this prototype only claims coverage of its grammar.
    if errors:
        verdict = "UNKNOWN"
    elif any(check["status"] == "BROKEN" for check in checks):
        verdict = "VIOLATION"
    elif any(check["status"] == "UNKNOWN" for check in checks):
        verdict = "UNKNOWN"
    else:
        verdict = "SAFE"
    return {"verdict": verdict, "coverage": "COMPLETE_BOUNDED_GRAMMAR" if not errors else "OPEN",
            "errors": errors, "nodes": nodes, "edges": edges, "checks": checks}
