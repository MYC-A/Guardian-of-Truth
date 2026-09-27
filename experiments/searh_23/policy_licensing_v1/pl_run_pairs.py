"""Local pair-signal arm: computes, for EVERY unordered pair of the frozen
pair universe, the signals reused by all later arms:

  ce_both_*   bge-reranker score on (A context sentence, B span+sentence+tools)
  ce_policy_* same without tool descriptions        (IDEA F ablation)
  ce_tool_*   tool-semantics only (no policy text)  (IDEA F ablation)
  emb_sim     bge-base cosine over span+sentence+tools
  tool_sim    bge-base cosine over tool descriptions only
  structural  same-sentence / sentence distance / token distance (stanza)

Also builds per-event candidate rankings (hybrid r4 with the a-priori
weights frozen from relation_edges_v1: 0.40 emb + 0.25 ce + 0.20 struct +
0.15 role-compat) for the LISTWISE arm candidates.

CE scores are computed in BOTH directions (ab and ba); detection uses
max(ab, ba) since detection is a symmetric decision.

Run: PL_SUITE=original python3 pl_run_pairs.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, out_dir, write_usage, render_tool, tools_by_name, ev_by_eid, sentence_of_span

ROLE_COMPAT = {
    ("PRECONDITION_CHECK", "OPERATION_EFFECT"): 1.0,
    ("PRECONDITION_CHECK", "COMMUNICATION"): 0.6,
    ("STATE_OBSERVATION", "OPERATION_EFFECT"): 1.0,
    ("STATE_OBSERVATION", "COMMUNICATION"): 0.6,
    ("OPERATION_EFFECT", "OPERATION_EFFECT"): 0.7,
    ("OPERATION_EFFECT", "COMMUNICATION"): 0.6,
    ("COMMUNICATION", "COMMUNICATION"): 0.5,
    ("COMMUNICATION", "OPERATION_EFFECT"): 0.6,
}
DEFAULT_COMPAT = 0.2


def norm_minmax(xs):
    if not xs:
        return []
    lo, hi = min(xs), max(xs)
    if hi - lo < 1e-9:
        return [0.0 for _ in xs]
    return [(x - lo) / (hi - lo) for x in xs]


def main():
    which = os.environ.get("PL_SUITE", "original")
    suite = load_suite(which)
    arm = os.environ.get("PL_ARM_DIR", "PAIR_signals")

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer, CrossEncoder
    import stanza

    emb = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                              cache_folder="/workspace/guardian/hf_cache")
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)

    t0 = time.time()
    outdir = out_dir(arm + ("_renamed" if which == "renamed" else ""))
    n_pairs = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            n_pairs += sum(len(c["pair_universe"]) for c in [case])
            continue
        policy = case["policy"]
        by_name = tools_by_name(case)
        events = case["events"]
        evmap = ev_by_eid(case)

        # ---- stanza parse for structural features -----------------------
        doc = nlp(policy)
        span_meta = {}
        for ev in events:
            idx = ev["span_start"]
            end = ev["span_end"]
            for si, sent in enumerate(doc.sentences):
                toks = sent.tokens
                if not toks:
                    continue
                c0, c1 = toks[0].start_char, toks[-1].end_char
                if c0 <= idx and end <= c1:
                    tok_first = next(t.id[0] for t in toks
                                    if t.start_char < end and t.end_char > idx)
                    span_meta[ev["eid"]] = {"sentence": si, "tok_first": tok_first}
                    break

        def struct(a, b):
            ma, mb = span_meta.get(a["eid"]), span_meta.get(b["eid"])
            if not ma or not mb:
                return {"same_sentence": 0, "sentence_distance": 9, "token_distance": 999}
            return {"same_sentence": int(ma["sentence"] == mb["sentence"]),
                    "sentence_distance": abs(ma["sentence"] - mb["sentence"]),
                    "token_distance": abs(ma["tok_first"] - mb["tok_first"])}

        # ---- text renderings --------------------------------------------
        def ctx(ev):
            s, _ = sentence_of_span(policy, ev["span_start"])
            return s or ev["source_span"]

        def tools_of(ev):
            return " ".join(render_tool(by_name[n]) for n in ev.get("governed_tools", [])
                            if n in by_name)

        ev_ctx = {e["eid"]: ctx(e) for e in events}
        ev_tools = {e["eid"]: tools_of(e) for e in events}

        # embeddings: span + sentence + tools (retriever view)
        emb_texts = [f"{e['source_span']}. {ev_ctx[e['eid']]} {ev_tools[e['eid']]}".strip()
                     for e in events]
        emb_vecs = emb.encode(emb_texts, convert_to_numpy=True,
                               normalize_embeddings=True, batch_size=32)
        tool_texts = [ev_tools[e["eid"]] or "no tool" for e in events]
        tool_vecs = emb.encode(tool_texts, convert_to_numpy=True,
                               normalize_embeddings=True, batch_size=32)
        ev_idx = {e["eid"]: i for i, e in enumerate(events)}

        # ---- CE pairs (three context variants, both directions) ---------
        ce_jobs = []  # (variant, a_eid, b_eid)
        for i, a in enumerate(events):
            for b in events[i + 1:]:
                for variant in ("both", "policy", "tool"):
                    ce_jobs.append((variant, a["eid"], b["eid"]))
                    ce_jobs.append((variant, b["eid"], a["eid"]))

        def ce_texts(variant, a, b):
            ae, be = a["eid"], b["eid"]
            if variant == "both":
                return (ev_ctx[ae], f"{b['source_span']}. {ev_ctx[be]} {ev_tools[be]}".strip())
            if variant == "policy":
                return (ev_ctx[ae], f"{b['source_span']}. {ev_ctx[be]}".strip())
            # tool-only: no policy sentence at all
            return (f"{a['source_span']}. {ev_tools[ae]}".strip(),
                    f"{b['source_span']}. {ev_tools[be]}".strip())

        ce_in = []
        ce_keys = []
        for variant, ae, be in ce_jobs:
            ta, tb = ce_texts(variant, evmap[ae], evmap[be])
            ce_in.append((ta, tb))
            ce_keys.append((variant, ae, be))
        ce_scores = rer.predict(ce_in, batch_size=32, convert_to_numpy=True) if ce_in else []
        ce_map = {k: float(v) for k, v in zip(ce_keys, ce_scores)}

        # ---- assemble pair records --------------------------------------
        pairs = []
        for pu in case["pair_universe"]:
            a, b = evmap[pu["a_eid"]], evmap[pu["b_eid"]]
            ae, be = a["eid"], b["eid"]
            rec = {
                "a_eid": ae, "b_eid": be,
                "a_span": pu["a_span"], "b_span": pu["b_span"],
                "a_role": a["role"], "b_role": b["role"],
                "gold": pu["gold"], "hard": pu["hard"],
                "ce_both_ab": round(ce_map[("both", ae, be)], 6),
                "ce_both_ba": round(ce_map[("both", be, ae)], 6),
                "ce_policy_ab": round(ce_map[("policy", ae, be)], 6),
                "ce_policy_ba": round(ce_map[("policy", be, ae)], 6),
                "ce_tool_ab": round(ce_map[("tool", ae, be)], 6),
                "ce_tool_ba": round(ce_map[("tool", be, ae)], 6),
                "emb_sim": round(float(emb_vecs[ev_idx[ae]] @ emb_vecs[ev_idx[be]]), 6),
                "tool_sim": round(float(tool_vecs[ev_idx[ae]] @ tool_vecs[ev_idx[be]]), 6),
                "struct": struct(a, b),
            }
            pairs.append(rec)
            n_pairs += 1

        # ---- per-event candidate rankings (hybrid r4) --------------------
        rankings = {}
        for e in events:
            cands = []
            for other in events:
                if other["eid"] == e["eid"]:
                    continue
                r1 = float(emb_vecs[ev_idx[e["eid"]]] @ emb_vecs[ev_idx[other["eid"]]])
                r2 = max(ce_map[("both", e["eid"], other["eid"])],
                         ce_map[("both", other["eid"], e["eid"])])
                st = struct(e, other)
                r3 = (int(st["same_sentence"])
                      + (1 if st["token_distance"] < 40 else 0)
                      + (2.0 * pow(2.718281828, -st["sentence_distance"] / 2.0)))
                compat = ROLE_COMPAT.get((e["role"], other["role"]),
                                         ROLE_COMPAT.get((other["role"], e["role"]),
                                                         DEFAULT_COMPAT))
                cands.append({"eid": other["eid"], "r1": r1, "r2": r2,
                              "r3": r3, "compat": compat})
            r1n = norm_minmax([c["r1"] for c in cands])
            r2n = norm_minmax([c["r2"] for c in cands])
            r3n = norm_minmax([c["r3"] for c in cands])
            for k, c in enumerate(cands):
                c["r4"] = round(0.40 * r1n[k] + 0.25 * r2n[k] + 0.20 * r3n[k]
                                + 0.15 * c["compat"], 6)
            cands.sort(key=lambda c: -c["r4"])
            rankings[e["eid"]] = cands

        path.write_text(json.dumps({
            "case_id": case["case_id"],
            "split": case["split"],
            "pairs": pairs,
            "rankings": rankings,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    write_usage(arm + ("_renamed" if which == "renamed" else ""), {
        "wall_seconds": round(time.time() - t0, 1),
        "suite": which, "pairs": n_pairs,
        "models": ["BAAI/bge-base-en-v1.5", "BAAI/bge-reranker-base", "stanza en"],
    })
    print(f"pair signals done {which}: {n_pairs} pairs")


if __name__ == "__main__":
    main()
