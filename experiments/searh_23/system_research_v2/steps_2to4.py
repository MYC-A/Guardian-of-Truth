#!/usr/bin/env python3
"""Steps 2-4 automatic acquisition + system-level integration (V2).

Step2: prose contract acquisition (compositional per-tool questions),
programmatic validation, AUTO_VERIFIED bindings -> WorldFacts.
Step3: automatic claim inventory through the existing literal-grounded
compiler, measured against gold claims + verdict impact.
Step4: goal/action discovery + refusal interpretation, validated
programmatically, AUTO_VERIFIED reachability.
System: full-auto analyze (multi-Phi consensus variants) + oracle
decomposition factorial.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))
sys.path.insert(0, str(HERE.parent / "system_integration_v1"))

from v2_llm import chat  # noqa: E402
from step1_arms import (  # noqa: E402
    load_split, families_of, run_s1a, run_s1f, gold_programs_for,
    PRIMARY, SECONDARY, behavioural_signature)

# ------------------------------------------------------------------ Step2 ---

S2_SYSTEM = """You read ONE tool's documentation and infer its result
contract. You receive: tool name, free-text description, parameters, and
result_schema (field names with "scalar" meaning a typed value).

Return JSON:
{"contracts":[
 {"entity_argument":"<parameter naming the entity the fact is about>",
  "result_entity_path":"$.<entity echo field in result_schema>",
  "result_value_path":"$.<value field in result_schema>",
  "predicate":"<entity_type>.<meaning>",
  "entity_type":"<type>",
  "strength":"OBSERVED"|"EXECUTED"|"REQUESTED",
  "allowed_values":[<completion values>] or [],
  "meaning":"<short gloss>"}]}

Rules:
- strength OBSERVED when the tool reports/reads a state; EXECUTED when it
  performs an operation (allowed_values then lists the completion value(s));
  REQUESTED when it only submits a request
- the value field carries the business meaning (not the id echo)
- predicate namespace must equal entity_type
- one contract per business meaning the documentation states; [] if none"""


def acquire_auto_contracts(tools: list[dict], model="swift"):
    """Model-proposed contracts for tools lacking documented_contracts."""
    out = {}
    for t in tools:
        if t.get("documented_contracts"):
            continue  # catalog-supplied: never re-derived
        view = {k: t.get(k) for k in ("name", "description", "parameters",
                                      "result_schema")}
        r = chat(model, [
            {"role": "system", "content": S2_SYSTEM},
            {"role": "user", "content": json.dumps(view, ensure_ascii=False)},
        ], max_tokens=1200)
        out[t["name"]] = r.get("parsed") or {}
    return out


S2_CONTRAST_SYSTEM = """You resolve ONE contract question by choosing A or B.
You receive a tool's documentation and its current draft contract.
Return JSON: {"choice":"A"|"B"|"UNKNOWN",
  "quote":"<exact documentation substring supporting the choice>",
  "predicate":"<business-meaning predicate namespace.type>",
  "reason":"<one sentence>"}

A: the tool REPORTS or READS a state — its result contract is OBSERVED with
   empty allowed_values (calling it does not change business state)
B: the tool PERFORMS an operation — its contract is EXECUTED (or REQUESTED
   if it only submits) with the completion value(s) in allowed_values

