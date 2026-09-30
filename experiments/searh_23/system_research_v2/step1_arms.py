#!/usr/bin/env python3
"""Step 1 arms over frozen trajectories_v2 (directive §36).

Arms (frozen before sealed inference):
  S1-A one-shot            primary extractor (gemma4:31b)
  S1-B compositional       clause inventory -> local gates -> composition
  S1-C action-inventory    governed tools first -> per-action program
  S1-D bidirectional       S1-C + program<->source coverage audit
  S1-E CEGIS-like          S1-A + mutation falsifier + localized repair
  S1-F multi-Phi           Phi1 (gemma4:31b) and Phi2 (gpt-oss:120b) separate

Scoring (directive §37): governed action P/R, program exact (normalized
signature), atom F1, source quote validity, BEHAVIOURAL equivalence via the
frozen proof runtime (action-proof status agreement + isolated final verdict
with gold claims/facts), Phi size.
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
from probe_task1 import (  # noqa: E402
    SYSTEM as S1A_SYSTEM, build_messages as s1a_messages,
    compile_programs, program_signature, gate_signature, _normalize_atom)
from mutations import (  # noqa: E402
    m_entity_rename, m_temporal_flip, m_modality_flip, m_negation_flip,
    m_exception_flip, m_value_swap, m_entity_swap,
    check_invariance, check_flip, signature_diff_paths, apply_rename_to_signature)

FROZEN = HERE / "frozen" / "trajectories_v2"
PRIMARY = "gemma4:31b"
SECONDARY = "gpt-oss:120b"


def load_split(split: str):
    inputs = json.loads((FROZEN / f"{split}_inputs.json").read_text())
    gold = {r["case_id"]: r for r in json.loads(
        (FROZEN / f"{split}_gold.json").read_text())}
    return inputs, gold


def families_of(inputs):
    """Unique policy + tools per family (extraction is per-policy)."""
    fams = {}
    for row in inputs:
        if row["family"] in fams:
            continue
        fams[row["family"]] = {
            "family": row["family"],
            "policy": row["system_policy"],
            "tools": row["available_tools"],
            "cases": [r for r in inputs if r["family"] == row["family"]],
        }
    return list(fams.values())


# ------------------------------------------------------------------ S1-A ---

def run_s1a(fam, model=PRIMARY):
    resp = chat(model, s1a_messages(fam["policy"], fam["tools"]),
                max_tokens=4000)
    if not resp.get("parsed"):
        return [], ["parse_failure"], resp
    programs, issues = compile_programs(resp["parsed"], fam["policy"],
                                        fam["tools"])
    return programs, issues, resp


# ------------------------------------------------------------------ S1-B ---

S1B_STEP1_SYSTEM = """You list every normative clause of a policy. You receive
the RAW POLICY and a TOOL CATALOG. Return JSON:
{"clauses":[
 {"quote":"<exact contiguous policy substring>",
  "clause_type":"governed_action|condition|exception|actor_rule|"
                "second_rule|clarification|non_rule",
  "governed_tool":"<catalog tool this clause governs, or null>",
  "notes":"<one short sentence>"}]}
Rules:
- a clause is one sentence or one coherent sentence part
- governed_action: names an operation that requires/forbids conditions
- condition: states a requirement for a governed action
- exception: waives a requirement under a condition
- actor_rule / second_rule / clarification: self-explanatory
- non_rule: sentences with no normative content
- every quote must be an exact contiguous substring; clauses may overlap"""

S1B_STEP2_SYSTEM = """You build the policy program for ONE governed action.
You receive: the policy, the clauses relevant to this action, and the tool
catalog entry for the governed tool. Return JSON exactly like the one-shot
policy program schema:
{"programs":[
 {"governed_tool":"...", "entity_argument":"...", "activation":null,
  "gate":<gate>, "complete":true, "governing_quote":"..."}]}
