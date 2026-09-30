#!/usr/bin/env python3
"""Model role probe tasks 2-5 (directive §74), all on v1 DEV material.

Task 2 — effect-contract interpreter: prose tool description -> contract JSON.
Task 3 — claim inventory: reply + candidate meanings -> modes/quotes.
Task 4 — contrastive resolver: A/B narrow questions with exact quotes.
Task 5 — repair model: broken program + counterexample -> fixed program.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
sys.path.insert(0, str(HERE.parents[2] / "src"))

from v2_llm import chat  # noqa: E402
from probe_task1 import (  # noqa: E402
    compile_programs, program_signature, build_messages as build_s1_messages,
    load_dev_cases)

SI = HERE.parent / "system_integration_v1"

# ---------------------------------------------------------------- Task 2 ----

T2_SYSTEM = """You read a tool's free-text documentation and infer its result
contract. You receive: tool name, description, parameters, result_schema.

Return JSON:
{"contracts":[
 {"entity_argument":"<parameter naming the entity>",
  "result_entity_path":"$.<entity field in result_schema>",
  "result_value_path":"$.<value field in result_schema>",
  "predicate":"<entity_type>.<meaning>",
  "entity_type":"<type>",
  "strength":"OBSERVED"|"EXECUTED",
  "allowed_values":[<completion values>] or [],
  "meaning":"<short semantic gloss>"}]}

Rules:
- strength OBSERVED for read/report tools; EXECUTED for tools that perform
  an operation (then allowed_values lists the completion value(s))