Also rewrite the predicate so its name carries the BUSINESS MEANING
(e.g. sample.release_state, not sample.state), keeping the namespace equal
to the entity type. The quote must be an exact contiguous substring of the
documentation."""


def contract_contrastive(tool: dict, draft: dict, model="swift"):
    """Targeted contrast question for read-vs-write strength (§40)."""
    view = {k: tool.get(k) for k in ("name", "description", "parameters",
                                     "result_schema")}
    r = chat(model, [
        {"role": "system", "content": S2_CONTRAST_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"DOCUMENTATION": view, "DRAFT_CONTRACT": draft},
            ensure_ascii=False)},
    ], max_tokens=600)
    return r.get("parsed") or {}


def apply_contrastive(tool: dict, valid: list[dict], model="swift") -> list[dict]:
    """Re-strength/rename contracts by the contrastive answer (validated)."""
    if not valid:
        return valid
    out = []
    schema = tool.get("result_schema", {})
    for c in valid:
        ans = contract_contrastive(tool, c, model)
        choice = ans.get("choice")
        pred = ans.get("predicate")
        quote_ok = (isinstance(ans.get("quote"), str)
                    and ans["quote"] in tool.get("description", ""))
        c2 = dict(c)
        if choice == "A":
            c2["strength"] = "OBSERVED"
            c2["allowed_values"] = []
        elif choice == "B" and c.get("strength") in {"OBSERVED", None}:
            # keep declared values if any, else the draft's
            c2["strength"] = "EXECUTED" if c.get("allowed_values") else "REQUESTED"
        if (isinstance(pred, str) and "." in pred
                and pred.split(".", 1)[0] == c2.get("entity_type")
                and c2["result_value_path"] and c2["result_value_path"][2:] in schema):
            c2["predicate"] = pred
        c2["contrastive"] = {"choice": choice, "quote_ok": quote_ok}
        out.append(c2)
    return out


def validate_auto_contracts(tool: dict, contracts) -> list[dict]:
    """Programmatic validation of model contracts (trust gate)."""
    params = tool.get("parameters", {})
    schema = tool.get("result_schema", {})
    ok = []
    if not isinstance(contracts, list):
        return ok
    for c in contracts:
        if not isinstance(c, dict):
            continue
        ent = c.get("entity_argument")
        if not isinstance(ent, str) or ent not in params:
            continue
        path = c.get("result_value_path", "")
        if not path.startswith("$.") or path[2:] not in schema:
            continue
        pred = c.get("predicate", "")
        et = c.get("entity_type", "")
        if not pred or "." not in pred:
            continue
        if not et:
            # same convention as acquire_documented: derive from namespace
            et = pred.split(".", 1)[0]
        if not pred.startswith(et + "."):
            continue
        strength = c.get("strength")
        if strength not in {"OBSERVED", "EXECUTED", "REQUESTED"}:
            continue
        values = c.get("allowed_values", [])
        if not isinstance(values, list):
            continue
        if strength in {"EXECUTED", "REQUESTED"} and not values:
            continue
        ok.append({
            "entity_argument": ent,
            "result_entity_path": f"$.{ent}",
            "result_value_path": path,
            "predicate": pred, "entity_type": et, "strength": strength,
            "allowed_values": values, "meaning": c.get("meaning", ""),
        })
    return [c for c in ok if ent_ok(c, schema)]


def ent_ok(c, schema):
    ent = c["entity_argument"]
    return ent in schema


def enriched_case(row: dict, auto_contracts: dict, contrastive_model=None) -> dict:
    """Copy the row's tools with validated AUTO contracts injected."""
    tools = []
    for t in row["available_tools"]:
        t2 = dict(t)
        if not t2.get("documented_contracts") and t2["name"] in auto_contracts:
            valid = validate_auto_contracts(t, auto_contracts[t2["name"]].get("contracts", []))
            if valid and contrastive_model:
                valid = apply_contrastive(t, valid, contrastive_model)
            if valid:
                t2["documented_contracts"] = valid
                t2["auto_contracts"] = True
        tools.append(t2)
    row2 = dict(row)
    row2["available_tools"] = tools
    return row2


