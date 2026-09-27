"""Relation DETECTOR arms without LLM: cross-encoder thresholds and NLI.

Evaluated on the full ordered pair universe derived from relation_inputs
(to-side = OPERATION_EFFECT / COMMUNICATION events, from-side = all
non-descriptive events), so precision can be measured against the fixed
pair space.

Arms:
  DET-ce   bge-reranker-base pair relevance (reuses the R2 scores produced by
           rel_run_retriever.py) with FROZEN thresholds:
             score >= 0.50            -> RELATED
             0.35 <= score < 0.50     -> UNKNOWN
             score < 0.35             -> NOT_RELATED
  DET-nli  cross-encoder/nli-deberta-v3-base. Premise = both events with roles,
           tool semantics and context sentences; hypothesis set:
             H_pos: "Event A must happen before event B, or enables or
                     triggers event B."
             H_neg: "Event A and event B are unrelated in this policy."
           Decision rule (FROZEN):
             entail(H_pos) >= 0.50        -> RELATED
             0.35 <= entail(H_pos) < 0.50 -> UNKNOWN
             otherwise                    -> NOT_RELATED
           entail(H_neg) is recorded for analysis but not used in the rule.

Run:  REL_SUITE=original python3 rel_run_detector.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rel_common import (load_suite, out_dir, render_tool, sentence_of,
                        tools_by_name, pair_universe, suffix_for,
                        write_usage)

CE_THRESH_RELATED = 0.50
CE_THRESH_UNKNOWN = 0.35
NLI_THRESH_RELATED = 0.50
NLI_THRESH_UNKNOWN = 0.35


def pair_context(case, a, b):
    policy = case["policy"]
    by_name = tools_by_name(case)
    a_sent, _ = sentence_of(a["source_span"], policy)
    b_sent, _ = sentence_of(b["source_span"], policy)
    a_tools = " ".join(render_tool(by_name[n]) for n in a.get("governed_tools", [])
                       if n in by_name)
    b_tools = " ".join(render_tool(by_name[n]) for n in b.get("governed_tools", [])
                       if n in by_name)
    excerpt = " ".join(s for s in (a_sent, b_sent) if s).strip()
    return {
        "premise": (f'Event A: "{a["source_span"]}" (role: {a["role"]}). '
                    f'Event B: "{b["source_span"]}" (role: {b["role"]}). '
                    f'Event B tool semantics: {b_tools or "none given"}. '
                    f'Policy excerpt: "{excerpt}"'),
        "hypothesis_pos": "Event A must happen before event B, or enables or triggers event B.",
        "hypothesis_neg": "Event A and event B are unrelated in this policy.",
    }


def ce_decision(score):
    if score >= CE_THRESH_RELATED:
        return "RELATED"
    if score >= CE_THRESH_UNKNOWN:
        return "UNKNOWN"
    return "NOT_RELATED"


def nli_decision(entail_pos):
    if entail_pos >= NLI_THRESH_RELATED:
        return "RELATED"
    if entail_pos >= NLI_THRESH_UNKNOWN:
        return "UNKNOWN"
    return "NOT_RELATED"


def main():
    which = os.environ.get("REL_SUITE", "original")
    suite = load_suite(which)
    arm = os.environ.get("REL_ARM_DIR", "DET_local")

    retriever_dir = Path(os.environ.get(
        "REL_OUTPUTS", str(Path(__file__).parent / "outputs"))) / (
        "R_retriever" + suffix_for(which))

    import numpy as np
    import torch
    os.environ.setdefault("HF_HOME", "/workspace/guardian/hf_cache")
    from transformers import AutoModelForSequenceClassification, AutoTokenizer

    tok = AutoTokenizer.from_pretrained("cross-encoder/nli-deberta-v3-base")
    nli = AutoModelForSequenceClassification.from_pretrained(
        "cross-encoder/nli-deberta-v3-base").to("cuda").eval()
    label_map = {v: k for k, v in (nli.config.label2id or {"contradiction": 0,
                                                           "entailment": 1,
                                                           "neutral": 2}).items()}

    def entail(premise, hypothesis):
        with torch.no_grad():
            inp = tok(premise, hypothesis, return_tensors="pt", truncation=True,
                      max_length=512).to("cuda")
            logits = nli(**inp).logits[0].softmax(-1).cpu().numpy()
        return {label_map[i]: float(logits[i]) for i in range(len(logits))}

    t0 = time.time()
    outdir = out_dir(arm + suffix_for(which))
    n_pairs = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        # cross-encoder scores from the retriever arm (same suite)
        ret = json.loads((retriever_dir / f"{case['case_id']}.json").read_text(
            encoding="utf-8"))
        ce_by_pair = {}
        for q in ret["queries"]:
            for c in q["candidates"]:
                ce_by_pair[(q["from_span"], c["to_span"])] = c["r2"]

        rows = []
        for a, b in pair_universe(case["events"]):
            ctx = pair_context(case, a, b)
            pos = entail(ctx["premise"], ctx["hypothesis_pos"])
            neg = entail(ctx["premise"], ctx["hypothesis_neg"])
            ce = ce_by_pair.get((a["source_span"], b["source_span"]))
            rows.append({
                "from_span": a["source_span"], "to_span": b["source_span"],
                "from_role": a["role"], "to_role": b["role"],
                "ce_score": ce,
                "ce_decision": ce_decision(ce) if ce is not None else "UNKNOWN",
                "nli_entail_pos": round(pos.get("entailment", 0.0), 6),
                "nli_neutral_pos": round(pos.get("neutral", 0.0), 6),
                "nli_contradiction_pos": round(pos.get("contradiction", 0.0), 6),
                "nli_entail_neg": round(neg.get("entailment", 0.0), 6),
                "nli_decision": nli_decision(pos.get("entailment", 0.0)),
            })
            n_pairs += 1

        path.write_text(json.dumps({"case_id": case["case_id"], "pairs": rows},
                                   ensure_ascii=False, indent=1), encoding="utf-8")

    write_usage(arm + suffix_for(which), {
        "wall_seconds": round(time.time() - t0, 1),
        "suite": which, "pairs": n_pairs,
        "models": ["BAAI/bge-reranker-base (reused R2)",
                   "cross-encoder/nli-deberta-v3-base"],
        "thresholds": {"ce": [CE_THRESH_RELATED, CE_THRESH_UNKNOWN],
                       "nli": [NLI_THRESH_RELATED, NLI_THRESH_UNKNOWN]},
    })
    print(f"DET-ce/DET-nli done {which}: {n_pairs} pairs")


if __name__ == "__main__":
    main()
