#!/usr/bin/env python3
"""Extractive action-feasibility proposal for refusals and handoffs.

This is an experimental positive-only arm, not a proof that every policy
prerequisite was found. Exact quotes, entity IDs and tool membership are
checked mechanically; semantic completeness remains a measured risk.
"""
from __future__ import annotations

import hashlib
import json
import re
from pathlib import Path

from guardian_truth.parsing import parse_catalog, parse_events
from tq_questions import Mistral
from typed_witnesses import (entity_anchors, exact_literal, same_entity,
                             unique_whitespace_span)

REFUSAL = re.compile(
    r"не могу|невозможно|нельзя|нет способа|переда[юём]|специалист|"
    r"can't|cannot|impossible|not possible|transfer|escalat|human agent",
    re.IGNORECASE)
SYSTEM = ("Identify ONLY a currently feasible alternative to an assistant's "
          "refusal, handoff, or wrong plan. Use only the provided dialogue and "
          "policy. If any prerequisite is unobserved, uncertain, out of scope, "
          "or for another entity or amount, set candidate=false. If a later "
          "observation supersedes an earlier one, use the later one. Return a "
          "JSON object with candidate (boolean), kind (false_refusal, "
          "premature_transfer, wrong_plan, or none), response_quote, "
          "policy_quote, user_quote, tool, premises (array of objects with "
          "event integer and quote), missing_premises (array of strings), "
          "entity_ids (array of exact ID strings), amount (integer if the "
          "requested action names a monetary amount; otherwise null), and "
          "short reason. Quotes "
          "must be verbatim substrings. Never infer tool success from a call.")
SYSTEM_V2 = SYSTEM + (
    " Here candidate=true means the POLICY REQUIRES the agent to take the "
    "named action NOW instead of the response's refusal or handoff. A policy "
    "permission to refuse or transfer never supports candidate=true. Cite the "
    "mandatory clause containing the exact tool name. Missing or uncertain "
    "prerequisites force candidate=false; list them explicitly.")
MANDATORY = re.compile(r"\b(?:must|shall|required|obligated)\b|"
                       r"\b(?:должен|должна|обязан|обязана|необходимо)\b",
                       re.IGNORECASE)


def eligible(case: dict) -> bool:
    events = parse_events(case["response"], "response")
    return any(e.kind == "text" and e.role == "assistant" and REFUSAL.search(e.text)
               for e in events)


def prompt_for(case: dict) -> str:
    events = parse_events(case["prompt"], "prompt")
    timeline = [{"event": i, "role": e.role, "kind": e.kind, "tool": e.name,
                 "text": e.text} for i, e in enumerate(events)]
    return json.dumps({"dialogue": timeline, "target": case["response"]},
                      ensure_ascii=False)


def validate(case: dict, answer: dict) -> tuple[str, list[str]]:
    issues = []
    if not isinstance(answer, dict) or answer.get("candidate") is not True:
        return "NO_PROPOSAL", []
    events = parse_events(case["prompt"], "prompt")
    response_events = parse_events(case["response"], "response")
    system_text = "\n".join(e.text for e in events if e.role == "system")
    policy_match = re.search(r"<policy>(.*?)</policy>", system_text, re.DOTALL)
    policy_text = policy_match.group(1) if policy_match else system_text
    user_text = "\n".join(e.text for e in events if e.role == "user" and e.kind == "text")
    response_text = "\n".join(e.text for e in response_events
                              if e.role == "assistant" and e.kind == "text")
    catalog = parse_catalog(events, case["prompt"])
    if not catalog.complete:
        issues.append("catalog_incomplete")
    if answer.get("kind") not in {"false_refusal", "premature_transfer", "wrong_plan"}:
        issues.append("unknown_kind")
    for name, source in (("response_quote", response_text),
                         ("policy_quote", policy_text), ("user_quote", user_text)):
        quote = answer.get(name)
        if not isinstance(quote, str) or len(quote.strip()) < 8 or quote not in source:
            issues.append("invalid_" + name)
    if not REFUSAL.search(str(answer.get("response_quote", ""))):
        issues.append("target_quote_not_refusal_or_handoff")
    if answer.get("tool") not in catalog.tools:
        issues.append("tool_not_declared")
    missing = answer.get("missing_premises")
    if not isinstance(missing, list) or missing:
        issues.append("premise_missing_or_invalid")
    premises = answer.get("premises")
    if not isinstance(premises, list):
        issues.append("invalid_premises")
    else:
        if not any(isinstance(item, dict) and isinstance(item.get("event"), int)
                   and 0 <= item["event"] < len(events)
                   and events[item["event"]].kind == "result"
                   for item in premises):
            issues.append("no_observed_precondition")
        for premise in premises:
            if not isinstance(premise, dict):
                issues.append("invalid_premise")
                continue
            index, quote = premise.get("event"), premise.get("quote")
            if not isinstance(index, int) or index < 0 or index >= len(events) or \
                    events[index].kind not in {"result", "text"} or \
                    events[index].role not in {"user", "assistant", "unknown"} or \
                    not isinstance(quote, str) or len(quote.strip()) < 3 or \
                    quote not in events[index].text:
                issues.append("invalid_premise_source")
    ids = answer.get("entity_ids")
    user_ids = set(re.findall(r"\b[A-Z]{2,}-\d+\b", user_text))
    if not isinstance(ids, list) or any(
            not isinstance(item, str) or not exact_literal(user_text, item)
            for item in ids) or (user_ids and not ids):
        issues.append("entity_not_in_user_request")
    if isinstance(ids, list) and isinstance(premises, list):
        for premise in premises:
            if isinstance(premise, dict) and isinstance(premise.get("event"), int):
                index = premise["event"]
                if 0 <= index < len(events) and events[index].kind == "result" \
                        and ids and not any(exact_literal(events[index].text, item)
                                            for item in ids if isinstance(item, str)):
                    issues.append("unbound_result_entity")
                if 0 <= index < len(events) and events[index].kind == "result":
                    event = events[index]
                    if not event.json_valid or not isinstance(event.value, dict):
                        issues.append("invalid_result_json")
                        continue
                    anchors = entity_anchors(event.value)
                    if not anchors:
                        issues.append("unanchored_result")
                    for later in events[index + 1:]:
                        if later.kind == "result" and later.name == event.name and \
                                later.json_valid and isinstance(later.value, dict) and \
                                same_entity(anchors, entity_anchors(later.value)):
                            issues.append("superseded_result_premise")
                            break
    amount = answer.get("amount")
    user_amounts = {int(item) for item in re.findall(r"\$\s*(\d+)", user_text)}
    if amount is not None and (isinstance(amount, bool) or not isinstance(amount, int)):
        issues.append("invalid_amount")
    if user_amounts and (amount is None or amount not in user_amounts):
        issues.append("unbound_requested_amount")
    if isinstance(amount, int) and isinstance(premises, list):
        for premise in premises:
            if not isinstance(premise, dict) or not isinstance(premise.get("event"), int):
                continue
            index = premise["event"]
            if 0 <= index < len(events) and events[index].kind == "result" and \
                    re.search(r"authoriz|approv|соглас", events[index].name or "",
                              re.IGNORECASE):
                values = events[index].value if events[index].json_valid else None
                if not isinstance(values, dict) or values.get("amount") != amount:
                    issues.append("authorization_amount_mismatch")
    return ("CANDIDATE" if not issues else "UNKNOWN"), sorted(set(issues))


