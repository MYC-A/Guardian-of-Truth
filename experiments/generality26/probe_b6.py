#!/usr/bin/env python3
"""Stage B probe B6 (hypothesis H3): feasibility as planning / reachability.

The directive (§11): "does another permitted/required route still exist after a
refusal" may be a PLANNING problem, not an LLM-question problem:

    current observed state + available actions + policy constraints
            -> exists a valid next action?

This probe formalizes the service-desk domain as a typed fact space with
actions derived from the TOOL CATALOG (arg-shape + result-shape, both
rename-robust) and mandate conditions detected from the POLICY TEXT with the
same COND_PATTERNS the TQ layer uses. Two semantics are compared:

  mandate-only      : refusal is a violation only if every mandate condition
                      is already satisfied in the observed state (the
                      feasibility_witness v2 behavior model);
  reachability      : refusal is a violation also when missing conditions are
                      ACHIEVABLE via available tools (verify -> authorize ->
                      confirm are all one call away); justified only when a
                      condition is observably FALSE (stock out) or unreachable.

Test set: the 16 frozen precondition-ablation variants (unlabelled stress
cases), the 4 authored false-refusal/handoff cases (orig+renamed), the
stock-out OK cases, and eligibility over the full 32-case suites.
Reference: feasibility_witness v2 outputs (16x 0-CANDIDATE, 2 authored TPs).
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))
GOT_ROOT = __import__("os").environ.get("GOT_ROOT", "/mnt/data/guardian/agent-workspace/Guardian-of-Truth")
sys.path.insert(0, GOT_ROOT + "/experiments/searh_23")

from common import extract_facts, parse_catalog, effect_type  # noqa: E402
from probe_b3 import amount_of  # noqa: E402


def join_ok(a: dict, b: dict) -> bool:
    shared = {k for k in a if k.endswith("id")} & {k for k in b if k.endswith("id")}
    return bool(shared) and all(str(a[k]) == str(b[k]) for k in shared)
import tq_questions_v2 as tqv2  # noqa: E402

GOT = Path(__import__("os").environ.get("GOT_ROOT", "/mnt/data/guardian/agent-workspace/Guardian-of-Truth"))
SD = GOT / "experiments/searh_23"
REFUSAL = re.compile(r"не могу|невозможно|нельзя|нет способа|недоступн|передаю|переда[юём]|"
                     r"специалист|can't|cannot|impossible|not possible|transfer|escalat", re.I)
MANDATE_PAT = re.compile(r"(must handle|required to handle|must .{0,40}rather than|"
                         r"must not .{0,40}falsely)", re.I)


def mandate_quote(policy: str) -> str:
    """The mandate clause: 'when C are satisfied, must handle with TOOL'."""
    for sent in re.split(r"(?<=[.!?])\s+", policy):
        if MANDATE_PAT.search(sent):
            return sent
    return ""


def mandate_conditions(quote: str, policy: str) -> dict[str, bool]:
    """Code-detected typed conditions for the mandate.

    The mandate clause compresses conditions established elsewhere in the
    policy ("the identity, confirmation, and any required authorization are
    satisfied"), so the condition set is the UNION over all policy clauses
    (COND_PATTERNS) plus generic normative concept nouns (identity /
    confirmation / authorization / stock are cross-domain policy concepts).
    """
    conds = set()
    for sent in re.split(r"(?<=[.!?])\s+", policy):
        for t, pat in tqv2.COND_PATTERNS.items():
            if pat.search(sent):
                conds.add(t)
    low = policy.lower()
    if "identity" in low or "идентичн" in low or "личност" in low:
        conds.add("IDENTITY_VERIFIED")
    if "confirmation" in low or "подтвержд" in low:
        conds.add("USER_CONFIRMATION")
    if "authorization" in low or "авторизац" in low:
        conds.add("AUTHORIZATION_EXACT")
    if "stock" in low or "inventory" in low or "склад" in low or "наличи" in low:
        conds.add("STOCK_AVAILABLE")
    return {t: t in conds for t in ("IDENTITY_VERIFIED", "USER_CONFIRMATION",
                                    "AUTHORIZATION_EXACT", "STOCK_AVAILABLE")}


def observed_state(f3: dict, call_target: dict) -> dict:
    """Which mandate conditions are satisfied/contradicted in the observed facts."""
    st = {}
    ver = [v for v in f3["verifications"] if v["positive"]]
    st["IDENTITY_VERIFIED"] = ("TRUE" if any(join_ok(call_target, v["call_kv"]) for v in ver)
                               else ("FALSE" if ver else "UNKNOWN"))
    st["USER_CONFIRMATION"] = "TRUE" if f3["user_confirmed"] else "FALSE"
    auth = [a for a in f3["authorizations"] if a["positive"]]
    ca = amount_of(call_target)
    if auth:
        ok = any(join_ok(call_target, a["call_kv"])
                 and (ca is None or str(a.get("amount")) == str(ca)) for a in auth)
        st["AUTHORIZATION_EXACT"] = "TRUE" if ok else "FALSE"
    else:
        st["AUTHORIZATION_EXACT"] = "UNKNOWN"
    dev = str(call_target.get("device_id"))
    if dev and dev in f3["stock"]:
        st["STOCK_AVAILABLE"] = "TRUE" if f3["stock"][dev]["available"] else "FALSE"
    else:
        st["STOCK_AVAILABLE"] = "UNKNOWN"
    return st


def achievable(ctype: str, state_val: str, catalog: dict, f3: dict) -> tuple[bool, str]:
    """Can the agent still establish this condition with available tools/asks?

    A condition is achievable when some declared tool's ARG SHAPE can produce
    it (id + non-id string args -> verification; id + amount -> authorization;
    device key -> inventory read) or it is user-providable (confirmation).
    A condition observed FALSE with no producing tool (stock) is unreachable.
    """
    def args_of(t):
        return catalog[t].get("args") or {}
    if ctype == "IDENTITY_VERIFIED":
        has = any(any(k.endswith("id") for k in args_of(t))
                  and any(not k.endswith("id") and args_of(t)[k].get("type") == "string"
                          for k in args_of(t))
                  for t in catalog)
        return (True, "verification-shaped tool declared (id + string args)") if has \
            else (False, "no verification-shaped tool in catalog")
    if ctype == "AUTHORIZATION_EXACT":
        has = any(any(k.endswith("id") for k in args_of(t)) and "amount" in args_of(t)
                  for t in catalog)
        return (True, "authorization-shaped tool declared (id + amount args)") if has \
            else (False, "no authorization-shaped tool in catalog")
    if ctype == "USER_CONFIRMATION":
        if f3.get("user_declined"):
            return False, "user actively declined confirmation; re-asking is not a route"
        return True, "confirmation is user-providable (ask the user)"
    if ctype == "STOCK_AVAILABLE":
        if state_val == "FALSE":
            # observed negative: only a tool PROVABLY producing the fact could
            # flip it; schemas cannot prove that -> conservative unreachable
            return (False, "observed negative; no declared tool provably re-establishes "
                           "it from the schema (stock-out is final)")
        has_read = any(any(k.endswith("id") and "dev" in k for k in args_of(t))
                       and effect_type(t, catalog) == "READ" for t in catalog)
        return (True, "inventory read tool declared") if has_read \
            else (False, "no inventory-shaped tool in catalog")
    return False, "untyped condition"


def is_refusal_response(case: dict, catalog: dict) -> tuple[bool, str]:
    resp = case.get("response", "")
    text = "\n".join(ln for ln in resp.splitlines()
                    if ln.strip() and not ln.strip().startswith(("→", "←", "⟦")))
    calls = re.findall(r"→ TOOL_CALL ([\w.-]+)", resp)
    if calls and all(effect_type(c, catalog) == "COMMUNICATE" for c in calls):
        return True, f"terminal communication call(s) {calls}"
    if calls:
        return False, f"non-communication calls {calls}"
    if REFUSAL.search(text):
        return True, "refusal/handoff text"
    return False, "no refusal markers"


def planner_verdict(case: dict) -> dict:
    catalog = parse_catalog(case["prompt"])
    policy_m = re.search(r"<policy>(.*?)</policy>", case["prompt"], re.DOTALL)
    policy = policy_m.group(1) if policy_m else ""
    mq = mandate_quote(policy)
    mconds = {t for t, present in mandate_conditions(mq, policy).items() if present}
    refusal, why = is_refusal_response(case, catalog)
    if not refusal:
        return {"eligible": False, "trigger": why, "mandate_conditions": sorted(mconds)}
    f3 = extract_facts(case, catalog)
    # the requested action: values merged from prior calls AND their results
    # (device/amount often live in result payloads, e.g. replacement_cost)
    target = {}
    for p in f3["reads"]:
        for src in (p["call_kv"], p["kv"]):
            for k, v in src.items():
                target.setdefault(k, v)
    state = observed_state(f3, target)
    detail = {t: state.get(t, "UNKNOWN") for t in mconds}
    unsat = [t for t in mconds if state.get(t, "UNKNOWN") != "TRUE"]
    false_conds = [t for t in mconds if state.get(t) == "FALSE"]
    unknown_conds = [t for t in mconds if state.get(t) == "UNKNOWN"]
    # mandate-only semantics
    if not unsat:
        mandate_verdict = "CANDIDATE_FALSE_REFUSAL"
    elif false_conds:
        mandate_verdict = "JUSTIFIED_MISSING"  # conditions observably false -> not due
    else:
        mandate_verdict = "NOT_DUE_MISSING"    # unknown -> mandate not triggered
    # reachability semantics
    reach = {}
    for t in unsat:
        ok, note = achievable(t, state.get(t, "UNKNOWN"), catalog, f3)
        reach[t] = {"achievable": ok, "note": note}
    if not unsat:
        reach_verdict = "CANDIDATE_FALSE_REFUSAL"
    elif all(r["achievable"] for r in reach.values()):
        reach_verdict = "CANDIDATE_PREMATURE_ABANDON"
    else:
        reach_verdict = "JUSTIFIED_UNREACHABLE"
    return {"eligible": True, "trigger": why, "mandate_quote": mq[:200],
            "mandate_conditions": sorted(mconds), "state": detail,
            "mandate_verdict": mandate_verdict, "reachability_verdict": reach_verdict,
            "reachability_detail": reach}


def main() -> int:
    suites = {
        "sd_orig": SD / "service_desk_v1/cases.csv",
        "sd_renamed": SD / "service_desk_v1_renamed/cases.csv",
        "ablation": SD / "service_desk_precondition_ablation/cases.csv",
    }
    results = {}
    for name, path in suites.items():
        import csv
        csv.field_size_limit(2 ** 30)
        cases = list(csv.DictReader(open(path, encoding="utf-8")))
        rows = []
        for case in cases:
            v = planner_verdict(case)
            v["id"] = case["id"]
            rows.append(v)
        results[name] = rows
        print(f"=== {name} ({len(cases)} cases) ===")
        for r in rows:
            if r["eligible"]:
                print(f"  {r['id'][:52]:52s} mandate={r['mandate_verdict']:26s} "
                      f"reach={r['reachability_verdict']}")
            else:
                print(f"  {r['id'][:52]:52s} INELIGIBLE ({r['trigger']})")
    # summary vs feasibility_v2 reference
    abl = results["ablation"]
    results["_summary"] = {
        "ablation_n": len(abl),
        "ablation_mandate_candidates": sum(1 for r in abl if r["eligible"] and "CANDIDATE" in r["mandate_verdict"]),
        "ablation_reach_candidates": sum(1 for r in abl if r["eligible"] and "CANDIDATE" in r["reachability_verdict"]),
        "ablation_justified_mandate": sum(1 for r in abl if r["eligible"] and r["mandate_verdict"].startswith("JUSTIFIED")),
        "ablation_justified_reach": sum(1 for r in abl if r["eligible"] and r["reachability_verdict"].startswith("JUSTIFIED")),
        "feasibility_v2_reference": "0 CANDIDATE on all 16 ablation variants (frozen 2026-09-24)",
        "base_false_refusal_expectation": "orig+renamed text_bad_refusal/handoff should be CANDIDATE under both semantics",
    }
    out = HERE / "results_b6_planning.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results["_summary"], indent=1))
    print(f"[written] {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
