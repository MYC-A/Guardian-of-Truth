"""C3v2: critique + deterministic repair validation (pre-registered, see
docs/agentz_prereg_c3v2.md). Reuses cached critiques from arch_c3_full (no LLM).
Per repaired rule: V1 binding / V2 encodability / V3 field grounding; rejected
rules fall back to the original rule. Re-solve, measure transitions vs C0.

Usage: python3 arch_c3v2.py <dataset>
"""
import json, re, sys
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, save_result, prf
from common import timeline as T
from common import asp_lower as A1
from common import asp_lower2 as A2
from arch_c3_full import solve_case, pred_of, transition

OUT = Path("/home/z/my-project/got-agentz/outputs/agentz")

ENCODABLE_ACT = {"arg_gt", "arg_lt", "arg_gte", "arg_lte", "arg_equals",
                 "flag_true", "flag_false", "action_present", "action_absent",
                 "text_report", "value_is_latest"}


def evidence_vocab(row):
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
    facts = A2.build_evidence_facts(ev, ra, text_acts=ta, latest=lv)
    acts = set(ra["tools_called"])
    fields = {t[0] for t in lv}
    fields |= {f for (f, _, _) in ta.get("reports", [])}
    for s in facts:
        m = re.match(r'action\([^,]+,"([^"]+)"\)', s)
        if m:
            acts.add(m.group(1))
        m = re.match(r'arg\([^,]+,([^,]+),', s)
        if m:
            fields.add(m.group(1).strip('"'))
        m = re.match(r'text_report\("([^"]+)"', s)
        if m:
            fields.add(m.group(1))
    return ev, facts, acts, fields, lx_used


def encodable(c):
    t = c.get("type")
    if t not in ENCODABLE_ACT:
        return False
    if t == "action_absent" and not (c.get("closure_premise") or ""):
        return False
    return True


def rule_refs(c):
    t = c.get("type")
    refs = []
    if t in ("action_present", "action_absent"):
        refs.append(("act", c.get("tool")))
    elif t in ("arg_gt", "arg_lt", "arg_gte", "arg_lte", "arg_equals"):
        refs.append(("field", c.get("field")))
    elif t in ("flag_true", "flag_false"):
        refs.append(("field", c.get("flag")))
    elif t in ("text_report", "value_is_latest"):
        refs.append(("field", c.get("field")))
    return [(k, v) for k, v in refs if v]


def validate_rule(rnew, rold, acts, fields):
    """Return (accepted_rule, reject_reason or None)."""
    a = str(rnew.get("action", "") or "")
    if a and a != "*" and a not in acts:
        return rold, "V1_action_not_in_trace:" + a
    conds = list(rnew.get("conditions", []) or []) + list(rnew.get("exceptions", []) or [])
    for c in conds:
        if not encodable(c):
            return rold, "V2_unencodable:" + str(c.get("type"))
        for kind, ref in rule_refs(c):
            pool = acts if kind == "act" else fields
            if kind == "act" and ref != "*" and ref not in pool:
                return rold, f"V3_{kind}_not_in_trace:{ref}"
            if kind == "field" and str(ref) not in {str(x) for x in pool}:
                return rold, f"V3_{kind}_not_in_trace:{ref}"
    return rnew, None


def validate_theory(th0, th1, acts, fields):
    th2 = {"rules": [], "unrepresentable_notes": list(th0.get("unrepresentable_notes", []) or [])}
    rejects = []
    old_by_id = {str(r.get("id") or f"R{i+1}"): r for i, r in enumerate(th0.get("rules", []))}
    for i, r1 in enumerate(th1.get("rules", [])):
        rid = str(r1.get("id") or f"R{i+1}")
        r0 = old_by_id.get(rid, {"id": rid, "kind": "prohibition", "action": "",
                                 "conditions": [], "exceptions": [],
                                 "unrepresentable_parts": ["replaced_rule_dropped"]})
        vr, why = validate_rule(r1, r0, acts, fields)
        th2["rules"].append(vr)
        if why:
            rejects.append({"rule_id": rid, "reason": why[:120]})
    return th2, rejects


def run(ds):
    rows = {r["id"]: r for r in load_dataset(ds)}
    c3 = json.loads((OUT / f"arch_c3_full_{ds}.json").read_text())
    golds = {r["id"]: r["gold"] for r in rows}
    c0v3 = json.loads((OUT / f"arch_c0v3_{ds}.json").read_text())

    results, rej_total = {}, {"V1": 0, "V2": 0, "V3": 0}
    for cid, r in rows.items():
        det0 = c0v3["details"][cid]
        th0 = det0["theory"]
        repaired = c3.get("repaired_theories", {}).get(cid)
        ev, facts, acts, fields, lx_used = evidence_vocab(r)
        if repaired:
            th2, rejects = validate_theory(th0, repaired, acts, fields)
        else:
            th2, rejects = th0, []
        for rej in rejects:
            k = rej["reason"].split(":")[0].split("_")[0]
            rej_total[k if k in rej_total else "V3"] += 1
        s2 = solve_case(r, th2)
        p0 = det0.get("pred")
        p0 = p0 if p0 is not None else pred_of(s2) if False else p0
        # recompute C0 pred from stored asp for consistency:
        a0 = det0.get("asp", {})
        p0 = 1 if a0.get("proved_error") else (0 if a0.get("proved_no_error") else None)
        p2 = pred_of(s2)
        results[cid] = {
            "gold": golds[cid],
            "c0_pred": p0, "c3v2_pred": p2,
            "violations": s2.get("violations"),
            "n_rejected_rules": len(rejects),
            "rejects": rejects,
            "repaired_was_present": repaired is not None,
            "transition": transition(golds[cid], p0, p2),
        }
        print(f"{cid}: {p0}->{p2} gold={golds[cid]} {results[cid]['transition']} rej={len(rejects)}", flush=True)

    m0 = prf({k: v["c0_pred"] for k, v in results.items()}, golds)
    m2 = prf({k: v["c3v2_pred"] for k, v in results.items()}, golds)
    tr = {}
    for v in results.values():
        tr[v["transition"]] = tr.get(v["transition"], 0) + 1
    unres = sum(1 for v in results.values() if v["c3v2_pred"] is None) / len(results)
    save_result(f"arch_c3v2_{ds}.json", {
        "protocol": "docs/agentz_prereg_c3v2.md", "dataset": ds, "n": len(rows),
        "metrics_c0": m0, "metrics_c3v2": m2,
        "delta_f1_vs_c0": round(m2["f1"] - m0["f1"], 4),
        "transitions": tr, "unresolved_share_c3v2": round(unres, 4),
        "rejections_by_mechanism": rej_total,
        "results": results,
    })
    print(f"\nC3v2 {ds}: C0 F1={m0['f1']} -> C3v2 F1={m2['f1']} "
          f"(d={round(m2['f1']-m0['f1'],4)}) transitions={tr} rejects={rej_total}")


if __name__ == "__main__":
    run(sys.argv[1] if len(sys.argv) > 1 else "synth-dev")