The gate uses ONLY the given clauses; copy quotes character-by-character.
<gate> ::= {"all":[g,...]} | {"any":[g,...]}
         | {"unless":{"base":g,"exception":g}}
         | {"source":{"quote":"...","gate":g}}
         | {"atom":{"predicate":"<catalog predicate>","entity_type":"...",
                    "value":<required scalar>,"allowed_strengths":["OBSERVED"],
                    "scope_joins":{}}}"""


def run_s1b(fam, model=PRIMARY):
    from probe_task1 import catalog_view
    msgs1 = [
        {"role": "system", "content": S1B_STEP1_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"RAW POLICY": fam["policy"],
             "TOOL CATALOG": catalog_view(fam["tools"])}, ensure_ascii=False)},
    ]
    r1 = chat(model, msgs1, max_tokens=3000)
    if not r1.get("parsed"):
        return [], ["clause_parse_failure"], r1
    clauses = r1["parsed"].get("clauses", [])
    valid_clauses = [c for c in clauses
                     if isinstance(c, dict) and isinstance(c.get("quote"), str)
                     and c["quote"] in fam["policy"]]
    issues = [f"clause_invalid:{i}" for i, c in enumerate(clauses)
              if c not in valid_clauses]
    # group clauses by governed tool
    by_tool: dict[str, list] = {}
    for c in valid_clauses:
        tool = c.get("governed_tool")
        if tool and any(t["name"] == tool for t in fam["tools"]):
            by_tool.setdefault(tool, []).append(c)
        elif c.get("clause_type") in {"non_rule", "clarification"}:
            continue
        else:
            by_tool.setdefault("", []).append(c)
    programs = []
    tools_by_name = {t["name"]: t for t in fam["tools"]}
    for tool, cls in by_tool.items():
        if not tool or tool not in tools_by_name:
            continue
        msgs2 = [
            {"role": "system", "content": S1B_STEP2_SYSTEM},
            {"role": "user", "content": json.dumps(
                {"POLICY": fam["policy"],
                 "CLAUSES_FOR_THIS_ACTION": cls,
                 "TOOL": tools_by_name[tool]}, ensure_ascii=False)},
        ]
        r2 = chat(model, msgs2, max_tokens=2500)
        if not r2.get("parsed"):
            issues.append(f"{tool}:local_parse_failure")
            continue
        progs, pissues = compile_programs(r2["parsed"], fam["policy"],
                                          fam["tools"])
        issues += [f"{tool}:{x}" for x in pissues]
        programs.extend(p for p in progs if p["governed_tool"] == tool)
    return programs, issues, {"clauses": valid_clauses}


# ------------------------------------------------------------------ S1-C ---

S1C_STEP1_SYSTEM = """You decide which catalog tools are governed by policy
rules. You receive the RAW POLICY and the TOOL CATALOG. Return JSON:
{"governed_tools":[{"tool":"<name>","reason":"<one sentence>",
                    "governing_quote":"<exact policy substring>"}],
 "ungoverned_tools":["<name>",...]}
A tool is governed ONLY if the policy states a rule about performing or
using it. Every catalog tool must appear in exactly one of the two lists."""

S1C_STEP2_SYSTEM = S1B_STEP2_SYSTEM


def run_s1c(fam, model=PRIMARY):
    from probe_task1 import catalog_view
    msgs1 = [
        {"role": "system", "content": S1C_STEP1_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"RAW POLICY": fam["policy"],
             "TOOL CATALOG": catalog_view(fam["tools"])}, ensure_ascii=False)},
    ]
    r1 = chat(model, msgs1, max_tokens=1500)
    if not r1.get("parsed"):
        return [], ["inventory_parse_failure"], r1
    inv = r1["parsed"]
    gov = [g.get("tool") for g in inv.get("governed_tools", [])
           if isinstance(g, dict) and isinstance(g.get("tool"), str)
           and any(t["name"] == g["tool"] for t in fam["tools"])]
    programs = []
    issues = []
    tools_by_name = {t["name"]: t for t in fam["tools"]}
    clauses = inv.get("governed_tools", [])
    for tool in gov:
        relevant = [g for g in clauses if isinstance(g, dict) and g.get("tool") == tool]
        msgs2 = [
            {"role": "system", "content": S1C_STEP2_SYSTEM},
            {"role": "user", "content": json.dumps(
                {"POLICY": fam["policy"],
                 "CLAUSES_FOR_THIS_ACTION": relevant,
                 "TOOL": tools_by_name[tool]}, ensure_ascii=False)},
        ]
        r2 = chat(model, msgs2, max_tokens=2500)
        if not r2.get("parsed"):
            issues.append(f"{tool}:local_parse_failure")
            continue
        progs, pissues = compile_programs(r2["parsed"], fam["policy"],
                                          fam["tools"])
        issues += [f"{tool}:{x}" for x in pissues]
        programs.extend(p for p in progs if p["governed_tool"] == tool)
    return programs, issues, {"inventory": inv}


# ------------------------------------------------------------------ S1-D ---

S1D_COVER_SYSTEM = """You audit bidirectional source coverage between a
policy and its extracted program. You receive the policy, the clauses, and
the program. Return JSON:
{"program_elements":[
   {"element":"<short id like atom-0>","quote":"<exact policy substring licensing it>",
    "licensing_clause":"<clause quote or null>"}],
 "uncovered_clauses":[{"quote":"...","why":"<one sentence>"}],
 "coverage_complete":true|false}