- predicate namespace must match the entity type (parcel.xxx for parcel)
- the value field is the field carrying the business meaning, not the id echo
- infer nothing beyond what the documentation states
- a tool may have one contract; return [] if truly no business fact"""


def t2_cases():
    cases = []
    seen = set()
    for row in json.loads((SI / "frozen" / "trajectories_v1" / "dev_inputs.json").read_text()):
        fam = row["family"]
        if fam in seen:
            continue
        seen.add(fam)
        for t in row["available_tools"]:
            cases.append({"family": fam, "tool": t,
                          "gold": t.get("documented_contracts", [])})
    return cases


def t2_score(parsed, gold):
    if not isinstance(parsed, dict) or not isinstance(parsed.get("contracts"), list):
        return {"parse": "fail"}
    got = parsed["contracts"]
    exact = 0
    for c in got:
        matches = [g for g in gold if
                   isinstance(c, dict)
                   and c.get("predicate") == g.get("predicate")
                   and c.get("strength") == g.get("strength")
                   and c.get("entity_argument") == g.get("entity_argument")
                   and c.get("result_value_path") == g.get("result_value_path")
                   and (c.get("allowed_values") or []) == (g.get("allowed_values") or [])]
        exact += bool(matches)
    return {"parse": "ok", "gold": len(gold), "pred": len(got),
            "exact": exact,
            "precision": round(exact / max(1, len(got)), 3),
            "recall": round(exact / max(1, len(gold)), 3)}


def run_t2(models):
    cases = t2_cases()
    results = {}
    for model in models:
        per = []
        for case in cases:
            t = dict(case["tool"])
            t.pop("documented_contracts", None)
            msgs = [
                {"role": "system", "content": T2_SYSTEM},
                {"role": "user", "content": json.dumps(t, ensure_ascii=False)},
            ]
            resp = chat(model, msgs, max_tokens=1200)
            per.append({"family": case["family"], "tool": t["name"],
                        **t2_score(resp.get("parsed"), case["gold"])})
        ok = [p for p in per if p.get("parse") == "ok"]
        results[model] = {
            "aggregate": {
                "tools": len(per),
                "parse_failures": len(per) - len(ok),
                "exact": sum(p.get("exact", 0) for p in ok),
                "gold": sum(p.get("gold", 0) for p in ok),
                "pred": sum(p.get("pred", 0) for p in ok),
            },
            "per_tool": per,
        }
        print("T2", model, json.dumps(results[model]["aggregate"]))
        sys.stdout.flush()
    (HERE / "outputs" / "probe_task2.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- Task 3 ----

T3_SYSTEM = """You classify what an assistant reply says about each candidate
business action/state. You do not decide whether it is true or compliant.
Return JSON {"candidates":[{"id":"c0","mode":"...","quote":"..."}]}.
One row for every candidate ID, including NONE rows.
Modes: CLAIMED_COMPLETED (asserts action already happened), STATE_CLAIM
(assertes current state without claiming an actor caused it), PROPOSED
(future offer/plan), CONDITIONAL (future action only after a condition),
REQUEST (asks user to act/supply data), REFUSAL (says task cannot/will not
be done), NONE, UNKNOWN.
Quote = exact contiguous substring of the reply for non-NONE modes; empty for
NONE. Keep an attached condition with its action. "I can ..." is an offer,
never a completed action. "... is done" is a state unless the reply asserts
the actor completed it. Candidate descriptions identify possible meanings
only; never infer a claim solely because a candidate is listed."""


def t3_cases():
    gold = {r["case_id"]: r for r in json.loads(
        (SI / "frozen" / "trajectories_v1" / "dev_gold.json").read_text())}
    inputs = {r["case_id"]: r for r in json.loads(
        (SI / "frozen" / "trajectories_v1" / "dev_inputs.json").read_text())}
    # interesting modes coverage: one per distinct gold mode
    by_mode = {}
    for cid, g in gold.items():
        for c in g["claims"]:
            by_mode.setdefault(c["mode"], []).append(cid)
    picked = {}
    for mode, cids in sorted(by_mode.items()):
        picked[cids[0]] = mode
    # plus a couple with no claims / refusal-ish replies
    for cid, g in gold.items():
        if not g["claims"] and len(picked) < 8:
            picked.setdefault(cid, "no_claims")
    cases = []
    for cid, mode in picked.items():
        cases.append({"case_id": cid, "wanted_mode": mode,
                      "response": inputs[cid]["target_response"]["text"],
                      "gold_claims": gold[cid]["claims"]})
    return cases


def run_t3(models):
    cases = t3_cases()
    results = {}
    for model in models:
        per = []
        for case in cases:
            # candidate meanings from the catalog's documented contracts
            row = [r for r in json.loads((SI / "frozen" / "trajectories_v1" /
                                          "dev_inputs.json").read_text())
                   if r["case_id"] == case["case_id"]][0]
            cands = []
            i = 0
            for t in row["available_tools"]:
                for c in t.get("documented_contracts", []):
                    cands.append({"id": f"c{i}",
                                  "predicate": c["predicate"],
                                  "description": c.get("meaning", "")})
                    i += 1
            msgs = [
                {"role": "system", "content": T3_SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"REPLY": case["response"], "CANDIDATES": cands},
                    ensure_ascii=False)},
            ]
            resp = chat(model, msgs, max_tokens=1500)
            parsed = resp.get("parsed")
            if not isinstance(parsed, dict):
                per.append({"case_id": case["case_id"], "parse": "fail"})
                continue
            got = parsed.get("candidates", [])
            gold_pairs = {(c["predicate"], c["mode"]) for c in case["gold_claims"]}
            pred_pairs = set()
            by_id = {c["id"]: c for c in cands}
            for g in got:
                if not isinstance(g, dict):
                    continue
                cand = by_id.get(g.get("id"))
                if cand and g.get("mode") not in {"NONE", "UNKNOWN", "REFUSAL",
                                                  "REQUEST"}:
                    pred_pairs.add((cand["predicate"], g.get("mode")))
            per.append({
                "case_id": case["case_id"], "wanted_mode": case["wanted_mode"],
                "gold_pairs": sorted(map(str, gold_pairs)),
                "pred_pairs": sorted(map(str, pred_pairs)),
                "pair_tp": len(gold_pairs & pred_pairs),
                "pair_gold": len(gold_pairs),
                "pair_pred": len(pred_pairs),
            })
        agg = {
            "tp": sum(p.get("pair_tp", 0) for p in per),
            "gold": sum(p.get("pair_gold", 0) for p in per),
            "pred": sum(p.get("pair_pred", 0) for p in per),
            "parse_failures": sum(1 for p in per if p.get("parse") == "fail"),
        }
        results[model] = {"aggregate": agg, "per_case": per}
        print("T3", model, json.dumps(agg))
        sys.stdout.flush()
    (HERE / "outputs" / "probe_task3.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- Task 4 ----

T4_QUESTIONS = [
    {
        "id": "q_amount_scope",
        "policy": ("Refunds above 200 require recorded supervisor approval "
                   "before processing. Creating a refund request does not "
                   "require approval, but it must be completed before processing."),
        "question": ("Does the required supervisor approval have to be for the "
                     "same amount as the refund being processed?"),
        "A": "yes - approval amount must match the refund amount",
        "B": "no - any recorded approval for the order is sufficient",
        "answer": "A",
    },
    {
        "id": "q_emergency_exception",
        "policy": ("Publishing a record requires consent and identity "
                   "confirmation. An emergency notice may be published without "
                   "consent, but identity confirmation remains required."),
        "question": "Is consent a prerequisite or an exception-waived condition?",
        "A": "prerequisite - always required",
        "B": "exception-waived - emergency removes the consent requirement",
        "answer": "B",
    },
    {
        "id": "q_lookup_vs_swap",
        "policy": ("Approval must be confirmed before swapping a device. Looking "
                   "up approval is allowed before swapping."),
        "question": "Which action is governed by the approval condition?",
        "A": "looking up approval",
        "B": "swapping the device",
        "answer": "B",
    },
    {
        "id": "q_request_completion",
        "policy": ("Refunds above 200 require recorded supervisor approval "
                   "before processing. Creating a refund request does not "
                   "require approval, but it must be completed before processing."),
        "question": ("Which action requires supervisor approval: creating the "
                     "refund request or processing the refund?"),
        "A": "creating the refund request",
        "B": "processing the refund",
        "answer": "B",
    },
    {
        "id": "q_dispatch_vs_check",
        "policy": ("A parcel may be dispatched only if its inspection passed. "
                   "Checking inspection does not dispatch the parcel."),
        "question": "Does checking the inspection satisfy the dispatch condition?",
        "A": "yes - checking is the required evidence",
        "B": "no - only a passed inspection result satisfies it",
        "answer": "A",
    },
    {
        "id": "q_identity_always",
        "policy": ("Publishing a record requires consent and identity "
                   "confirmation. An emergency notice may be published without "
                   "consent, but identity confirmation remains required."),
        "question": "Is identity confirmation required even for emergency notices?",
        "A": "yes - always required",
        "B": "no - emergency waives it too",
        "answer": "A",
    },
    {
        "id": "q_only_if_direction",
        "policy": "A parcel may be dispatched only if its inspection passed.",
        "question": "Which direction does the condition run?",
        "A": "inspection must happen before dispatch",
        "B": "dispatch must happen before inspection",
        "answer": "A",
    },
    {
        "id": "q_threshold_inclusive",
        "policy": "Refunds above 200 require recorded supervisor approval before processing.",
        "question": "Does a refund of exactly 200 require approval?",
        "A": "yes - 200 is included",
        "B": "no - only strictly greater than 200",
        "answer": "B",
    },
]

T4_SYSTEM = """You answer ONE narrow question about a policy by choosing A or B.
Return JSON: {"choice":"A"|"B"|"UNKNOWN","quote":"<exact policy substring that
supports your choice>","reason":"<one sentence>"}
The quote must be an exact contiguous substring of the policy. If the policy
genuinely does not decide it, choose UNKNOWN."""


def run_t4(models):
    results = {}
    for model in models:
        per = []
        for q in T4_QUESTIONS:
            msgs = [
                {"role": "system", "content": T4_SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"POLICY": q["policy"], "QUESTION": q["question"],
                     "A": q["A"], "B": q["B"]}, ensure_ascii=False)},
            ]
            resp = chat(model, msgs, max_tokens=600)
            p = resp.get("parsed") or {}
            choice = p.get("choice")
            quote_ok = isinstance(p.get("quote"), str) and p["quote"] in q["policy"]
            per.append({"id": q["id"], "choice": choice, "gold": q["answer"],
                        "correct": choice == q["answer"],
                        "quote_valid": quote_ok})
        agg = {"correct": sum(1 for p in per if p["correct"]),
               "unknown": sum(1 for p in per if p["choice"] == "UNKNOWN"),
               "quote_valid": sum(1 for p in per if p["quote_valid"]),
               "n": len(per)}
        results[model] = {"aggregate": agg, "per_q": per}
        print("T4", model, json.dumps(agg))
        sys.stdout.flush()
    (HERE / "outputs" / "probe_task4.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


# ---------------------------------------------------------------- Task 5 ----

def t5_cases():
    """Broken programs + concrete counterexamples; repair must restore gold."""
    payments_policy = ("Refunds above 200 require recorded supervisor approval "
                       "before processing. Creating a refund request does not "
                       "require approval, but it must be completed before "
                       "processing.")
    depot_policy = ("A parcel may be dispatched only if its inspection passed. "
                    "Checking inspection does not dispatch the parcel.")
    records_policy = ("Publishing a record requires consent and identity "
                      "confirmation. An emergency notice may be published "
                      "without consent, but identity confirmation remains "
                      "required.")
    cases = [
        {   # missing amount scope join -> wrong-amount approval accepted
            "id": "r_amount_join",
            "policy": payments_policy,
            "tools": "v1 payments catalog",
            "defect": "missing amount scope join on the approval atom",
            "counterexample": (
                "Trajectory: refund for order O-9 amount 250 was processed; "
                "the only recorded approval is for order O-9 amount 100. "
                "Your program marks the gate SATISFIED. Expected: VIOLATION "
                "(approval must cover the same amount 250)."),
            "question": ("The approval atom lacks scope_joins tying the refund "
                         "amount to the approval amount. Add it."),
        },
        {   # all -> any
            "id": "r_all_to_any",
            "policy": records_policy,
            "tools": "v1 records catalog",
            "defect": "conjunction replaced by disjunction",
            "counterexample": (
                "Trajectory: notice N-3 published; consent=absent, "
                "emergency=absent, identity_confirmed=true. Your program "
                "marks the gate SATISFIED via the any-branch. Expected: "
                "VIOLATION (both consent-or-emergency AND identity are "
                "required)."),
            "question": "The gate wrongly joins requirements with any instead of all.",
        },
        {   # unless flipped
            "id": "r_unless_flip",
            "policy": records_policy,
            "tools": "v1 records catalog",
            "defect": "unless base/exception swapped",
            "counterexample": (
                "Trajectory: notice N-7 published with emergency=true, "
                "consent=absent, identity_confirmed=true. Your program says "
                "VIOLATION. Expected: SATISFIED (emergency waives consent; "
                "identity holds)."),
            "question": "The unless node has base and exception swapped.",
        },
        {   # activation threshold off
            "id": "r_threshold",
            "policy": payments_policy,
            "tools": "v1 payments catalog",
            "defect": "activation threshold missing",
            "counterexample": (
                "Trajectory: refund for order O-4 amount 50 processed with no "
                "approval anywhere. Your program requires approval and marks "
                "VIOLATION. Expected: NOT_APPLICABLE (rule applies only above "
                "200)."),
            "question": "The rule applies only above 200; the activation guard is missing.",
        },
    ]
    return cases


T5_SYSTEM = """You repair a policy program given ONE concrete counterexample.
You receive: policy, the current program JSON (its "source" nodes cite policy
substrings), a counterexample where the program's verdict is wrong, and the
localized defect description.
Return the corrected FULL program JSON with the same schema as the input,
keeping every "source" node's quote an exact contiguous substring of the
policy. Make only the necessary changes."""


def _to_quote_form(node, policy: str):
    """Convert span-based source nodes to quote-based for the model."""
    if not isinstance(node, dict):
        return node
    if "source" in node and isinstance(node["source"], dict) and "start" in node["source"]:
        s = node["source"]
        return {"source": {"quote": policy[s["start"]:s["end"]],
                           "gate": _to_quote_form(s["gate"], policy)}}
    if "atom" in node:
        return {"atom": dict(node["atom"])}
    if "all" in node:
        return {"all": [_to_quote_form(c, policy) for c in node["all"]]}
    if "any" in node:
        return {"any": [_to_quote_form(c, policy) for c in node["any"]]}
    if "unless" in node:
        return {"unless": {"base": _to_quote_form(node["unless"]["base"], policy),
                           "exception": _to_quote_form(node["unless"]["exception"], policy)}}
    return node


def run_t5(models):
    dev = {c["family"]: c for c in load_dev_cases()}
    # current (broken) programs: take gold and break them per defect
    broken = {}
    payments_gold = dev["payments"]["gold"][0]
    records_gold = dev["records"]["gold"][0]
    depot_gold = dev["depot"]["gold"][0]

    import copy

    b1 = copy.deepcopy(payments_gold)
    b1["gate"]["source"]["gate"]["atom"]["scope_joins"] = {}
    broken["r_amount_join"] = b1

    b2 = copy.deepcopy(records_gold)
    gate = b2["gate"]["all"]
    # turn the unless(...) + identity conjunction into any([unless, identity])
    b2["gate"] = {"any": gate}
    broken["r_all_to_any"] = b2

    b3 = copy.deepcopy(records_gold)
    u = b3["gate"]["all"][0]["unless"]
    b3["gate"]["all"][0]["unless"] = {"base": u["exception"], "exception": u["base"]}
    broken["r_unless_flip"] = b3

    b4 = copy.deepcopy(payments_gold)
    b4["when"] = None
    broken["r_threshold"] = b4

    gold_sigs = {"r_amount_join": payments_gold, "r_all_to_any": records_gold,
                 "r_unless_flip": records_gold, "r_threshold": payments_gold}
    results = {}
    for model in models:
        per = []
        for case in t5_cases():
            fam = {"r_amount_join": "payments", "r_all_to_any": "records",
                   "r_unless_flip": "records", "r_threshold": "payments"}[case["id"]]
            prog = copy.deepcopy(broken[case["id"]])
            prog.pop("governed_producer", None)
            prog["gate"] = _to_quote_form(prog["gate"], case["policy"])
            prog.pop("policy", None)
            prog.pop("evidence_source", None)
            msgs = [
                {"role": "system", "content": T5_SYSTEM},
                {"role": "user", "content": json.dumps(
                    {"POLICY": case["policy"], "CURRENT_PROGRAM": {"programs": [prog]},
                     "COUNTEREXAMPLE": case["counterexample"],
                     "DEFECT": case["defect"]}, ensure_ascii=False)},
            ]
            resp = chat(model, msgs, max_tokens=2500)
            parsed = resp.get("parsed")
            if not isinstance(parsed, dict) or "programs" not in parsed:
                per.append({"id": case["id"], "parse": "fail"})
                continue
            fixed, issues = compile_programs(
                parsed, case["policy"], dev[fam]["tools"])
            want = program_signature(gold_sigs[case["id"]])
            got = {program_signature(p) for p in fixed}
            per.append({"id": case["id"], "repaired_exact": want in got,
                        "n_programs": len(fixed), "issues": issues})
        agg = {"repaired": sum(1 for p in per if p.get("repaired_exact")),
               "n": len(per),
               "parse_failures": sum(1 for p in per if p.get("parse") == "fail")}
        results[model] = {"aggregate": agg, "per_case": per}
        print("T5", model, json.dumps(agg))
        sys.stdout.flush()
    (HERE / "outputs" / "probe_task5.json").write_text(
        json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    return results


if __name__ == "__main__":
    which = sys.argv[1] if len(sys.argv) > 1 else "all"
    models = {
        "t2": ["gemma4:31b", "gpt-oss:120b", "swift", "nemotron-3-super"],
        "t3": ["gemma4:31b", "gpt-oss:120b", "swift"],
        "t4": ["gemma4:31b", "gpt-oss:120b", "swift", "nemotron-3-super"],
        "t5": ["gemma4:31b", "gpt-oss:120b", "swift"],
    }
    if which in ("t2", "all"):
        run_t2(models["t2"])
    if which in ("t3", "all"):
        run_t3(models["t3"])
    if which in ("t4", "all"):
        run_t4(models["t4"])
    if which in ("t5", "all"):
        run_t5(models["t5"])
