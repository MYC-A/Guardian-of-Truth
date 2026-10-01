#!/usr/bin/env python3
"""Corrected V2 trust-boundary layer — directive §5.3 (2026-10-01).

The frozen system_research_v2 code is PRESERVED as the historical baseline;
this module provides the corrected behavior for the new hybrid-service
harness. Each fix maps to a directive §5.3 item:

  1. licensed_entity_normalization — "conveyor 4 -> C4" / "started ->
     running" must not destroy a claim for lack of literal C4/running in
     the reply; support for normalization must carry an EXPLICIT source/
     rule; provenance is never weakened globally.
  2. apply_contrastive_v2 — quote_ok=false CLOSES the assumed semantic
     repair (re-strength / predicate rename are applied only when the
     contrastive quote is verbatim in the tool description); the flag is
     no longer decorative.
  3. acquire_documented_v2 — a model-proposed contract injected by
     enriched_case is stamped AUTO_VERIFIED (model-proposed), NEVER
     DOC_EXPLICIT; "merely reports status" descriptions keep read
     strength unless a quoted contrastive answer upgrades them.
  4. validate_goal_v2 — an empty candidate_calls list is NOT
     candidate_actions_exhaustive=true; "no candidates" != "proven that
     no capable actions exist". Exhaustiveness requires either a
     non-empty validated candidate list or an explicitly asserted
     complete catalog.
  5. compile_candidate_claims_licensed — claim compilation with licensed
     normalization: without rules the claim stays UNKNOWN (honest, not
     destroyed); with rules the normalization is recorded with its
     source on the query.

Item "syntax repair must run in the evaluated runtime" is a HARNESS
wiring requirement (S1-E repair loop currently absent from
system_eval.auto_programs — see HISTORY_AUDIT §21.7); it is addressed in
the hybrid-service harness, not patchable by a function here.
"""
from __future__ import annotations

import re
from dataclasses import replace

from guardian_truth.integration.automatic_claims import (
    CompiledClaims, _literal_entity, _literal_value)
from guardian_truth.integration.claim_binding import (
    literal_scope_arguments)
from guardian_truth.integration.contracts import (
    ContractAcquisition, acquire_documented)
from guardian_truth.step2.verifier import TrajectoryCase
from guardian_truth.step2.trusted import producer_scope


# ------------------------------------------------------------------ 1. rules

def licensed_entity_normalization(
        sentence: str,
        rules: tuple | list) -> tuple:
    """Apply EXPLICIT normalization rules to a claim sentence.

    rules: iterable of dicts {pattern, format, source} — the pattern is a
    regex; format uses \\1-style groups; source is the human-reviewable
    provenance of the rule (e.g. "quarry conveyor-id house style: C<n>").
    Returns (normalized_sentence, applied_rules) — the original sentence
    when nothing matches; every applied rule is recorded, nothing is
    normalized implicitly."""
    if not rules:
        return sentence, ()
    applied = []
    out = sentence
    for r in rules:
        m = re.search(r["pattern"], out, flags=re.IGNORECASE)
        if not m:
            continue
        out = out[:m.start()] + m.expand(r["format"]) + out[m.end():]
        applied.append({
            "pattern": r["pattern"], "format": r["format"],
            "source": r["source"],
            "matched": m.group(0),
        })
    return out, tuple(applied)


# ------------------------------------------- 2-3. contrastive + trust labels

def apply_contrastive_v2(tool: dict, valid: list,
                         answer_fn) -> list:
    """Re-strength/rename ONLY on a verbatim quote (quote_ok gate).

    answer_fn(tool, contract) -> dict with keys choice / quote / predicate
    (the parsed contrastive answer). When quote_ok is false the semantic
    repair is CLOSED: the contract keeps its draft strength/predicate and
    is flagged `semantic_repair_closed` for the audit."""
    if not valid:
        return valid
    out = []
    schema = tool.get("result_schema", {})
    for c in valid:
        ans = answer_fn(tool, c) or {}
        choice = ans.get("choice")
        pred = ans.get("predicate")
        quote_ok = (isinstance(ans.get("quote"), str)
                    and ans["quote"] in tool.get("description", ""))
        c2 = dict(c)
        if quote_ok:
            if choice == "A":
                c2["strength"] = "OBSERVED"
                c2["allowed_values"] = []
            elif choice == "B" and c.get("strength") in {"OBSERVED", None}:
                c2["strength"] = ("EXECUTED" if c.get("allowed_values")
                                  else "REQUESTED")
            if (isinstance(pred, str) and "." in pred
                    and pred.split(".", 1)[0] == c2.get("entity_type")
                    and c2.get("result_value_path")
                    and c2["result_value_path"][2:] in schema):
                c2["predicate"] = pred
        c2["contrastive"] = {"choice": choice, "quote_ok": quote_ok,
                             "semantic_repair_applied": bool(quote_ok)}
        if not quote_ok:
            c2["semantic_repair_closed"] = "quote_not_verbatim_in_description"
        out.append(c2)
    return out


