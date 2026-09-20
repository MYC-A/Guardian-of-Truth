"""C0 vs C3 controlled comparison on the FULL case set (pre-registered protocol,
see docs/agentz_prereg_c0c3.md). Applies the FROZEN P_CRITIC to every case of a
dataset (not only known false proofs), re-solves with identical evidence pipeline,
records transitions: FP_eliminated / TP_lost / FP_gained / TP_gained, UNRESOLVED
shares, F1. Raw critic outputs and repaired theories are saved for audit.

Usage: python3 arch_c3_full.py <dataset> [--phase all|critique|solve]
"""
import json, sys, time
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, save_result, SYSTEM_PROMPT, run_llm, extract_json, prf
from common.spans import locate
from common import timeline as T
from common import asp_lower as A1
from common import asp_lower2 as A2
from arch_c_theory import policy_text, P_CRITIC

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")


def raw_path(ds):
    return OUT / f"arch_c3_full_{ds}.json"


def solve_case(row, theory):
    """Identical evidence path to C0v3 verdict_v2 (only the theory differs)."""
    ev = T.parse_prompt(row["prompt"])
    ra = A1.analyze_response(ev, row["prompt"], row["response"])
    ra["tools_called"] = sorted({e.tool_name for e in T.tool_calls(ev)} | {a["name"] for a in ra["actions"]})
    lv = A2.latest_tool_values(ev)
    ta = A2.analyze_text_acts_lx(row["response"])
    lx_used = ta is not None
    if ta is None:
        ta, _ = A2.analyze_text_acts(row["response"], lv)
        ta = ta or {"reports": []}
    else:
        ents = {e for (_, _, e) in ta["reports"] if e}
        if ents:
            lv = [t for t in lv if t[1] in ents or t[1] == "*"]
    facts = A2.build_evidence_facts(ev, ra, text_acts=ta, latest=lv) + A2.rule_facts(theory)
    s = A2.solve(facts)
    s["_lx_used"] = lx_used
    return s


def pred_of(res):
    if not res:
        return None
    if res.get("proved_error"):
        return 1
    if res.get("proved_no_error"):
        return 0
    return None


def transition(gold, p0, p1):
    if gold == 0 and p0 == 1 and p1 != 1:
        return "FP_eliminated"
    if gold == 1 and p0 == 1 and p1 != 1:
        return "TP_lost"
    if gold == 0 and p0 != 1 and p1 == 1:
        return "FP_gained"
    if gold == 1 and p0 != 1 and p1 == 1:
        return "TP_gained"
    if gold == 1 and p0 != 1 and p1 != 1:
        return "FN_still" if p0 == 0 or p0 is None else "TP_lost"
    if gold == 0 and p0 != 1 and p1 != 1:
        return "TN_still"
    return "unchanged"


def critique_tasks(rows, c0v3):
    tasks = []
    for r in rows:
        p = policy_text(r["prompt"])
        th0 = c0v3["details"][r["id"]]["theory"]
        prompt = (P_CRITIC + "\n\nPOLICY:\n" + p[:9000] +
                  "\n\nGROUNDED ELEMENTS:\n[]\n\nTHEORY:\n" +
                  json.dumps(th0, ensure_ascii=False, indent=1))
        tasks.append({"id": f"{r['id']}-critF", "system": SYSTEM_PROMPT, "prompt": prompt})
    return tasks


