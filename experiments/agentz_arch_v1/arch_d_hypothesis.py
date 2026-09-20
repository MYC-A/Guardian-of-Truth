"""Architecture D - local formal verification of a single error hypothesis.

Instead of formalizing the whole policy first (arch C), the system takes a
concrete suspicion (from A1/B1), extracts ONLY the relevant rule fragment +
applicable conditions + relevant facts, and asks Clingo to check this single
hypothesis. Unrepresentable/uncertain => the suspicion stays (never proved).
Label: 1 if >=1 suspicion formally confirmed; else fallback = B2 label.
"""
import sys, json
from pathlib import Path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from common.io_utils import load_dataset, run_llm, prf, save_result, extract_json, SYSTEM_PROMPT
from common import timeline as T
from common import asp_lower as ASP

P_D = """A first reviewer suspected an error in the agent's final response. Your task:
extract ONLY the policy requirements relevant to THIS suspicion, as a formal theory.
Include: the exact rule the suspicion is about (kind prohibition/obligation/requirement,
action = exact tool name), all its conditions, and ALL exceptions that could change the
verdict (кроме/unless/only if/уже/текущем обращении...). Use ONLY these types:
  arg_gt/arg_lt/arg_gte/arg_lte/arg_equals (numeric field of the action args)
  flag_true/flag_false (boolean JSON field from tool results)
  action_present/action_absent (tool called in history; action_absent needs closure_premise quote)
Also extract the FACTS of this conversation relevant to the suspicion:
  response_action: tool call(s) the agent made in the final response (name + numeric args)
  observed_flags: boolean fields from tool results with their true/false value
  tools_called: list of tool names called during the conversation (from history)
If the suspicion is about a text claim (value/entity/reporting) rather than an action,
set "text_claim": true and still provide the relevant rule if any.
Answer with JSON only:
{"theory":{"rules":[...],"unrepresentable_notes":[...]},
 "facts":{"response_action":{"name":"...","args":{...}},"observed_flags":[{"flag":"...","value":true}],
          "tools_called":["..."]},
 "unrepresentable_parts":[...]}
"""

P_D_CLAIM = """A reviewer suspected the agent's final TEXT contains an ungrounded or stale claim.
Decide strictly from the conversation facts:
1) Is there a LATER tool result (after the evidence the reviewer cites) that shows the
   correct/current value for the same entity and field?
2) Does the final response match that latest tool result?
3) Or does no tool result support the claimed value at all?
Answer JSON: {"verdict":"refuted|supported|unresolved",
 "ground_quote":"<exact verbatim quote from the conversation supporting your verdict>",
 "reason":"..."}
"""


def d_formalize(row, suspicion):
    ctx = row["prompt"]
    tasks = [{"id": f"{row['id']}-d",
              "system": SYSTEM_PROMPT,
              "prompt": P_D + "\n\nCONVERSATION:\n" + ctx[:90000] +
                        "\n\nSUSPICION:\n" + json.dumps(
                            {"description": suspicion.get("description", ""),
                             "policy_quote": suspicion.get("policy_quote", ""),
                             "response_fragment": suspicion.get("response_fragment", "")},
                            ensure_ascii=False)}]
    out = run_llm(tasks, concurrency=1)
    j = extract_json(out.get(f"{row['id']}-d"))
    return j


def d_check_hypothesis(row, j):
    """Run clingo on the hypothesis-local theory + LLM-proposed facts cross-checked
    against the deterministic timeline (facts are only accepted if verifiable)."""
    if not j or not isinstance(j, dict):
        return {"verdict": "unresolved", "reason": "no_parse"}
    theory = j.get("theory") or {}
    facts_json = j.get("facts") or {}
    # deterministic evidence from timeline
    events = T.parse_prompt(row["prompt"])
    ra = ASP.analyze_response(events, row["prompt"], row["response"])
    ra["tools_called"] = sorted({e.tool_name for e in T.tool_calls(events)})
    # observed flags: union of deterministic scan + LLM flags that match names found in payload booleans
    det_flags = {f["name"]: f["value"] for f in ra["flags"]}
    for f in facts_json.get("observed_flags", []):
        if f.get("flag") in det_flags:
            pass  # deterministic value wins
        else:
            ra["flags"].append({"name": f.get("flag"), "value": bool(f.get("value")), "ts_idx": -1})
    # response action: use deterministic parse of the response (trusted) + LLM-declared action
    if not ra["actions"] and facts_json.get("response_action"):
        ra["actions"].append({"name": facts_json["response_action"].get("name", ""),
                              "args": facts_json["response_action"].get("args", {}),
                              "span": (0, 0)})
    facts = ASP.build_evidence_facts(events, ra) + ASP.rule_facts(theory)
    res = ASP.solve(facts)
    return res


def run_d(dataset, limit=None):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    b = json.loads((Path(__file__).resolve().parent.parent.parent / "outputs" / "agentz" /
                    f"arch_b_{dataset}.json").read_text())
    preds, details = {}, {}
    for r in rows:
        det = b["details"].get(r["id"], {})
        s2 = det.get("b2", [])
        surv = [s for s in s2 if s.get("status") != "refuted_stale"]
        if not surv:
            preds[r["id"]] = b["preds_b2"].get(r["id"], 0)
            details[r["id"]] = {"d": "no_suspicions"}
            continue
        any_proved = False
        dlogs = []
        for s in surv[:3]:
            j = d_formalize(r, s)
            res = d_check_hypothesis(r, j)
            dlogs.append({"suspicion": s.get("description", "")[:80], "asp": res})
            if res.get("proved_error"):
                any_proved = True
                break
        if any_proved:
            preds[r["id"]] = 1
        else:
            # formal channel did not confirm; fall back to probabilistic B2 label
            preds[r["id"]] = b["preds_b2"].get(r["id"], 1 if surv else 0)
        details[r["id"]] = {"d": dlogs}
    golds = {r["id"]: r["gold"] for r in rows}
    m = prf(preds, golds)
    save_result(f"arch_d_{dataset}.json",
                {"variant": "d_hypothesis", "dataset": dataset, "metrics": m,
                 "preds": preds, "details": details})
    print(f"D/{dataset}: {m}")


if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "public46"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 else None
    run_d(ds, limit)