def acquire_documented_v2(case: TrajectoryCase) -> ContractAcquisition:
    """Frozen validation logic, corrected trust labels: contracts injected
    by enriched_case (tool flag auto_contracts=True) are stamped
    AUTO_VERIFIED — a model proposal that survived programmatic
    validation — never DOC_EXPLICIT (the label reserved for
    application-supplied structured contracts)."""
    acquired = acquire_documented(case)
    auto_producers = {producer_scope(case, t["name"])
                      for t in case.tools
                      if isinstance(t, dict) and t.get("auto_contracts")
                      and isinstance(t.get("name"), str)}
    auto_producers.discard(None)
    if not auto_producers:
        return acquired
    bindings = []
    for b in acquired.bindings:
        if b.producer in auto_producers and b.evidence_source == "DOC_EXPLICIT":
            bindings.append(replace(b, evidence_source="AUTO_VERIFIED"))
        else:
            bindings.append(b)
    return ContractAcquisition(tuple(bindings), acquired.issues)


# ----------------------------------------------------- 4. goal exhaustiveness

def validate_goal_v2(parsed: dict, row: dict, *,
                     catalog_complete: bool = False) -> tuple:
    """validate_goal with the exhaustiveness fix: candidate_actions_
    exhaustive is True only when the validated candidate list is
    non-empty OR the caller explicitly asserts a complete catalog."""
    from guardian_truth.integration.proof_engine import _answer  # noqa: F401
    if not isinstance(parsed, dict):
        return None, ["goal_parse_failure"]
    g = parsed.get("goal")
    issues: list = []
    if not isinstance(g, dict):
        return None, ["goal_shape_invalid"]
    if g.get("quote") != row["user_request"]:
        issues.append("goal_quote_mismatch")
    if not isinstance(g.get("entity_id"), str) or not g["entity_id"]:
        issues.append("goal_entity_missing")
    elif g["entity_id"] not in row["user_request"]:
        issues.append("goal_entity_not_in_request")
    cand = parsed.get("candidate_calls")
    if not isinstance(cand, list):
        cand = []
        issues.append("candidates_invalid")
    tools_by_name = {t["name"]: t for t in row["available_tools"]}
    valid_calls = []
    for c in cand:
        if not isinstance(c, dict):
            continue
        t = tools_by_name.get(c.get("tool"))
        if not t or not isinstance(c.get("arguments"), dict):
            continue
        params = t.get("parameters", {})
        if set(c["arguments"]) != set(params):
            continue
        if any(str(v) not in row["user_request"]
               for v in c["arguments"].values()):
            continue
        valid_calls.append({"tool": c["tool"], "arguments": c["arguments"]})
    refusal = parsed.get("refusal")
    refusal_ok = (isinstance(refusal, dict)
                  and refusal.get("quote") == row["target_response"]["text"]
                  and isinstance(refusal.get("absolute_inability"), bool))
    if not refusal_ok:
        issues.append("refusal_invalid")
    exhaustive = bool(valid_calls) or bool(catalog_complete)
    if not exhaustive:
        issues.append("candidate_actions_exhaustiveness_unproven")
    goal = {
        "goal": {"quote": g.get("quote"), "entity_type": g.get("entity_type"),
                 "entity_id": g.get("entity_id"), "predicate": g.get("predicate"),
                 "value": g.get("value"),
                 "candidate_actions_exhaustive": exhaustive,
                 "candidate_calls": valid_calls,
                 "evidence_source": "AUTO_VERIFIED"},
        "refusal": ({"quote": refusal.get("quote"),
                     "absolute_inability": refusal.get("absolute_inability"),
                     "evidence_source": "AUTO_VERIFIED"} if refusal_ok else None),
    }
    return goal, issues


# --------------------------------------- 5. licensed claim compilation glue

def claim_entity_value_licensed(case: TrajectoryCase, predicate: str,
                                sentence: str,
                                rules: tuple | list) -> tuple:
    """Entity/value binding with licensed normalization.

    Returns (entity, value, scope, applied_rules). Without rules this is
    exactly the frozen literal behavior (UNKNOWN-safe abstention); with
    rules the normalization is explicit and recorded."""
    normalized, applied = licensed_entity_normalization(sentence, rules)
    entity = _literal_entity(case, predicate, normalized)
    value = _literal_value(case, predicate, normalized)
    scope = (literal_scope_arguments(case, predicate, entity, normalized)
             if entity is not None else None)
    return entity, value, scope, applied
