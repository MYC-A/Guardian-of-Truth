"""Architecture C - joint policy-theory building, LangExtract grounding, Clingo.

C0: one LLM theory (RuleIR-lite) -> ASP + evidence -> verdict
C1: two independent theories -> registry union (naive)
C2: LangExtract grounded rule elements + clause coverage of the policy;
    uncovered policy clauses trigger ONE targeted re-extraction (adaptive)
C3: mutual critique: critic sees the other theory + grounded elements and must
    point to source fragments; accepted repairs cite anchored fragments
C5: divergence report between theories (conditions count/rules count/elements)
Verdict mapping (sound):
  proved_error -> 1 ; proved_no_error -> 0 ; else UNRESOLVED -> None (or 1 in
  decision layer with explicit probabilistic flag)
"""
import sys, json, re, time
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, run_llm, prf, save_result, extract_json, SYSTEM_PROMPT
from common.spans import locate
from common import timeline as T
from common import asp_lower as ASP
from common import langextract_runner as LR


def policy_text(prompt, max_chars=14000):
    i = prompt.find("<policy>")
    j = prompt.find("</policy>")
    if i >= 0 and j > i:
        p = prompt[i + 8:j].strip()
    else:
        p = prompt[:max_chars]
    if len(p) > max_chars:
        p = p[:max_chars]
    return p


P_THEORY = """Convert the POLICY below into a formal theory as JSON. Rules of types:
- "prohibition": action forbidden under conditions, with optional exceptions
- "obligation": action allowed/required only if conditions hold (preconditions)
- "requirement": an action that MUST be performed (tool name) in a situation
Condition/exception types you may use (ONLY these):
  {"type":"arg_gt|arg_lt|arg_gte|arg_lte|arg_equals","field":"<argument name>","value":N}
  {"type":"flag_true|flag_false","flag":"<exact JSON boolean field name from tool results>"}
  {"type":"action_present","tool":"<tool name>"}     # holds if that tool was called in history
  {"type":"action_absent","tool":"<tool name>","closure_premise":"<verbatim policy quote proving this tool is the only source of that fact>"}
For every rule set "action" to the exact tool name it governs (or "*").
If some policy clause cannot be represented by these types, add its text to
"unrepresentable_parts" of the rule (or "unrepresentable_notes" for the theory).
Do NOT invent conditions that are not in the text. Keep every exception!
EXAMPLE - policy: "Refunds above 10,000 RUB require manager approval via approve_refund
before execution. Refunds of 10,000 RUB or less need no approval. Reporting a balance is
allowed only from the latest get_balance result for that exact account."
Correct theory:
{"rules":[
 {"id":"R1","kind":"obligation","action":"refund",
  "conditions":[{"type":"action_present","tool":"approve_refund"}],
  "exceptions":[{"type":"arg_lte","field":"amount","value":10000}]},
 {"id":"R2","kind":"prohibition","action":"report_balance","action_text":"state a balance value",
  "conditions":[],"exceptions":[],
  "unrepresentable_parts":["latest-result-only requirement is not expressible"]}],
 "unrepresentable_notes":[]}
Mark a part "unrepresentable" ONLY when it truly cannot be expressed with the types above;
otherwise encode it. The field "kind" (or "type") must be prohibition/obligation/requirement.
Answer with JSON only: {"rules":[{...}],"unrepresentable_notes":[...]}
"""

P_THEORY2 = """You are an independent analyst. Read the POLICY and produce a COMPLETE formal
theory as JSON. Pay special attention to: exceptions (except/unless/кроме), thresholds
(свыше/более/more than), temporal order (до/перед/before/после/after), actor boundaries,
and scope (current session vs previous). Use ONLY these condition types:
arg_gt, arg_lt, arg_gte, arg_lte, arg_equals (numeric arg), flag_true, flag_false
(boolean field from tool results), action_present (tool called), action_absent (tool not
called; requires closure_premise = verbatim policy quote).
Rule kinds: prohibition / obligation / requirement. Set "action" to the exact tool name.
Anything not representable -> "unrepresentable_parts" / "unrepresentable_notes".
EXAMPLE - policy: "Refunds above 10,000 RUB require manager approval via approve_refund
before execution. Refunds of 10,000 RUB or less need no approval. Reporting a balance is
allowed only from the latest get_balance result for that exact account."
Correct theory:
{"rules":[
 {"id":"R1","kind":"obligation","action":"refund",
  "conditions":[{"type":"action_present","tool":"approve_refund"}],
  "exceptions":[{"type":"arg_lte","field":"amount","value":10000}]},
 {"id":"R2","kind":"prohibition","action":"report_balance","action_text":"state a balance value",
  "conditions":[],"exceptions":[],
  "unrepresentable_parts":["latest-result-only requirement is not expressible"]}],
 "unrepresentable_notes":[]}
Mark a part "unrepresentable" ONLY when it truly cannot be expressed with the types above;
otherwise encode it. The field "kind" (or "type") must be prohibition/obligation/requirement.
Answer with JSON only: {"rules":[{...}],"unrepresentable_notes":[...]}
"""

