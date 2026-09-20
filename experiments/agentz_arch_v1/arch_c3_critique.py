"""C3 critique experiment on symbolic FALSE PROOFS: can a source-grounded critic
repair inverted/forced theories? For each false-proof case, the critic sees the
POLICY + the wrong theory and must (a) list criticisms each anchored in a policy
quote, (b) emit a repaired theory. Re-solve with ASP v2 + LX evidence. Measure:
false proofs fixed / true proofs preserved."""
import json, sys
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, save_result, SYSTEM_PROMPT, run_llm, extract_json
from common.spans import locate
from common import timeline as T
from common import asp_lower as A1
from common import asp_lower2 as A2
from arch_c_theory import policy_text, P_CRITIC

FALSE_PROOFS = None  # derived dynamically from reeval output if not overridden

def get_false_proofs():
    import sys as _s
    if len(_s.argv) > 1 and _s.argv[1] == "--all":
        d = json.loads(Path("/home/z/my-project/got-agentz/outputs/agentz/reeval_c0v3_repaired_cascade.json").read_text())
        return [cid for cid, v in d["detail"].items()
                if v["p_sym"] == 1 and v["gold"] == 0]
    return FALSE_PROOFS or ["syn-exception_missed-en-1-ok", "syn-threshold_direct-ru-0-ok",
                "syn-threshold_direct-ru-1-ok", "syn-actor_confusion-ru-0-ok",
                "syn-actor_confusion-ru-1-ok", "syn-actor_confusion-ru-2-ok"]

def critique_case(row, theory):
    p = policy_text(row["prompt"])
    prompt = (P_CRITIC + "\n\nPOLICY:\n" + p[:9000] +
              "\n\nGROUNDED ELEMENTS:\n[]\n\nTHEORY:\n" +
              json.dumps(theory, ensure_ascii=False, indent=1))
    out = run_llm([{"id": f"{row['id']}-crit", "system": SYSTEM_PROMPT, "prompt": prompt}],
                  concurrency=1)
    j = extract_json(out.get(f"{row['id']}-crit"))
    if not j or not isinstance(j, dict):
        return None, []
    repaired = j.get("repaired") or theory
    valid = []
    for c in j.get("criticisms", []):
        q = c.get("source_quote") or ""
        anch = locate(q, p)
        c2 = dict(c, anchor=anch)
        if anch["status"] != "unanchored":
            valid.append(c2)
    return repaired, valid

def solve_case(row, theory):
    ev = T.parse_prompt(row["prompt"])
    ra = A1.analyze_response(ev, row["prompt"], row["response"])
    ra["tools_called"] = sorted({e.tool_name for e in T.tool_calls(ev)} | {a["name"] for a in ra["actions"]})
    lv = A2.latest_tool_values(ev)
    ta = A2.analyze_text_acts_lx(row["response"]) or {"reports": []}
    ents = {e for (_, _, e) in ta["reports"] if e}
    if ents:
        lv = [t for t in lv if t[1] in ents or t[1] == "*"]
    facts = A2.build_evidence_facts(ev, ra, text_acts=ta, latest=lv) + A2.rule_facts(theory)
    return A2.solve(facts)

def main():
    rows = {r["id"]: r for r in load_dataset("synth-dev")}
    c0v3 = json.loads(Path("/home/z/my-project/got-agentz/outputs/agentz/arch_c0v3_synth-dev.json").read_text())
    out = {"cases": {}}
    n_fixed = n_kept = n_broke = 0
    for cid in get_false_proofs():
        r = rows[cid]
        th0 = c0v3["details"][cid]["theory"]
        s0 = solve_case(r, th0)
        repaired, crits = critique_case(r, th0)
        s1 = solve_case(r, repaired) if repaired else None
        fixed = (s0.get("proved_error") and s1 is not None and not s1.get("proved_error"))
        n_fixed += int(fixed)
        n_kept += int(not s0.get("proved_error"))
        det = {"gold": r["gold"],
               "before": {"violations": s0.get("violations"), "pred": 1 if s0.get("proved_error") else None},
               "after": ({"violations": s1.get("violations"),
                          "pred": 1 if s1.get("proved_error") else (0 if s1.get("proved_no_error") else None)} if s1 else None),
               "n_valid_criticisms": len(crits),
               "criticisms": [c.get("issue", "")[:120] for c in crits],
               "repaired_theory": repaired,
               "fixed": bool(fixed)}
        out["cases"][cid] = det
        print(f"{cid}: fixed={det['fixed']} before={det['before']['violations']} "
              f"after={(det['after'] or {}).get('pred')} crits={len(crits)}", flush=True)
    out["summary"] = {"n": len(get_false_proofs()), "fixed": n_fixed}
    save_result("arch_c3_critique_falseproofs.json", out)
    print(f"SUMMARY: fixed {n_fixed}/{len(get_false_proofs())} false proofs")

if __name__ == "__main__":
    main()
