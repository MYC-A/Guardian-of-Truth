"""IDEA D — counterfactual licensing gate (inference-time mechanism).

For every edge A->B accepted by the BASE detector:
  1. GENERATE a controlled counterfactual policy where ONLY the binding of A
     changes: A is rebound to a different plausible candidate C (the best
     non-B candidate from the retriever ranking). One LLM call.
  2. VERIFY the counterfactual is controlled (else the gate abstains):
       - differs from the original;
       - all event spans except B and C still appear verbatim;
       - A's span still appears;
       - length ratio within [0.7, 1.4].
  3. RE-RUN the narrow pair question on the counterfactual for (A,B) and
     (A,C).
  4. GATE: the edge A->B stays LICENSED only if the detector DROPS it in the
     counterfactual world (decision for (A,B) != RELATED). If the detector
     still binds A->B there, it is following world plausibility, not the
     policy text -> the edge is downgraded to UNKNOWN.

Run (after det phase): PL_SUITE=original PL_MODEL=mistral python3 pl_run_cf_gate.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import (MODELS, Mistral, load_suite, out_dir, render_tool,
                       tools_by_name, ev_by_eid, sentence_of_span, write_usage)
from pl_run_llm import SYSTEM, det_user

CE_BAND = 0.35

CFGEN_SYSTEM = ("You are a careful editor of workplace policy texts. You make "
                "MINIMAL controlled edits. Answer strictly as a single JSON "
                "object, no extra text.")


def cfgen_user(case, a, b, c):
    return ("ORIGINAL POLICY:\n"
            f"{case['policy']}\n\n"
            f'EVENT A: "{a["source_span"]}" (role: {a["role"]})\n'
            f'EVENT B (currently bound to A): "{b["source_span"]}" (role: {b["role"]})\n'
            f'EVENT C (alternative target): "{c["source_span"]}" (role: {c["role"]})\n\n'
            "Task: rewrite the policy so that the textual binding that "
            "currently connects event A to event B is changed to connect "
            "event A to event C instead. Change ONLY that binding - keep "
            "every other statement, entity, modality and relation exactly as "
            "in the original. Keep the style and length similar. Do not "
            "remove or add any other requirement. Output the full rewritten "
            "policy.\n"
            'Answer strictly as JSON: {"rewritten_policy": "<full rewritten policy text>"}')


def relocate(policy, ev):
    """Re-locate an event span inside a (counterfactual) policy by text."""
    idx = policy.find(ev["source_span"])
    if idx < 0:
        return {**ev, "span_start": -1, "span_end": -1}
    return {**ev, "span_start": idx, "span_end": idx + len(ev["source_span"])}


def verify_controlled(case, cf_policy, a, b, c):
    """The CF edit is controlled iff: it differs, keeps A and every event
    other than the swap pair findable verbatim, and has a sane length."""
    if not cf_policy or cf_policy.strip() == case["policy"].strip():
        return False, "identical_or_empty"
    ratio = len(cf_policy) / max(1, len(case["policy"]))
    if not (0.7 <= ratio <= 1.4):
        return False, f"length_ratio_{ratio:.2f}"
    if cf_policy.find(a["source_span"]) < 0:
        return False, "anchor_A_lost"
    for ev in case["events"]:
        if ev["eid"] in (b["eid"], c["eid"]):
            continue
        if cf_policy.find(ev["source_span"]) < 0:
            return False, f"event_{ev['eid']}_lost"
    return True, "ok"


def main():
    model_key = os.environ.get("PL_MODEL", "mistral")
    which = os.environ.get("PL_SUITE", "original")
    model = MODELS[model_key]
    suite = load_suite(which)
    suffix = "" if which == "original" else "_" + which
    pair_dir = out_dir("PAIR_signals" + suffix)
    det_dir = out_dir(f"det_{model_key}{suffix}")
    client = Mistral(model=model, cache_dir=out_dir("_cache"))

    outdir = out_dir(f"cfgate_{model_key}{suffix}")
    t0 = time.time()
    n = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        dpath = det_dir / f"{case['case_id']}.json"
        spath = pair_dir / f"{case['case_id']}.json"
        if path.is_file() or not dpath.is_file() or not spath.is_file():
            continue
        evmap = ev_by_eid(case)
        det = json.loads(dpath.read_text(encoding="utf-8"))["rows"]
        sig = json.loads(spath.read_text(encoding="utf-8"))
        sig_map = {frozenset((r["a_eid"], r["b_eid"])): r for r in sig["pairs"]}
        rankings = sig["rankings"]

        # BASE-accepted edges
        accepted = []
        for r in det:
            if r.get("decision") != "RELATED":
                continue
            key = frozenset((r["a_eid"], r["b_eid"]))
            s = sig_map.get(key)
            if s is None or max(s["ce_both_ab"], s["ce_both_ba"]) < CE_BAND:
                continue
            accepted.append((r["a_eid"], r["b_eid"]))

        rows = []
        for a_eid, b_eid in accepted:
            a, b = evmap[a_eid], evmap[b_eid]
            # alternative candidate C: best-ranked non-B candidate for A
            c_eid = None
            for c in rankings.get(a_eid, []):
                if c["eid"] != b_eid and c["eid"] in evmap:
                    c_eid = c["eid"]
                    break
            if c_eid is None:
                rows.append({"a_eid": a_eid, "b_eid": b_eid, "c_eid": None,
                             "gate": "NO_ALTERNATIVE", "cf_verified": None})
                continue
            c_ev = evmap[c_eid]
            rec = client.ask(CFGEN_SYSTEM, cfgen_user(case, a, b, c_ev),
                             max_tokens=600)
            ans, err = Mistral.parse_json(rec["raw"])
            cf_policy = (ans or {}).get("rewritten_policy")
            n += 1
            ok, why = verify_controlled(case, cf_policy, a, b, c_ev)
            if not ok:
                rows.append({"a_eid": a_eid, "b_eid": b_eid, "c_eid": c_eid,
                             "gate": "UNVERIFIED_CF", "cf_verified": False,
                             "cf_check": why})
                continue
            # rebuild the case against the CF policy: relocate spans by text
            cf_events = [relocate(cf_policy, e) for e in case["events"]]
            cf_case = {**case, "policy": cf_policy, "events": cf_events}
            a_cf = next(e for e in cf_events if e["eid"] == a_eid)
            b_cf = next(e for e in cf_events if e["eid"] == b_eid)
            c_cf = next(e for e in cf_events if e["eid"] == c_eid)
            # re-run pair detection on the counterfactual policy
            rec_ab = client.ask(SYSTEM, det_user(cf_case, a_cf, b_cf), max_tokens=220)
            ans_ab, _ = Mistral.parse_json(rec_ab["raw"])
            rec_ac = client.ask(SYSTEM, det_user(cf_case, a_cf, c_cf), max_tokens=220)
            ans_ac, _ = Mistral.parse_json(rec_ac["raw"])
            n += 2
            dec_ab = (ans_ab or {}).get("decision")
            dec_ac = (ans_ac or {}).get("decision")
            if dec_ab in ("NOT_RELATED", "UNKNOWN"):
                gate = "LICENSED"       # detector dropped the edge under the swap
            else:
                gate = "WORLD_DRIVEN"   # still binds A->B in the CF world
            rows.append({"a_eid": a_eid, "b_eid": b_eid, "c_eid": c_eid,
                         "gate": gate, "cf_verified": True,
                         "cf_decision_ab": dec_ab, "cf_decision_ac": dec_ac})
        path.write_text(json.dumps({"case_id": case["case_id"], "rows": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")

    write_usage(f"cfgate_{model_key}{suffix}", {
        "phase": "cf_gate", "model": model, "suite": which, "calls": n,
        "wall_seconds": round(time.time() - t0, 1)})
    print(f"cf gate done: {n} calls")


if __name__ == "__main__":
    main()