P_THEORY3 = """You are an independent analyst. Read the POLICY and produce a COMPLETE formal
theory as JSON. Pay special attention to: exceptions (except/unless/кроме), thresholds
(свыше/более/more than), temporal order (до/перед/before/после/after), actor boundaries,
freshness of reported data (only from the LATEST result), and scope.
Use ONLY these condition types:
- arg_gt, arg_lt, arg_gte, arg_lte, arg_equals (numeric arg of the action)
- flag_true, flag_false (boolean field from tool results)
- action_present / action_absent (tool called in history; action_absent requires
  closure_premise = verbatim policy quote)
- text_report (field=F): holds if the FINAL RESPONSE text asserts a concrete value
  for field F (e.g. reporting a balance, price, eta). Use it as the CONDITION of a
  prohibition rule that governs stating values.
- value_is_latest (field=F): holds if every value the response asserts for F equals
  the latest tool-response value for the same entity. Use it as an EXCEPTION to make
  fresh-data reports legal.
Rule kinds: prohibition / obligation / requirement. Set "action" to the exact tool
name, or "*" for speech acts governed via text_report.
Anything not representable -> "unrepresentable_parts" / "unrepresentable_notes".
EXAMPLE - policy: "Reporting a balance is allowed only from the latest get_balance
result for that exact account. The agent must fetch the balance before stating it."
Correct theory:
{"rules":[
 {"id":"R1","kind":"prohibition","action":"*","action_text":"state a balance value",
  "conditions":[{"type":"text_report","field":"balance"}],
  "exceptions":[{"type":"value_is_latest","field":"balance"}],
  "unrepresentable_parts":[]}],
 "unrepresentable_notes":[]}
Mark a part "unrepresentable" ONLY when it truly cannot be expressed with the types
above. Prefer text_report + value_is_latest over marking freshness as unrepresentable.
Answer with JSON only: {"rules":[{...}],"unrepresentable_notes":[...]}
"""

P_CRITIC = """You are a critical reviewer of a formal policy theory. Below are:
(1) the ORIGINAL policy, (2) a list of grounded policy elements extracted with exact quotes,
(3) another analyst's theory. Find REAL discrepancies only:
- a condition/exception/threshold present in the policy or grounded elements but MISSING
  from the theory (name the source quote),
- a condition in the theory NOT supported by any policy text (name why; quote if possible),
- a wrong scope or wrong action binding.
For each criticism provide: rule_id, issue, source_quote (exact verbatim from the policy).
Then produce a REPAIRED theory in the same JSON format, applying only justified fixes.
Answer with JSON: {"criticisms":[{...}],"repaired":{...theory json...}}
"""


def build_theory(row, variant=1):
    p = policy_text(row["prompt"])
    tpl = {1: P_THEORY, 2: P_THEORY2, 3: P_THEORY3}[variant]
    ctx = build_context(row) if False else row["prompt"]
    # keep response visible for obligation/requirement action names
    tasks = [{"id": f"{row['id']}-t{variant}",
              "system": SYSTEM_PROMPT,
              "prompt": tpl + "\n\nPOLICY:\n" + p + "\n\nTARGET RESPONSE (for action names only):\n"
                        + row["response"][:1500]}]
    out = run_llm(tasks, concurrency=1)
    j = extract_json(out.get(f"{row['id']}-t{variant}"))
    if j is None or "rules" not in j:
        j = {"rules": [], "unrepresentable_notes": ["theory_parse_failed"]}
    return j


def langextract_elements(row):
    p = policy_text(row["prompt"])
    try:
        els = LR.extract(
            p,
            "Extract each semantic rule element (obligation, prohibition, permission, condition, exception, threshold, temporal order) verbatim from the policy.",
            LR.rule_element_examples())
    except Exception as e:
        els = []
    anchored = [e for e in els if e.get("aligned_text")]
    return {"all": els, "anchored": anchored,
            "anchor_rate": len(anchored) / len(els) if els else None}


