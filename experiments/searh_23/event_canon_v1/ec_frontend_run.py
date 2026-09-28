"""EVENT_CANON_v1 Track B: run the EXISTING frontend (pl_frontend, unchanged)
on the new frozen policies -> predicted mentions.

Reuses analyse_case / grounding / resolver from policy_licensing_v1 verbatim;
only the suite source and output dir differ. Run BEFORE annotating the
Track B gold alignment (alignment is gold, annotated by us, committed before
any canonicalization inference).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PL_DIR = HERE.parent / "policy_licensing_v1"
sys.path.insert(0, str(PL_DIR))
sys.path.insert(0, str(HERE))

from pl_frontend import analyse_case, RESOLVER_SYSTEM, LABEL_TO_ROLE  # noqa
from pl_common import Mistral, render_tool  # noqa
from ec_common import load_suite, out_dir, write_usage


def main():
    import os
    import torch
    from sentence_transformers import CrossEncoder
    import stanza

    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    client = Mistral(model="ministral-14b-latest",
                     cache_dir=out_dir("_cache"))
    which = os.environ.get("EC_SUITE", "original")
    outdir = out_dir("FRONTEND" if which == "original" else "FRONTEND_renamed")
    t0 = time.time()
    n_calls = 0
    for case in load_suite(which):
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        policy = case["policy"]
        cands = analyse_case(nlp, {"policy": policy})
        pairs, owners = [], []
        for i, c in enumerate(cands):
            for t in case["tools"]:
                pairs.append((c["span"], render_tool(t)))
                owners.append(i)
        scores = rer.predict(pairs, batch_size=32, convert_to_numpy=True) if pairs else []
        top3_by_cand = {}
        for i, s in zip(owners, scores):
            top3_by_cand.setdefault(i, []).append((float(s)))
        tool_names = [t["name"] for t in case["tools"]]
        events = []
        for i, c in enumerate(cands):
            sc = top3_by_cand.get(i, [])
            ranked = sorted(zip(sc, tool_names), key=lambda x: -x[0])[:3]
            top3 = [next(t for t in case["tools"] if t["name"] == n)
                    for _, n in ranked]
            if not top3:
                continue
            user = json.dumps({"policy_span": c["span"], "tools": top3},
                              ensure_ascii=False)
            rec = client.ask(RESOLVER_SYSTEM, user, max_tokens=200)
            n_calls += 1
            ans, err = Mistral.parse_json(rec["raw"])
            label = (ans or {}).get("label")
            if isinstance(label, dict):
                label = label.get("label") or label.get("role") or label.get("choice")
            from pl_frontend import COND_MARKS
            role = LABEL_TO_ROLE.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            if c.get("mark") in COND_MARKS and role == "OPERATION_EFFECT":
                role = "PRECONDITION_CHECK"
            events.append({"span": c["span"], "span_start": c["start"],
                           "span_end": c["end"], "role": role,
                           "governed_tools": [ranked[0][1]] if ranked else [],
                           "resolver_label": label,
                           "is_np": bool(c.get("is_np")),
                           "dep": c.get("dep"), "mark": c.get("mark")})
        path.write_text(json.dumps({"case_id": case["case_id"],
                                    "events": events}, ensure_ascii=False,
                                   indent=1), encoding="utf-8")
        print(f"[{case['case_id']}] {len(cands)} candidates -> {len(events)} events",
              flush=True)

    write_usage("FRONTEND" if which == "original" else "FRONTEND_renamed",
                {"phase": "frontend", "model": "ministral-14b-latest",
                             "calls": n_calls,
                             "wall_seconds": round(time.time() - t0, 1)})
    print(f"frontend done: {n_calls} resolver calls")


if __name__ == "__main__":
    main()