def step2_eval(split: str, model="swift"):
    """Measure acquired-contract fact recovery on prose-only families."""
    from v2_suite_builder import as_case, LAB_ORACLE_CONTRACTS
    from guardian_truth.integration.contracts import facts_from_documented
    inputs, gold = load_split(split)
    report = {"per_case": [], "model": model}
    tp = fp = fn = 0
    for row in inputs:
        needs_auto = any(not t.get("documented_contracts")
                         for t in row["available_tools"])
        if not needs_auto:
            continue
        auto = acquire_auto_contracts(row["available_tools"], model)
        row2 = enriched_case(row, auto, contrastive_model=model)
        case = as_case(row2)
        facts, _, issues = facts_from_documented(case)
        gold_facts = {json.dumps({k: f[k] for k in
                                  ("predicate", "entity", "value", "strength",
                                   "authority", "json_path", "source_call_id",
                                   "source_result_index")}, sort_keys=True,
                                 default=str)
                      for f in gold[row["case_id"]]["world_facts"]}
        got = set()
        for v in facts:
            f = v.fact.as_dict()
            got.add(json.dumps({
                "predicate": f["predicate"], "entity": json.loads(f["entity_id"]),
                "value": json.loads(f["value"]), "strength": f["strength"],
                "authority": f["authority"],
                "json_path": f["provenance"]["json_path"],
                "source_call_id": f["provenance"]["call_id"],
                "source_result_index": f["provenance"]["result_index"]},
                sort_keys=True, default=str))
        ctp, cfp, cfn = len(got & gold_facts), len(got - gold_facts), len(gold_facts - got)
        tp += ctp; fp += cfp; fn += cfn
        report["per_case"].append({
            "case_id": row["case_id"], "tp": ctp, "fp": cfp, "fn": cfn,
            "acquired_tools": [t["name"] for t in row2["available_tools"]
                               if t.get("auto_contracts")]})
    report["aggregate"] = {
        "tp": tp, "fp": fp, "fn": fn,
        "precision": round(tp / max(1, tp + fp), 3),
        "recall": round(tp / max(1, tp + fn), 3),
    }
    print("step2", split, model, json.dumps(report["aggregate"]))
    for c in report["per_case"]:
        print("  ", c["case_id"], c["tp"], c["fp"], c["fn"], c["acquired_tools"])
    (HERE / "outputs" / f"step2_{split}.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=1, default=str),
        encoding="utf-8")
    return report


# ------------------------------------------------------------------ Step3 ---

def step3_raw(row: dict, model=PRIMARY) -> str | None:
    """Model claim-inventory proposal (candidate-centred, frozen prompt)."""
    from guardian_truth.integration.candidate_claims import SYSTEM_PROMPT
    from v2_suite_builder import as_case
    case = as_case(row)
    from guardian_truth.integration.candidate_claims import candidate_meanings
    cands = [c.as_dict() for c in candidate_meanings(case)]
    if not cands:
        return None
    r = chat(model, [
        {"role": "system", "content": SYSTEM_PROMPT},
        {"role": "user", "content": json.dumps(
            {"REPLY": row["target_response"]["text"], "CANDIDATES": cands},
            ensure_ascii=False)},
    ], max_tokens=1500)
    raw = r.get("content")
    if raw is None:
        return None
    # client-side normalization only: the frozen compiler expects bare JSON
    txt = raw.strip()
    if txt.startswith("```"):
        nl = txt.find("\n")
        if nl != -1:
            txt = txt[nl + 1:]
        if txt.rstrip().endswith("```"):
            txt = txt.rstrip()[:-3].rstrip()
    try:
        json.loads(txt)
        return txt
    except Exception:
        return txt  # let the validator report it honestly


