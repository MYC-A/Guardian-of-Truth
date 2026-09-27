"""Real-track evidence gate: run the EVIDENCE arm (extractive span + judge)
on the BASE-accepted pairs of the REAL frontend track, to test whether the
licensing mechanism survives noisy predicted events.

Uses the same ev/evjudge prompts as the oracle track; events are the
FRONTEND-predicted ones (spans/roles/tools), scoring via span matching.

Run: python3 pl_real_evgate.py
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import (Mistral, load_suite, out_dir, render_tool,
                       tools_by_name, ev_by_eid, sentence_of_span)
from pl_run_llm import SYSTEM, ev_user, evjudge_user

CE_BAND = 0.35


def relocate(policy, span):
    idx = policy.find(span)
    return idx


def main():
    suite = load_suite("original")
    from sentence_transformers import CrossEncoder
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=out_dir("_cache"))
    outdir = out_dir("REAL_ev")
    t0 = time.time()
    n = 0

    # reuse the CE scores computed by pl_run_real? They were not persisted per
    # pair; recompute quickly for BASE-accepted detection only (cheap, local).
    per_case = []
    for case in suite:
        fpath = out_dir("FRONTEND") / f"{case['case_id']}.json"
        if not fpath.is_file():
            continue
        pred = json.loads(fpath.read_text(encoding="utf-8"))["events"]
        gold_events = case["events"]
        by_name = tools_by_name(case)

        # CE for all pairs
        pairs = []
        for i in range(len(pred)):
            for j in range(i + 1, len(pred)):
                a, b = pred[i], pred[j]
                sa, _ = sentence_of_span(case["policy"], a["span_start"])
                sb, _ = sentence_of_span(case["policy"], b["span_start"])
                tb = " ".join(render_tool(by_name[t]) for t in b.get("governed_tools", []) if t in by_name)
                pairs.append(((i, j), (sa or a["span"],
                                        f"{b['span']}. {sb or ''} {tb}".strip())))
        scores = rer.predict([p[1] for p in pairs], batch_size=32,
                             convert_to_numpy=True) if pairs else []
        ce = {p[0]: float(s) for p, s in zip(pairs, scores)}

        # mistral det for all pairs
        det = {}
        for (i, j) in ce:
            a = {"source_span": pred[i]["span"], "role": pred[i]["role"],
                 "governed_tools": pred[i].get("governed_tools", []),
                 "span_start": pred[i]["span_start"]}
            b = {"source_span": pred[j]["span"], "role": pred[j]["role"],
                 "governed_tools": pred[j].get("governed_tools", []),
                 "span_start": pred[j]["span_start"]}
            rec = client.ask(SYSTEM, det_user_real(case, a, b), max_tokens=220)
            n += 1
            ans, err = Mistral.parse_json(rec["raw"])
            det[(i, j)] = (ans or {}).get("decision")

        # BASE-accepted pairs -> evidence gate
        accepted = [(i, j) for (i, j), d in det.items()
                    if d == "RELATED" and ce[(i, j)] >= CE_BAND]

        ev_rows = []
        for (i, j) in accepted:
            a = {"source_span": pred[i]["span"], "role": pred[i]["role"],
                 "governed_tools": pred[i].get("governed_tools", []),
                 "span_start": pred[i]["span_start"]}
            b = {"source_span": pred[j]["span"], "role": pred[j]["role"],
                 "governed_tools": pred[j].get("governed_tools", []),
                 "span_start": pred[j]["span_start"]}
            rec = client.ask(SYSTEM, ev_user_real(case, a, b), max_tokens=300)
            n += 1
            ans, err = Mistral.parse_json(rec["raw"])
            ev_text = _clean((ans or {}).get("evidence"))
            verbatim = bool(ev_text and ev_text not in (None, "NO_EVIDENCE")
                            and ev_text in case["policy"])
            decision = "UNSUPPORTED"
            judge_reason = None
            if verbatim:
                rec2 = client.ask(SYSTEM, evjudge_user_real(a, b, ev_text), max_tokens=220)
                n += 1
                ans2, _ = Mistral.parse_json(rec2["raw"])
                d2 = (ans2 or {}).get("decision")
                judge_reason = (ans2 or {}).get("reason")
                decision = {"LICENSED": "RELATED", "NOT_LICENSED": "NOT_RELATED"}.get(d2, "UNKNOWN")
            ev_rows.append({"i": i, "j": j, "evidence": ev_text,
                            "verbatim": verbatim, "decision": decision,
                            "judge_reason": judge_reason})

        path = outdir / f"{case['case_id']}.json"
        path.write_text(json.dumps({"case_id": case["case_id"],
                                    "n_pred": len(pred), "ce": {f"{i}_{j}": v for (i, j), v in ce.items()},
                                    "det": {f"{i}_{j}": v for (i, j), v in det.items()},
                                    "ev_rows": ev_rows}, ensure_ascii=False, indent=1),
                        encoding="utf-8")
        print(f"[{case['case_id']}] pred={len(pred)} accepted={len(accepted)}", flush=True)

    write_usage("REAL_ev", {"phase": "real_ev", "calls": n,
                            "wall_seconds": round(time.time() - t0, 1)})
    print(f"real evidence gate done: {n} calls")


def _clean(s):
    if not isinstance(s, str):
        return s
    t = s.strip()
    while t and t[0] in "\"'" + chr(8220) and t[-1] in "\"'" + chr(8221):
        t = t[1:-1].strip()
    return t


def det_user_real(case, a, b):
    from pl_run_llm import det_user
    return det_user(case, a, b)


def ev_user_real(case, a, b):
    from pl_run_llm import ev_user
    return ev_user(case, a, b)


def evjudge_user_real(a, b, evidence):
    from pl_run_llm import evjudge_user
    return evjudge_user(a, b, evidence)


if __name__ == "__main__":
    main()