def run(ds):
    rows = load_dataset(ds)
    c0v3 = json.loads((OUT / f"arch_c0v3_{ds}.json").read_text())
    golds = {r["id"]: r["gold"] for r in rows}

    # ---- phase 1: critique (cached, resumable) ----
    rawp = raw_path(ds)
    if rawp.exists():
        state = json.loads(rawp.read_text())
        critiques = state.get("critiques", {})
    else:
        state, critiques = {"protocol": "docs/agentz_prereg_c0c3.md @ this commit"}, {}

    todo_ids = [r["id"] for r in rows if f"{r['id']}-critF" not in critiques]
    if todo_ids:
        tasks = [t for t in critique_tasks(rows, c0v3) if t["id"].replace("-critF", "") in
                 [x for x in todo_ids]]
        print(f"critique: {len(tasks)} LLM calls...", flush=True)
        t0 = time.time()
        outs = run_llm(tasks, concurrency=4)
        for cid, text in outs.items():
            critiques[cid] = text
        print(f"critique done in {round(time.time()-t0,1)}s", flush=True)

    # parse + anchor
    parsed = {}
    for r in rows:
        cid = f"{r['id']}-critF"
        text = critiques.get(cid)
        j = extract_json(text) if text else None
        repaired = None
        crits = []
        if isinstance(j, dict):
            cand = j.get("repaired")
            if isinstance(cand, dict) and "rules" in cand:
                repaired = cand
            p = policy_text(r["prompt"])
            for c in (j.get("criticisms") or []) if isinstance(j.get("criticisms"), list) else []:
                q = (c or {}).get("source_quote") or ""
                anch = locate(q, p)
                crits.append(dict(c, anchor=anch,
                                  valid=anch.get("status") != "unanchored"))
        parsed[r["id"]] = {"repaired": repaired, "criticisms": crits,
                           "parse_ok": isinstance(j, dict)}

    # ---- phase 2: solve both arms (only repaired differs) ----
    results, transitions = {}, {}
    for r in rows:
        cid = r["id"]
        th0 = c0v3["details"][cid]["theory"]
        th1 = parsed[cid]["repaired"] or th0
        s0 = solve_case(r, th0)
        s1 = solve_case(r, th1)
        p0, p1 = pred_of(s0), pred_of(s1)
        tr = transition(golds[cid], p0, p1)
        transitions[cid] = tr
        th_diff = (len(json.dumps(th1)) - len(json.dumps(th0)))
        results[cid] = {
            "gold": golds[cid],
            "c0": {"pred": p0, "violations": s0.get("violations"),
                   "unknown": len(s0.get("unknown_rules", [])),
                   "notes": len(th0.get("unrepresentable_notes", []))},
            "c3": {"pred": p1, "violations": s1.get("violations"),
                   "unknown": len(s1.get("unknown_rules", [])),
                   "notes": len(th1.get("unrepresentable_notes", [])),
                   "repaired_is_new": parsed[cid]["repaired"] is not None},
            "n_criticisms": len(parsed[cid]["criticisms"]),
            "n_valid_criticisms": sum(1 for c in parsed[cid]["criticisms"] if c["valid"]),
            "criticism_issues": [c.get("issue", "")[:140] for c in parsed[cid]["criticisms"]],
            "theory_size_delta_chars": th_diff,
            "transition": tr,
        }
        print(f"{cid}: {p0}->{p1} gold={golds[cid]} {tr} "
              f"crits={results[cid]['n_valid_criticisms']}/{results[cid]['n_criticisms']}", flush=True)

    # ---- metrics ----
    m0 = prf({k: v["c0"]["pred"] for k, v in results.items()}, golds)
    m1 = prf({k: v["c3"]["pred"] for k, v in results.items()}, golds)
    tr_counts = {}
    for v in transitions.values():
        tr_counts[v] = tr_counts.get(v, 0) + 1
    unres0 = sum(1 for v in results.values() if v["c0"]["pred"] is None) / len(results)
    unres1 = sum(1 for v in results.values() if v["c3"]["pred"] is None) / len(results)
    notes0 = sum(v["c0"]["notes"] for v in results.values()) / len(results)
    notes1 = sum(v["c3"]["notes"] for v in results.values()) / len(results)

    save_result(f"arch_c3_full_{ds}.json", {
        "protocol": "docs/agentz_prereg_c0c3.md",
        "dataset": ds, "n": len(rows),
        "metrics_c0": m0, "metrics_c3": m1,
        "delta_f1": round(m1["f1"] - m0["f1"], 4),
        "transitions": tr_counts,
        "unresolved_share": {"c0": round(unres0, 4), "c3": round(unres1, 4)},
        "notes_avg": {"c0": round(notes0, 2), "c3": round(notes1, 2)},
        "results": results,
        "raw_critiques": critiques,
        "repaired_theories": {r["id"]: parsed[r["id"]]["repaired"] for r in rows
                              if parsed[r["id"]]["repaired"] is not None},
    })
    print(f"\nC0vsC3 {ds}: C0 F1={m0['f1']} (P={m0['precision']} R={m0['recall']}) | "
          f"C3 F1={m1['f1']} (P={m1['precision']} R={m1['recall']}) | dF1={round(m1['f1']-m0['f1'],4)}")
    print(f"transitions: {tr_counts}")
    print(f"UNRESOLVED: {round(unres0,3)} -> {round(unres1,3)} | notes avg: {round(notes0,2)} -> {round(notes1,2)}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "synth-dev")