A clause is covered when some program element (gate atom, activation, or the
program's governing rule) is licensed by it. Reading tool mentions and
non-rule sentences need no element. Every quote must be an exact contiguous
substring of the policy."""


def run_s1d(fam, model=PRIMARY):
    programs, issues, aux = run_s1c(fam, model)
    if not programs:
        return programs, issues + ["no_programs_for_coverage"], aux
    # quote-form program for the model
    from probe_tasks_2to5 import _to_quote_form
    progs_q = []
    for p in programs:
        q = dict(p)
        q["gate"] = _to_quote_form(p["gate"], fam["policy"])
        progs_q.append(q)
    msgs = [
        {"role": "system", "content": S1D_COVER_SYSTEM},
        {"role": "user", "content": json.dumps(
            {"POLICY": fam["policy"], "PROGRAM": {"programs": progs_q}},
            ensure_ascii=False)},
    ]
    r = chat(model, msgs, max_tokens=2500)
    cover = r.get("parsed") or {}
    issues = list(issues)
    if not cover:
        issues.append("coverage_parse_failure")
    else:
        if cover.get("coverage_complete") is False:
            for c in cover.get("uncovered_clauses", []):
                if isinstance(c, dict) and isinstance(c.get("quote"), str):
                    issues.append("uncovered_clause:" + c["quote"][:60])
    return programs, issues, {"s1c": aux, "coverage": cover}


# ------------------------------------------------------------------ S1-E ---

# twin mutation parameters per family (data, not falsifier logic)
TWIN_PARAMS = {
    "bakery": {"rename": [("order", "consignment")],
               "negation": "accepted",
               "value": None, "temporal": True, "modality": False,
               "exception": False},
    "ferry": {"rename": [("passenger", "traveller")],
              "negation": "valid ticket", "value": None,
              "temporal": True, "modality": False, "exception": False},
    "museum": {"rename": [("visitor", "guest")],
               "negation": "member card", "value": None,
               "temporal": False, "modality": False, "exception": False},
    "orchard": {"rename": [("grove", "plantation")],
                "negation": "pests", "value": None,
                "temporal": False, "modality": False, "exception": True},
    "lab": {"rename": [("sample", "specimen")],
            "negation": "priority status", "value": None,
            "temporal": False, "modality": False, "exception": True},
    "cinema": {"rename": [("ticket", "voucher")],
               "negation": "confirmed", "value": ("15", "25"),
               "temporal": False, "modality": False, "exception": False},
    "quarry": {"rename": [("conveyor", "belt")],
               "negation": "released", "value": None,
               "temporal": False, "modality": False, "exception": False},
    "apiary": {"rename": [("hive", "colony")],
               "negation": "certified", "value": None,
               "temporal": False, "modality": False, "exception": False},
    "transit": {"rename": [("ticket", "booking")],
                "negation": "paid", "value": None,
                "temporal": False, "modality": False, "exception": False},
    "archive": {"rename": [("record", "file")],
                "negation": "declassified", "value": None,
                "temporal": False, "modality": False, "exception": True},
}

REPAIR_SYSTEM = """You repair a policy program given concrete
counterexamples from validation and mutation tests. You receive: the policy,
the current program (or raw failed draft), and a list of counterexamples.
Each names a violated invariant and the localized difference. Return the
corrected FULL program JSON ({"programs":[...]}) with source nodes quoting
exact contiguous policy substrings. Change ONLY what the counterexamples
demand.

The frozen gate algebra supports EXACTLY these nodes:
 {"all":[<gate>,...]} | {"any":[<gate>,...]}
 {"unless":{"base":<gate>,"exception":<gate>}}
 {"source":{"quote":"<exact policy substring>","gate":<gate>}}
 {"atom":{"predicate":"<catalog predicate>","entity_type":"...",
   "value":<required scalar>,"allowed_strengths":["OBSERVED"|"EXECUTED"],
   "scope_joins":{"<target param>":"<source param>"}}}
"activation" lives ONLY at the program level:
 {"field":"<param>","op":"GT","value":<number>,"quote":"..."}
Any other operator (not, implies, activation-as-gate, none_of, ...) must be
re-expressed with the five operators above."""


def falsify(fam, programs, model=PRIMARY):
    """Deterministic falsifier: rename invariance + flip sensitivity.
    Returns list of counterexamples (concrete, localized)."""
    policy = fam["policy"]
    params = TWIN_PARAMS.get(fam["family"], {})
    ces = []
    base_sigs = [program_signature(p) for p in programs]
    # 1) rename invariance: the catalog is UNCHANGED, so every catalog-anchored
    # token (predicate, entity_type, entity_argument) must stay fixed; the
    # program signature must be IDENTICAL under a policy-noun rename.
    renames = params.get("rename") or []
    if renames:
        mutated = policy
        for old, new in renames:
            mutated = mutated.replace(old, new)
        if mutated != policy:
            resp = chat(model, s1a_messages(mutated, fam["tools"]),
                        max_tokens=4000)
            if resp.get("parsed"):
                mprogs, _ = compile_programs(resp["parsed"], mutated,
                                             fam["tools"])
                for j, p in enumerate(programs):
                    match = [mp for mp in mprogs
                             if mp["governed_tool"] == p["governed_tool"]]
                    if not match:
                        ces.append({
                            "invariant": "rename_invariance",
                            "violation": f"program for {p['governed_tool']} "
                                         "disappeared after a semantic rename "
                                         "(catalog unchanged)",
                            "diff": ["program_missing"]})
                        continue
                    chk = check_invariance(base_sigs[j],
                                           program_signature(match[0]), {})
                    if not chk["passed"]:
                        diffs = signature_diff_paths(base_sigs[j],
                                                     program_signature(match[0]))
                        ces.append({**chk["counterexample"],
                                    "invariant": "rename_invariance",
                                    "diff": diffs[:6]})
    # 2) temporal flip sensitivity
    if params.get("temporal"):
        mutated, spec = m_temporal_flip(policy)
        if mutated != policy:
            resp = chat(model, s1a_messages(mutated, fam["tools"]),
                        max_tokens=4000)
            if resp.get("parsed"):
                mprogs, _ = compile_programs(resp["parsed"], mutated,
                                             fam["tools"])
                for p in programs:
                    match = [mp for mp in mprogs
                             if mp["governed_tool"] == p["governed_tool"]]
                    if match:
                        chk = check_flip(program_signature(p),
                                         program_signature(match[0]))
                        if not chk["passed"]:
                            ces.append({**chk["counterexample"],
                                        "invariant": "temporal_flip",
                                        "diff": ["insensitive:program_identical"]})
    # 3) modality flip
    if params.get("modality") and " must " in policy or " may " in policy:
        mutated, spec = m_modality_flip(policy)
        if mutated != policy:
            resp = chat(model, s1a_messages(mutated, fam["tools"]),
                        max_tokens=4000)
            if resp.get("parsed"):
                mprogs, _ = compile_programs(resp["parsed"], mutated,
                                             fam["tools"])
                for p in programs:
                    match = [mp for mp in mprogs
                             if mp["governed_tool"] == p["governed_tool"]]
                    if match:
                        chk = check_flip(program_signature(p),
                                         program_signature(match[0]))
                        if not chk["passed"]:
                            ces.append({**chk["counterexample"],
                                        "invariant": "modality_flip",
                                        "diff": ["insensitive:program_identical"]})
    # 4) negation flip (value polarity)
    neg = params.get("negation")
    if neg:
        mutated, spec = m_negation_flip(policy, neg)
        if mutated != policy:
            resp = chat(model, s1a_messages(mutated, fam["tools"]),
                        max_tokens=4000)
            if resp.get("parsed"):
                mprogs, _ = compile_programs(resp["parsed"], mutated,
                                             fam["tools"])
                for p in programs:
                    match = [mp for mp in mprogs
                             if mp["governed_tool"] == p["governed_tool"]]
                    if match:
                        chk = check_flip(program_signature(p),
                                         program_signature(match[0]))
                        if not chk["passed"]:
                            ces.append({**chk["counterexample"],
                                        "invariant": "negation_flip",
                                        "diff": ["insensitive:program_identical"]})
    return ces


def run_s1e(fam, model=PRIMARY, max_rounds=2):
    """S1-A + falsifier + localized repair loop (bounded).

    Counterexample sources (all concrete, §14): programmatic compile
    failures (unsupported operators / invalid shapes / bad quotes) and
    mutation-invariant violations (rename invariance, flip sensitivity).
    """
    programs, issues, resp = run_s1a(fam, model)
    trace = {"falsify_rounds": []}
    # compile failures from the first pass are themselves counterexamples
    compile_ces = []
    for issue in issues:
        if any(tag in issue for tag in ("operator_unsupported", "gate_invalid",
                                        "shape_invalid", "quote_not_substring",
                                        "top_shape_invalid", "child_invalid",
                                        "conjunction_empty", "activation_invalid",
                                        "parse_failure", "empty_active_quote")):
            compile_ces.append({
                "invariant": "schema_conformance",
                "violation": f"program does not conform to the frozen gate "
                             f"algebra: {issue}",
                "diff": [issue]})
    for round_no in range(max_rounds):
        ces = compile_ces + falsify(fam, programs, model)
        compile_ces = []  # only re-sent on the first round
        trace["falsify_rounds"].append(
            {"round": round_no, "counterexamples": len(ces)})
        if not ces:
            break
        from probe_tasks_2to5 import _to_quote_form
        progs_q = []
        for p in programs:
            q = dict(p)
            q["gate"] = _to_quote_form(p["gate"], fam["policy"])
            progs_q.append(q)
        payload = {"POLICY": fam["policy"],
                   "COUNTEREXAMPLES": ces}
        if progs_q:
            payload["CURRENT_PROGRAM"] = {"programs": progs_q}
        if compile_ces or not progs_q:
            payload["RAW_FAILED_DRAFT"] = (resp.get("parsed")
                                           if isinstance(resp, dict) else None)
        msgs = [
            {"role": "system", "content": REPAIR_SYSTEM},
            {"role": "user", "content": json.dumps(payload, ensure_ascii=False)},
        ]
        r = chat(model, msgs, max_tokens=4000)
        repair_model_used = model
        if not r.get("parsed") and model != SECONDARY:
            # cross-model repair (§75): the second provider re-does the edit
            r = chat(SECONDARY, msgs, max_tokens=4000)
            repair_model_used = SECONDARY
        if not r.get("parsed"):
            issues.append(f"repair_round{round_no}:parse_failure")
            break
        fixed, fissues = compile_programs(r["parsed"], fam["policy"],
                                          fam["tools"])
        trace.setdefault("repair_models", []).append(repair_model_used)
        issues += [f"repair_round{round_no}:{x}" for x in fissues]
        if fixed:
            programs = fixed
    return programs, issues, trace


# ------------------------------------------------------------------ eval ---

def behavioural_eval(fam, programs, gold_programs, split_gold, case_rows):
    """Compile predicted programs (AUTO_VERIFIED) and compare action-proof
    statuses + isolated final verdict with gold claims/facts."""
    from v2_suite_builder import as_case, oracle_claim, gold_programs as _gp
    from guardian_truth.integration.contracts import facts_from_documented
    from guardian_truth.integration.proof_engine import (
        ReviewedProgram, check_call, check_claim, decide_reviewed)
    from guardian_truth.step2.trusted import producer_scope

    out = {"cases": []}
    for row in case_rows:
        case = as_case(row)
        catalog_names = {t.get("name") for t in case.tools}
        gp = []
        for p in gold_programs:
            if p["governed_tool"] not in catalog_names:
                continue
            d = dict(p)
            d["governed_producer"] = producer_scope(case, p["governed_tool"])
            gp.append(ReviewedProgram(**d))
        # predicted programs -> ReviewedProgram with AUTO_VERIFIED
        pp = []
        for p in programs:
            d = dict(p)
            d["governed_producer"] = producer_scope(case, p["governed_tool"])
            try:
                pp.append(ReviewedProgram(
                    policy=fam["policy"], governed_tool=d["governed_tool"],
                    governed_description=d["governed_description"],
                    governed_producer=d["governed_producer"],
                    entity_argument=d["entity_argument"], gate=d["gate"],
                    when=d.get("when"), evidence_source="AUTO_VERIFIED",
                    complete_for_governed_action=d.get(
                        "complete_for_governed_action", False)))
            except Exception as e:  # noqa: BLE001
                out.setdefault("compile_errors", []).append(
                    f"{row['case_id']}:{type(e).__name__}")
        facts, _, _ = facts_from_documented(case)
        verified = tuple(facts)
        gold_row = split_gold[row["case_id"]]

        def statuses(progs):
            return tuple(
                (c.call_id, check_call(p, case, c, verified)["status"])
                for p in progs for c in case.calls
                if c.tool == p.governed_tool and c.index <
                row["target_response"]["index"])

        def verdict_of(progs):
            actions = tuple(check_call(p, case, c, verified)
                            for p in progs for c in case.calls
                            if c.tool == p.governed_tool and c.index <
                            row["target_response"]["index"])
            if not gold_row["claims"] and not progs:
                return "NO_CLAIMS"
            queries = []
            for label in gold_row["claims"]:
                try:
                    queries.append(oracle_claim(row, label, case))
                except Exception:
                    pass
            claims = tuple(check_claim(q, case, verified) for q in queries)
            if gold_row.get("reachability") is not None:
                return None  # refusal case handled separately
            v = decide_reviewed(actions, claims,
                                policy_complete=bool(progs) and all(
                                    p.complete_for_governed_action
                                    for p in progs),
                                claim_inventory_complete=True)
            return v["status"]

        gs = statuses(gp)
        ps = statuses(pp)
        out["cases"].append({
            "case_id": row["case_id"],
            "action_status_agreement": sum(
                1 for a, b in zip(gs, ps) if a[0] == b[0] and a[1] == b[1]),
            "action_status_total": max(len(gs), len(ps)),
            "gold_action_statuses": [s for _, s in gs],
            "pred_action_statuses": [s for _, s in ps],
        })
    return out


def score_arm(programs, gold_programs):
    pred_sigs = {program_signature(p) for p in programs}
    gold_sigs = {program_signature(p) for p in gold_programs}
    pred_tools = {p["governed_tool"] for p in programs}
    gold_tools = {p["governed_tool"] for p in gold_programs}

    def atoms(node):
        if "atom" in node:
            a = _normalize_atom(node["atom"], None) or node["atom"]
            return [a]
        if "source" in node:
            return atoms(node["source"]["gate"])
        if "all" in node or "any" in node:
            key = "all" if "all" in node else "any"
            return [x for c in node[key] for x in atoms(c)]
        if "unless" in node:
            return atoms(node["unless"]["base"]) + atoms(node["unless"]["exception"])
        return []

    def atom_set(progs):
        out = set()
        for p in progs:
            for a in atoms(p["gate"]):
                out.add((a.get("predicate"), json.dumps(a.get("value"),
                                                        sort_keys=True),
                         tuple(sorted(a.get("allowed_strengths", []))),
                         tuple(sorted((a.get("scope_joins") or {}).items()))))
        return out

    pa, ga = atom_set(programs), atom_set(gold_programs)
    return {
        "governed_tool_recall": len(pred_tools & gold_tools) / max(1, len(gold_tools)),
        "governed_tool_precision": len(pred_tools & gold_tools) / max(1, len(pred_tools)),
        "program_exact": len(pred_sigs & gold_sigs),
        "program_gold": len(gold_sigs),
        "program_pred": len(pred_sigs),
        "atom_tp": len(pa & ga), "atom_fp": len(pa - ga), "atom_fn": len(ga - pa),
        "n_programs": len(programs),
    }


# ------------------------------------------------------------------ main ---

GOLD_PROGRAMS = None


def gold_programs_for(fam, split):
    """Gold programs from the domain module (dev or sealed)."""
    global GOLD_PROGRAMS
    if GOLD_PROGRAMS is None:
        import v2_domains_dev as DEV
        import v2_domains_sealed as SEALED
        GOLD_PROGRAMS = {}
        for family in list(DEV.DEV_FAMILIES) + list(SEALED.SEALED_FAMILIES):
            GOLD_PROGRAMS[family["name"]] = family["programs"]()
    return [dict(p) for p in GOLD_PROGRAMS[fam["family"]]]


ARMS = ("s1a", "s1b", "s1c", "s1d", "s1e")


def main():
    split = sys.argv[1] if len(sys.argv) > 1 else "dev"
    arms = sys.argv[2].split(",") if len(sys.argv) > 2 else list(ARMS)
    inputs, gold = load_split(split)
    fams = families_of(inputs)
    results = {}
    for arm in arms:
        arm_results = []
        for fam in fams:
            gp = gold_programs_for(fam, split)
            if arm == "s1a":
                programs, issues, aux = run_s1a(fam)
            elif arm == "s1b":
                programs, issues, aux = run_s1b(fam)
            elif arm == "s1c":
                programs, issues, aux = run_s1c(fam)
            elif arm == "s1d":
                programs, issues, aux = run_s1d(fam)
            elif arm == "s1e":
                programs, issues, aux = run_s1e(fam)
            else:
                raise SystemExit(f"unknown arm {arm}")
            score = score_arm(programs, gp)
            behav = behavioural_eval(fam, programs, gp, gold, fam["cases"])
            bsig = behavioural_signature(fam, gp, programs)
            status_agree = sum(c["action_status_agreement"] for c in behav["cases"])
            status_total = sum(c["action_status_total"] for c in behav["cases"])
            arm_results.append({
                "family": fam["family"], "score": score, "issues": issues,
                "behavioural": behav,
                "status_agreement": f"{status_agree}/{status_total}",
                "behavioural_signature": bsig,
            })
            print(arm, fam["family"], json.dumps(score),
                  f"status_agree={status_agree}/{status_total}")
            sys.stdout.flush()
        agg = {
            "tool_recall": round(sum(r["score"]["governed_tool_recall"]
                                     for r in arm_results) / len(arm_results), 3),
            "tool_precision": round(sum(r["score"]["governed_tool_precision"]
                                        for r in arm_results) / len(arm_results), 3),
            "program_exact": sum(r["score"]["program_exact"] for r in arm_results),
            "program_gold": sum(r["score"]["program_gold"] for r in arm_results),
            "atom_tp": sum(r["score"]["atom_tp"] for r in arm_results),
            "atom_fp": sum(r["score"]["atom_fp"] for r in arm_results),
            "atom_fn": sum(r["score"]["atom_fn"] for r in arm_results),
        }
        p = agg["atom_tp"] / max(1, agg["atom_tp"] + agg["atom_fp"])
        r = agg["atom_tp"] / max(1, agg["atom_tp"] + agg["atom_fn"])
        agg["atom_precision"] = round(p, 3)
        agg["atom_recall"] = round(r, 3)
        agg["atom_f1"] = round(2 * p * r / max(1e-9, p + r), 3)
        agree = sum(int(a) for a in
                    (x["status_agreement"].split("/")[0] for x in arm_results))
        total = sum(int(a) for a in
                    (x["status_agreement"].split("/")[1] for x in arm_results))
        agg["action_status_agreement"] = f"{agree}/{total}"
        bs_agree = sum(x["behavioural_signature"].get("agree", 0)
                       for x in arm_results)
        bs_total = sum(x["behavioural_signature"].get("compared", 0)
                       for x in arm_results)
        agg["generated_state_agreement"] = round(
            bs_agree / max(1, bs_total), 3)
        agg["generated_state_compared"] = bs_total
        results[arm] = {"aggregate": agg, "per_family": arm_results}
        print(f"== {arm} {split} ==", json.dumps(agg))
        sys.stdout.flush()
    out = HERE / "outputs" / f"step1_{split}.json"
    out.write_text(json.dumps(results, ensure_ascii=False, indent=1,
                              default=str), encoding="utf-8")
    print("saved", out)




# ------------------------------------------------- behavioural signature ---

def _atoms_of(node):
    if "atom" in node:
        return [node["atom"]]
    if "source" in node:
        return _atoms_of(node["source"]["gate"])
    if "all" in node or "any" in node:
        key = "all" if "all" in node else "any"
        return [x for c in node[key] for x in _atoms_of(c)]
    if "unless" in node:
        return _atoms_of(node["unless"]["base"]) + _atoms_of(node["unless"]["exception"])
    return []


def behavioural_signature(fam, gold_programs, pred_programs, max_states=81):
    """Compare gold vs predicted programs on GENERATED states (§31-32).

    A state assigns each distinct (predicate, entity-relevant) atom of the
    union one of: required value, opposite value, or ABSENT (never read).
    We synthesize a read call per assigned atom, then a hypothetical
    governed call, and compare check_call statuses. Bounded by max_states
    (uniformly sampled deterministic subset).
    """
    from guardian_truth.step2.verifier import CallEvent, ResultEvent, TrajectoryCase
    from guardian_truth.integration.proof_engine import ReviewedProgram, check_call
    from guardian_truth.step2.trusted import producer_scope

    policy = fam["policy"]
    tools = fam["tools"]
    # tool that produces each predicate (documented contract)
    producer_of = {}
    value_field_of = {}
    entity_field_of = {}
    for t in tools:
        for c in t.get("documented_contracts", []):
            producer_of[c["predicate"]] = t["name"]
            value_field_of[c["predicate"]] = c["result_value_path"][2:]
            entity_field_of[c["predicate"]] = c["entity_argument"]
    # governed tool of the programs
    all_progs = [(p, "gold") for p in gold_programs] + \
                [(p, "pred") for p in pred_programs]
    atoms = set()
    for p, _ in all_progs:
        for a in _atoms_of(p["gate"]):
            atoms.add(a["predicate"])
    atoms = sorted(a for a in atoms if a in producer_of)  # only synthesizable
    if not atoms:
        return {"states": 0, "agree": 0, "note": "no synthesizable atoms"}
    # enumerate value assignments: for each atom: required-value, opposite, absent
    import itertools
    def value_options(pred):
        # find required value from any program's atom
        req = None
        for p, _ in all_progs:
            for a in _atoms_of(p["gate"]):
                if a["predicate"] == pred:
                    req = a.get("value")
        if isinstance(req, bool):
            return [req, not req, None]
        if isinstance(req, str):
            return [req, None]  # strings: present-with-required vs absent
        return [req, None]

    combos = list(itertools.product(*(value_options(a) for a in atoms)))
    if len(combos) > max_states:
        step = len(combos) / max_states
        combos = [combos[int(i * step)] for i in range(max_states)]
    entity = "E-1"
    agree = total = 0
    disagreements = []
    for combo in combos:
        # build synthetic case
        history = []
        idx = 0
        for pred, val in zip(atoms, combo):
            if val is None:
                continue
            tool = producer_of[pred]
            args = {entity_field_of[pred]: entity}
            payload = {entity_field_of[pred]: entity,
                       value_field_of[pred]: val}
            history.append({"index": idx, "role": "assistant", "call_id": f"x{idx}",
                            "tool": tool, "arguments": args})
            idx += 1
            history.append({"index": idx, "role": "tool", "call_id": f"x{idx-1}",
                            "tool": tool, "payload": payload})
            idx += 1
        row = {"case_id": "synthetic", "system_policy": policy,
               "available_tools": tools, "history": history,
               "target_response": {"index": idx, "text": "ok"}}
        from v2_suite_builder import as_case
        case = as_case(row)
        facts = None
        from guardian_truth.integration.contracts import facts_from_documented
        facts, _, _ = facts_from_documented(case)
        facts = tuple(facts)
        # compare each gold program against pred program with same tool+activation
        for g in gold_programs:
            for p in pred_programs:
                if g["governed_tool"] != p["governed_tool"]:
                    continue
                if (g.get("when") or None) != (p.get("when") or None):
                    continue
                try:
                    gd = {k: g[k] for k in
                          ("policy", "governed_tool", "governed_description",
                           "entity_argument", "gate", "when")}
                    gd["governed_producer"] = producer_scope(case, g["governed_tool"])
                    pd = {k: p[k] for k in
                          ("policy", "governed_tool", "governed_description",
                           "entity_argument", "gate", "when")}
                    pd["governed_producer"] = producer_scope(case, p["governed_tool"])
                    gd["evidence_source"] = "HUMAN_REVIEWED"
                    pd["evidence_source"] = "AUTO_VERIFIED"
                    gd["complete_for_governed_action"] = True
                    pd["complete_for_governed_action"] = bool(
                        p.get("complete_for_governed_action"))
                    gp = ReviewedProgram(**gd)
                    pp = ReviewedProgram(**pd)
                except Exception:
                    continue
                target = CallEvent(idx, "hyp", g["governed_tool"],
                                   {g["entity_argument"]: entity})
                try:
                    gs = check_call(gp, case, target, facts, hypothetical=True)["status"]
                    ps = check_call(pp, case, target, facts, hypothetical=True)["status"]
                except Exception:
                    continue
                total += 1
                if gs == ps:
                    agree += 1
                elif len(disagreements) < 12:
                    disagreements.append({"state": dict(zip(atoms, combo)),
                                          "gold": gs, "pred": ps})
    return {"states": len(combos), "compared": total, "agree": agree,
            "agreement_rate": round(agree / max(1, total), 3),
            "disagreements": disagreements}


if __name__ == "__main__":
    main()


def run_s1f(fam):
    """Multi-Phi: both extractors carried separately (§26-29)."""
    p1, i1, r1 = run_s1a(fam, PRIMARY)
    p2, i2, r2 = run_s1a(fam, SECONDARY)
    s1 = {program_signature(p) for p in p1}
    s2 = {program_signature(p) for p in p2}
    # behavioural equivalence between the two interpretations
    bsig = behavioural_signature(fam, p1, p2)
    return {
        "phi1": {"programs": p1, "issues": i1},
        "phi2": {"programs": p2, "issues": i2},
        "divergent": s1 != s2,
        "n_phi1": len(s1), "n_phi2": len(s2),
        "shared": len(s1 & s2),
        "inter_phi_behavioural": bsig,
    }


def main_s1f():
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument("split")
    args = ap.parse_args()
    inputs, gold = load_split(args.split)
    results = []
    for fam in families_of(inputs):
        gp = gold_programs_for(fam, args.split)
        out = run_s1f(fam)
        sc1 = score_arm(out["phi1"]["programs"], gp)
        sc2 = score_arm(out["phi2"]["programs"], gp)
        # union-of-tools view (no union of rules, §29)
        tools1 = {p["governed_tool"] for p in out["phi1"]["programs"]}
        tools2 = {p["governed_tool"] for p in out["phi2"]["programs"]}
        gold_tools = {p["governed_tool"] for p in gp}
        results.append({
            "family": fam["family"], "divergent": out["divergent"],
            "phi1_score": sc1, "phi2_score": sc2,
            "tool_recall_phi1": len(tools1 & gold_tools) / max(1, len(gold_tools)),
            "tool_recall_phi2": len(tools2 & gold_tools) / max(1, len(gold_tools)),
            "tool_recall_union": len((tools1 | tools2) & gold_tools) / max(1, len(gold_tools)),
            "inter_phi_behavioural": out["inter_phi_behavioural"],
        })
        print(args.split, fam["family"],
              f"divergent={out['divergent']} "
              f"r1={results[-1]['tool_recall_phi1']} "
              f"r2={results[-1]['tool_recall_phi2']} "
              f"union={results[-1]['tool_recall_union']} "
              f"interphi_behav={out['inter_phi_behavioural'].get('agreement_rate')}")
        sys.stdout.flush()
    agg = {
        "families": len(results),
        "divergent": sum(1 for r in results if r["divergent"]),
        "tool_recall_phi1": round(sum(r["tool_recall_phi1"] for r in results) / len(results), 3),
        "tool_recall_phi2": round(sum(r["tool_recall_phi2"] for r in results) / len(results), 3),
        "tool_recall_union": round(sum(r["tool_recall_union"] for r in results) / len(results), 3),
    }
    print("== s1f ==", json.dumps(agg))
    out = HERE / "outputs" / f"step1f_{args.split}.json"
    out.write_text(json.dumps({"aggregate": agg, "per_family": results},
                              ensure_ascii=False, indent=1, default=str),
                   encoding="utf-8")
    print("saved", out)