def step3_eval(split: str, model=PRIMARY, use_auto_contracts=None):
    """Automatic claims through the literal-grounded compiler."""
    from v2_suite_builder import as_case
    from guardian_truth.integration.automatic_claims import compile_candidate_claims
    from guardian_truth.integration.proof_engine import check_claim
    from guardian_truth.integration.contracts import facts_from_documented
    inputs, gold = load_split(split)
    per_case = []
    tp = fp = fn = 0
    for row in inputs:
        if gold[row["case_id"]].get("reachability") is not None and \
           not row["history"]:
            continue  # refusal-only cases have no claim inventory path
        row2 = row
        if use_auto_contracts is not None:
            row2 = enriched_case(row, use_auto_contracts(row))
        raw = step3_raw(row2, model)
        if raw is None:
            per_case.append({"case_id": row["case_id"], "skipped": "no candidates"})
            continue
        case = as_case(row2)
        facts, _, _ = facts_from_documented(case)
        compiled = compile_candidate_claims(
            row["target_response"]["text"], row["target_response"]["index"],
            case, raw)
        gold_pairs = {(c["predicate"], c["mode"]) for c in gold[row["case_id"]]["claims"]}
        pred_pairs = {(q.predicate, q.mode) for q in compiled.queries}
        ctp = len(gold_pairs & pred_pairs)
        cfp = len(pred_pairs - gold_pairs)
        cfn = len(gold_pairs - pred_pairs)
        tp += ctp; fp += cfp; fn += cfn
        per_case.append({
            "case_id": row["case_id"], "tp": ctp, "fp": cfp, "fn": cfn,
            "inventory_complete": compiled.inventory_complete,
            "issues": list(compiled.issues)[:6],
            "gold_pairs": sorted(str(p) for p in gold_pairs),
            "pred_pairs": sorted(str(p) for p in pred_pairs),
        })
    agg = {"tp": tp, "fp": fp, "fn": fn,
           "precision": round(tp / max(1, tp + fp), 3),
           "recall": round(tp / max(1, tp + fn), 3)}
    print("step3", split, model, json.dumps(agg))
    for c in per_case:
        if "skipped" not in c:
            print("  ", c["case_id"], c["tp"], c["fp"], c["fn"],
                  "complete" if c["inventory_complete"] else "incomplete")
    (HERE / "outputs" / f"step3_{split}.json").write_text(
        json.dumps({"aggregate": agg, "per_case": per_case},
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return {"aggregate": agg, "per_case": per_case}


# ------------------------------------------------------------------ Step4 ---

S4_GOAL_SYSTEM = """You convert a user request into a goal specification for
reachability checking. You receive: the user request, the assistant reply,
and the tool catalog with documented predicates.

Return JSON:
{"goal":{"quote":"<the full user request verbatim>",
         "predicate":"<catalog predicate the user wants established>",
         "entity_type":"<type>","entity_id":"<id mentioned in the request>",
         "value":"<required value>"},
 "candidate_calls":[{"tool":"<catalog tool>","arguments":{<exact params>}}],
 "refusal":{"quote":"<the full reply verbatim>","absolute_inability":true|false}}

Rules:
- candidate_calls: every catalog tool+argument combination that could
  DIRECTLY establish the goal (effect tools whose documented predicate and
  allowed value match the goal); read tools are not candidates
- arguments values must appear verbatim in the user request
- refusal.absolute_inability=true only if the reply states the task cannot
  be done at all; use the full reply text as quote"""


def step4_goal(row: dict, model=PRIMARY):
    from probe_task1 import catalog_view
    r = chat(model, [
        {"role": "system", "content": S4_GOAL_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"USER_REQUEST": row["user_request"],
             "REPLY": row["target_response"]["text"],
             "TOOL_CATALOG": catalog_view(row["available_tools"])},
            ensure_ascii=False)},
    ], max_tokens=1500)
    return r.get("parsed")


