"""C0-v3 driver: theories with the EXTENDED ontology (text_report/value_is_latest),
solved with ASP v2 + LangExtract text-acts. The ontology co-evolves with the
verifier: freshness becomes representable, so theories stop marking it unrep."""
import sys, json, time
from pathlib import Path
sys.path.insert(0, "/home/z/my-project/got-agentz/experiments/agentz_arch_v1")
from common.io_utils import load_dataset, prf, save_result, SYSTEM_PROMPT, run_llm, extract_json
from common import timeline as T
from common import asp_lower2 as A2
from arch_c_theory import policy_text, P_THEORY3, evidence

def build_theory_v3(row):
    p = policy_text(row["prompt"])
    prompt = (P_THEORY3 + "\n\nPOLICY:\n" + p +
              "\n\nTARGET RESPONSE (for action names only):\n" + row["response"][:1500])
    out = run_llm([{"id": f"{row['id']}-t3", "system": SYSTEM_PROMPT, "prompt": prompt}],
                  concurrency=1)
    j = extract_json(out.get(f"{row['id']}-t3"))
    if j is None or "rules" not in j:
        j = {"rules": [], "unrepresentable_notes": ["theory_parse_failed"]}
    return j

def verdict_v2(row, theory):
    events, ra = evidence(row)
    lv = A2.latest_tool_values(events)
    ta = A2.analyze_text_acts_lx(row["response"])
    if ta is None:
        ta, _ = A2.analyze_text_acts(row["response"], lv)
        lx_used = False
    else:
        lx_used = True
        ents = {e for (_, _, e) in ta["reports"] if e}
        if ents:
            lv = [t for t in lv if t[1] in ents or t[1] == "*"]
    facts = A2.build_evidence_facts(events, ra, text_acts=ta, latest=lv) + A2.rule_facts(theory)
    s = A2.solve(facts)
    return s, {"text_acts": ta.get("reports", []), "lx_used": lx_used,
               "latest": lv[:8]}

def run(dataset, limit=None):
    rows = load_dataset(dataset)
    if limit:
        rows = rows[:limit]
    # resume support: incremental checkpoint after every case
    out_path = Path("/home/z/my-project/got-agentz/outputs/agentz") / f"arch_c0v3_{dataset}.json"
    preds, details = {}, {}
    if out_path.exists():
        try:
            prev = json.loads(out_path.read_text())
            preds = prev.get("preds", {})
            details = prev.get("details", {})
            print(f"resuming: {len(preds)} cases already done", flush=True)
        except Exception:
            pass
    for r in rows:
        if r["id"] in preds and preds[r["id"]] is not None:
            continue
        if r["id"] in preds and preds[r["id"]] is None and r["id"] in details and "theory" in details[r["id"]]:
            continue
        # batch-build any missing theories first (concurrent, cache-backed)
        missing = [x for x in rows if x["id"] not in details or "theory" not in details.get(x["id"], {})]
        if missing:
            tasks = []
            for x in missing:
                p = policy_text(x["prompt"])
                prompt = (P_THEORY3 + "\n\nPOLICY:\n" + p +
                          "\n\nTARGET RESPONSE (for action names only):\n" + x["response"][:1500])
                tasks.append({"id": f"{x['id']}-t3", "system": SYSTEM_PROMPT,
                              "prompt": prompt, "max_tokens": 6144})
            outs = run_llm(tasks, concurrency=4)
            for x in missing:
                j = extract_json(outs.get(f"{x['id']}-t3"))
                if j is None or not isinstance(j, dict) or "rules" not in j:
                    j = {"rules": [], "unrepresentable_notes": ["theory_parse_failed"]}
                details.setdefault(x["id"], {})["theory"] = j
        t0 = time.time()
        th = details[r["id"]]["theory"]
        res, meta = verdict_v2(r, th)
        pred = 1 if res.get("proved_error") else (0 if res.get("proved_no_error") else None)
        preds[r["id"]] = pred
        details[r["id"]] = {"theory": th, "asp": res, "meta": meta, "pred": pred,
                            "elapsed": round(time.time() - t0, 1)}
        print(f"{r['id']}: pred={pred} err={res.get('proved_error')} ok={res.get('proved_no_error')} "
              f"unk={res.get('unknown_rules')} stale={res.get('stale')} lx={meta['lx_used']}", flush=True)
        golds_ = {x["id"]: x["gold"] for x in rows}
        save_result(f"arch_c0v3_{dataset}.json",
                    {"variant": "c0v3", "dataset": dataset, "metrics_strict": prf(preds, golds_),
                     "preds": preds, "details": details})
    golds = {r["id"]: r["gold"] for r in rows}
    m = prf(preds, golds)
    save_result(f"arch_c0v3_{dataset}.json",
                {"variant": "c0v3", "dataset": dataset, "metrics_strict": m,
                 "preds": preds, "details": details})
    print(f"C0v3/{dataset} STRICT: {m}")

if __name__ == "__main__":
    ds = sys.argv[1] if len(sys.argv) > 1 else "synth-dev"
    limit = int(sys.argv[2]) if len(sys.argv) > 2 and sys.argv[2].isdigit() else None
    run(ds, limit)