def validate_v2(case: dict, answer: dict) -> tuple[str, list[str]]:
    if not isinstance(answer, dict) or answer.get("candidate") is not True:
        return "NO_PROPOSAL", []
    events = parse_events(case["prompt"], "prompt")
    system_text = "\n".join(e.text for e in events if e.role == "system")
    policy_match = re.search(r"<policy>(.*?)</policy>", system_text, re.DOTALL)
    policy = policy_match.group(1) if policy_match else system_text
    quote = answer.get("policy_quote")
    span = unique_whitespace_span(policy, quote) if isinstance(quote, str) else None
    normalized = dict(answer)
    if span is not None:
        normalized["policy_quote"] = policy[span[0]:span[1]]
    verdict, issues = validate(case, normalized)
    if verdict != "CANDIDATE":
        return verdict, issues
    clause = normalized["policy_quote"]
    # A quote spanning multiple bullets can borrow "must" from an unrelated
    # requirement. It cannot certify that the cited action is mandatory.
    if "\n-" in clause:
        issues.append("multiple_policy_clauses")
    if not MANDATORY.search(clause):
        issues.append("policy_is_not_mandatory")
    if str(normalized.get("tool", "")) not in clause:
        issues.append("tool_not_in_mandatory_clause")
    return ("CANDIDATE" if not issues else "UNKNOWN"), sorted(set(issues))


def run(cases: list[dict], output: Path, *, version: int = 1) -> None:
    output.parent.mkdir(parents=True, exist_ok=True)
    done = {}
    if output.exists():
        for line in output.read_text(encoding="utf-8").splitlines():
            if line.strip():
                row = json.loads(line)
                if row.get("status") == "OK":
                    done[row["id"]] = row
    model = None
    with output.open("a", encoding="utf-8") as handle:
        for case in cases:
            cid = case["id"]
            digest = hashlib.sha256((case["prompt"] + "\0" + case["response"])
                                    .encode("utf-8")).hexdigest()
            if cid in done:
                if done[cid].get("input_sha256") != digest:
                    raise RuntimeError(f"feasibility input changed: {cid}")
                continue
            row = {"id": cid, "input_sha256": digest, "status": "OK",
                   "verdict": "INELIGIBLE", "issues": []}
            if eligible(case):
                if model is None:
                    model = Mistral()
                try:
                    answer = model.ask(SYSTEM_V2 if version == 2 else SYSTEM,
                                       prompt_for(case), max_tokens=900)
                    row["proposal"] = answer["value"]
                    row["usage"] = answer.get("usage", {})
                    row["finish_reason"] = answer.get("finish_reason")
                    if row["finish_reason"] != "stop":
                        row["verdict"], row["issues"] = "UNKNOWN", ["truncated_or_unfinished"]
                    else:
                        validator = validate_v2 if version == 2 else validate
                        row["verdict"], row["issues"] = validator(case, answer["value"])
                except Exception as error:
                    row.update(status="ERROR", verdict="UNKNOWN",
                               issues=[f"{type(error).__name__}: {str(error)[:200]}"])
            handle.write(json.dumps(row, ensure_ascii=False) + "\n")
            handle.flush()
            print(f"[feasibility] {cid}: {row['verdict']}", flush=True)