def validate_goal(parsed, row: dict):
    """Programmatic validation of the model goal (trust gate)."""
    if not isinstance(parsed, dict):
        return None, ["goal_parse_failure"]
    g = parsed.get("goal")
    issues = []
    if not isinstance(g, dict):
        return None, ["goal_shape_invalid"]
    if g.get("quote") != row["user_request"]:
        issues.append("goal_quote_mismatch")
    if not isinstance(g.get("entity_id"), str) or not g["entity_id"]:
        issues.append("goal_entity_missing")
    elif g["entity_id"] not in row["user_request"]:
        issues.append("goal_entity_not_in_request")
    # effect binding must exist for candidate calls
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
        if any(str(v) not in row["user_request"] for v in c["arguments"].values()):
            continue
        valid_calls.append({"tool": c["tool"], "arguments": c["arguments"]})
    refusal = parsed.get("refusal")
    refusal_ok = (isinstance(refusal, dict)
                  and refusal.get("quote") == row["target_response"]["text"]
                  and isinstance(refusal.get("absolute_inability"), bool))
    if not refusal_ok:
        issues.append("refusal_invalid")
    return {
        "goal": {"quote": g.get("quote"), "entity_type": g.get("entity_type"),
                 "entity_id": g.get("entity_id"), "predicate": g.get("predicate"),
                 "value": g.get("value"),
                 "candidate_actions_exhaustive": True,
                 "candidate_calls": valid_calls,
                 "evidence_source": "AUTO_VERIFIED"},
        "refusal": ({"quote": refusal.get("quote"),
                     "absolute_inability": refusal.get("absolute_inability"),
                     "evidence_source": "AUTO_VERIFIED"} if refusal_ok else None),
    }, issues


def step4_eval(split: str, model=PRIMARY):
    inputs, gold = load_split(split)
    per_case = []
    for row in inputs:
        if "reviewed_goal" not in row:
            continue
        parsed = step4_goal(row, model)
        validated, issues = validate_goal(parsed, row)
        # run reachability with the AUTO goal
        from v2_suite_builder import as_case
        from guardian_truth.integration.reachability import (
            ReviewedGoal, assess_local_reachability, decide_refusal)
        from guardian_truth.integration.proof_engine import ReviewedProgram
        from guardian_truth.integration.contracts import facts_from_documented
        from guardian_truth.step2.trusted import producer_scope
        case = as_case(row)
        fam = [f for f in families_of(inputs) if f["family"] == row["family"]][0]
        gp = gold_programs_for(fam, split)
        programs = []
        catalog_names = {t.get("name") for t in case.tools}
        for p in gp:
            if p["governed_tool"] not in catalog_names:
                continue
            d = {k: p[k] for k in ("policy", "governed_tool",
                                   "governed_description", "entity_argument",
                                   "gate", "when")}
            d["governed_producer"] = producer_scope(case, p["governed_tool"])
            d["evidence_source"] = "HUMAN_REVIEWED"
            d["complete_for_governed_action"] = True
            programs.append(ReviewedProgram(**d))
        facts, _, _ = facts_from_documented(case)
        try:
            goal = ReviewedGoal(**validated["goal"])
            reach = assess_local_reachability(
                row["user_request"], row["target_response"]["text"],
                row["target_response"]["index"], goal, programs, case,
                tuple(facts), catalog_complete=True)
            reach_status = reach["status"]
        except Exception as e:
            reach_status = f"error:{type(e).__name__}"
            issues.append(f"goal_rejected:{e}")
        gold_reach = gold[row["case_id"]].get("reachability")
        per_case.append({
            "case_id": row["case_id"], "issues": issues,
            "reach_pred": reach_status, "reach_gold": gold_reach,
            "match": reach_status == gold_reach,
            "n_candidate_calls": len(validated["goal"]["candidate_calls"]) if validated else 0,
        })
        print("  ", row["case_id"], "reach", reach_status, "gold", gold_reach,
              "issues", issues[:3])
    ok = sum(1 for c in per_case if c["match"])
    print("step4", split, f"{ok}/{len(per_case)} reachability exact")
    (HERE / "outputs" / f"step4_{split}.json").write_text(
        json.dumps({"per_case": per_case, "exact": f"{ok}/{len(per_case)}"},
                   ensure_ascii=False, indent=1, default=str), encoding="utf-8")
    return per_case


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    split = sys.argv[2] if len(sys.argv) > 2 else "dev"
    if which in ("step2", "all"):
        step2_eval(split)
    if which in ("step3", "all"):
        step3_eval(split)
    if which in ("step4", "all"):
        step4_eval(split)