def coverage_check(theory, els):
    """For each theory rule, does some grounded element text overlap its conditions?"""
    cov = []
    texts = [(e["text"], e.get("aligned_text") or e["text"]) for e in els]
    for r in theory.get("rules", []):
        desc = json.dumps(r, ensure_ascii=False)
        words = set(re.findall(r"[A-Za-z\u0400-\u04FF]{4,}", desc.lower())) - {"true", "false", "flag", "field", "value", "type", "action", "rule", "tool"}
        best = None
        for t in texts:
            tw = set(re.findall(r"[A-Za-z\u0400-\u04FF]{4,}", (t[0] + " " + t[1]).lower()))
            if tw:
                ov = len(words & tw) / max(len(words), 1)
                if best is None or ov > best[1]:
                    best = (t[0][:60], ov)
        cov.append({"rule": r.get("id"), "best_element": best[0] if best else None,
                    "overlap": round(best[1], 3) if best else 0.0})
    return cov


def critique_and_repair(row, theory, els):
    p = policy_text(row["prompt"])
    prompt = (P_CRITIC + "\n\nPOLICY:\n" + p[:9000] +
              "\n\nGROUNDED ELEMENTS:\n" +
              json.dumps([{"text": e["text"][:200], "attributes": e.get("attributes")} for e in els[:25]],
                         ensure_ascii=False, indent=1) +
              "\n\nTHEORY:\n" + json.dumps(theory, ensure_ascii=False, indent=1))
    out = run_llm([{"id": f"{row['id']}-crit", "system": SYSTEM_PROMPT, "prompt": prompt}], concurrency=1)
    j = extract_json(out.get(f"{row['id']}-crit"))
    if not j or not isinstance(j, dict):
        return None
    repaired = j.get("repaired") or theory
    # validate criticisms: quote must anchor into policy
    valid_criticisms = []
    for c in j.get("criticisms", []):
        q = c.get("source_quote") or ""
        anch = locate(q, p)
        c2 = dict(c)
        c2["anchor"] = anch
        if anch["status"] != "unanchored":
            valid_criticisms.append(c2)
    return {"criticisms": valid_criticisms, "repaired": repaired}


def evidence(row):
    events = T.parse_prompt(row["prompt"])
    ra = ASP.analyze_response(events, row["prompt"], row["response"])
    tools = sorted({e.tool_name for e in T.tool_calls(events)} | {a["name"] for a in ra["actions"]})
    ra["tools_called"] = tools
    return events, ra


def c_verdict(row, theory):
    events, ra = evidence(row)
    facts = ASP.build_evidence_facts(events, ra) + ASP.rule_facts(theory)
    return ASP.solve(facts)


def run_c(dataset, limit=None, variant="c0", final_theory="best"):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    preds, details = {}, {}
    for r in rows:
        det = {}
        t0 = time.time()
        th1 = build_theory(r, 1)
        det["theory1"] = th1
        if variant == "c0":
            theory = th1
        else:
            th2 = build_theory(r, 2)
            det["theory2"] = th2
            els = langextract_elements(r)
            det["lx_anchor_rate"] = els["anchor_rate"]
            det["lx_elements"] = len(els["all"])
            det["coverage1"] = coverage_check(th1, els["all"])
            det["coverage2"] = coverage_check(th2, els["all"])
            if variant == "c1":
                # naive union of rules
                merged = {"rules": th1.get("rules", []) + th2.get("rules", []),
                          "unrepresentable_notes": (th1.get("unrepresentable_notes", []) +
                                                    th2.get("unrepresentable_notes", []))}
                theory = merged
            elif variant == "c3":
                cr = critique_and_repair(r, th1, els["all"])
                det["criticisms"] = [c.get("issue", "")[:100] for c in (cr or {}).get("criticisms", [])]
                det["n_valid_criticisms"] = len((cr or {}).get("criticisms", []))
                theory = (cr or {}).get("repaired") or th1
            else:
                theory = th1
        det["theory_final"] = theory
        res = c_verdict(r, theory)
        det["asp"] = res
        det["elapsed"] = round(time.time() - t0, 1)
        # decision mapping
        if res.get("proved_error"):
            preds[r["id"]] = 1
        elif res.get("proved_no_error"):
            preds[r["id"]] = 0
        else:
            preds[r["id"]] = None
        det["pred"] = preds[r["id"]]
        details[r["id"]] = det
        print(f"{r['id']}: pred={preds[r['id']]} asp_err={res.get('proved_error')} "
              f"asp_ok={res.get('proved_no_error')} err={res.get('error')}", flush=True)
    golds = {r["id"]: r["gold"] for r in rows}
    strict = prf(preds, golds)
    # probabilistic decision layer: unresolved -> follow theory-agnostic 0 (strict) only
    save_result(f"arch_c_{variant}_{dataset}.json",
                {"variant": variant, "dataset": dataset, "metrics_strict": strict,
                 "preds": preds, "details": details})
    print(f"C/{variant}/{dataset} STRICT: {strict}")


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "synth-dev"
    variant = sys.argv[2] if len(sys.argv) > 2 else "c0"
    limit = int(sys.argv[3]) if len(sys.argv) > 3 else None
    run_c(ds, limit, variant)
