"""Pair retriever arms R1-R4 for the relation-edges research.

For every non-descriptive event (from-side) rank the candidate parent/target
operations and communications (to-side). Recall-oriented: the metrics ask
whether the correct parent is inside top-k.

Arms (all name-blind: tool names are never rendered):
  R1  bge-base-en-v1.5 embedding cosine (sentence context of the from-event
      vs sentence context + rendered tool description of the to-event)
  R2  bge-reranker-base cross-encoder score (same inputs, pair scoring)
  R3  structural proximity from stanza UD parse (same sentence / same clause /
      subordination link / token distance / sentence distance), fixed weights
  R4  hybrid: 0.40*R1 + 0.25*R2 + 0.20*R3 + 0.15*role-compatibility
      (weights and the compatibility matrix fixed BEFORE any results)

Run:  REL_SUITE=original python3 rel_run_retriever.py
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from rel_common import (load_suite, out_dir, render_tool, sentences,
                        sentence_of, tools_by_name, norm_minmax, suffix_for,
                        write_usage)

ROLE_COMPAT = {
    ("PRECONDITION_CHECK", "OPERATION_EFFECT"): 1.0,
    ("STATE_OBSERVATION", "OPERATION_EFFECT"): 1.0,
    ("OPERATION_EFFECT", "OPERATION_EFFECT"): 0.7,
    ("OPERATION_EFFECT", "COMMUNICATION"): 0.9,
    ("PRECONDITION_CHECK", "COMMUNICATION"): 0.3,
    ("STATE_OBSERVATION", "COMMUNICATION"): 0.3,
    ("COMMUNICATION", "OPERATION_EFFECT"): 0.2,
    ("COMMUNICATION", "COMMUNICATION"): 0.2,
    # nested chains: a check/state can itself be gated by an earlier action
    ("OPERATION_EFFECT", "PRECONDITION_CHECK"): 0.6,
    ("PRECONDITION_CHECK", "PRECONDITION_CHECK"): 0.5,
    ("STATE_OBSERVATION", "PRECONDITION_CHECK"): 0.4,
    ("COMMUNICATION", "PRECONDITION_CHECK"): 0.2,
    ("OPERATION_EFFECT", "STATE_OBSERVATION"): 0.4,
    ("PRECONDITION_CHECK", "STATE_OBSERVATION"): 0.4,
    ("STATE_OBSERVATION", "STATE_OBSERVATION"): 0.3,
    ("COMMUNICATION", "STATE_OBSERVATION"): 0.2,
}

# R3 fixed weights (a priori)
W = {"same_sentence": 0.40, "same_clause": 0.20, "subordinate": 0.20,
     "near_tokens": 0.10, "sentence_decay": 0.10}


def structural_features(parsed, from_ev, to_ev):
    """Stanza-based proximity features for one ordered pair."""
    spans_meta = parsed["spans_meta"]
    a, b = spans_meta.get(from_ev["source_span"]), spans_meta.get(to_ev["source_span"])
    if a is None or b is None:
        return {"same_sentence": 0, "same_clause": 0, "subordinate": 0,
                "token_distance": 999, "sentence_distance": 9}
    same_sentence = int(a["sentence"] == b["sentence"])
    same_clause = int(a["root"] == b["root"] and same_sentence)
    subordinate = 0
    if same_sentence:
        # a's clause root is a descendant of b's clause root, or vice versa
        if a["root"] != b["root"]:
            subordinate = int(a["root"] in b["subtree"] or b["root"] in a["subtree"])
    tok_dist = abs(a["first_token"] - b["first_token"])
    sent_dist = abs(a["sentence"] - b["sentence"])
    return {"same_sentence": same_sentence, "same_clause": same_clause,
            "subordinate": subordinate, "token_distance": tok_dist,
            "sentence_distance": sent_dist}


def structural_score(feat):
    return (W["same_sentence"] * feat["same_sentence"]
            + W["same_clause"] * feat["same_clause"]
            + W["subordinate"] * feat["subordinate"]
            + W["near_tokens"] * (1 if feat["token_distance"] < 40 else 0)
            + W["sentence_decay"] * math.exp(-feat["sentence_distance"] / 2.0))


def parse_case(nlp, case):
    """Locate each event span in the stanza parse; record sentence id, clause
    root id, subtree token ids, first token id."""
    doc = nlp(case["policy"])
    spans_meta = {}
    for ev in case["events"]:
        span = ev["source_span"]
        idx = case["policy"].find(span)
        if idx < 0:
            continue
        end = idx + len(span)
        sent_i, tok_first, tok_last, root_id, subtree = None, None, None, None, set()
        for si, sent in enumerate(doc.sentences):
            toks = sent.tokens
            if not toks:
                continue
            c0, c1 = toks[0].start_char, toks[-1].end_char
            if c0 <= idx and end <= c1:
                sent_i = si
                for t in toks:
                    if t.start_char < end and t.end_char > idx:
                        tok_first = tok_first if tok_first is not None else t.id[0]
                        tok_last = t.id[0]
                # clause root: walk up from the first token of the span
                wid = tok_first
                words = {w.id: w for w in sent.words}
                seen = set()
                while wid in words and words[wid].head != 0 and wid not in seen:
                    seen.add(wid)
                    wid = words[wid].head
                root_id = wid
                # subtree of the clause root
                stack, subtree = [root_id], {root_id}
                while stack:
                    cur = stack.pop()
                    for w in sent.words:
                        if w.head == cur and w.id not in subtree:
                            subtree.add(w.id)
                            stack.append(w.id)
                break
        if sent_i is not None:
            spans_meta[span] = {"sentence": sent_i, "root": root_id,
                                "subtree": subtree, "first_token": tok_first,
                                "last_token": tok_last}
    return {"doc": doc, "spans_meta": spans_meta}


def main():
    which = os.environ.get("REL_SUITE", "original")
    suite = load_suite(which)
    arm = os.environ.get("REL_ARM_DIR", "R_retriever")

    import numpy as np
    import torch
    from sentence_transformers import SentenceTransformer, CrossEncoder
    import stanza

    emb = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                              cache_folder="/workspace/guardian/hf_cache")
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)

    t0 = time.time()
    outdir = out_dir(arm + suffix_for(which))
    n_pairs = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        policy = case["policy"]
        by_name = tools_by_name(case)
        events = case["events"]
        to_side = [e for e in events if e["role"] != "OTHER"]
        from_side = [e for e in events if e["role"] != "OTHER"]

        parsed = parse_case(nlp, case)

        rows = []
        # --- R1 embeddings (one query per from-event, one doc per to-event)
        q_texts, q_owner = [], []
        for fe in from_side:
            sent, _ = sentence_of(fe["source_span"], policy)
            q_texts.append(f"{fe['source_span']}. {sent or ''}")
            q_owner.append(fe["source_span"])
        d_texts, d_owner = [], []
        for te in to_side:
            sent, _ = sentence_of(te["source_span"], policy)
            tdesc = " ".join(render_tool(by_name[n]) for n in te.get("governed_tools", [])
                             if n in by_name)
            d_texts.append(f"{te['source_span']}. {sent or ''} {tdesc}".strip())
            d_owner.append(te["source_span"])
        q_emb = emb.encode(q_texts, convert_to_numpy=True, normalize_embeddings=True,
                           batch_size=32) if q_texts else []
        d_emb = emb.encode(d_texts, convert_to_numpy=True, normalize_embeddings=True,
                           batch_size=32) if d_texts else []

        # --- R2 cross-encoder pairs
        ce_pairs = []
        ce_index = []
        for i, fe in enumerate(from_side):
            fsent, _ = sentence_of(fe["source_span"], policy)
            for j, te in enumerate(to_side):
                if te["source_span"] == fe["source_span"]:
                    continue
                tsent, _ = sentence_of(te["source_span"], policy)
                tdesc = " ".join(render_tool(by_name[n]) for n in te.get("governed_tools", [])
                                 if n in by_name)
                ce_pairs.append((fsent or fe["source_span"],
                                 f"{te['source_span']}. {tsent or ''} {tdesc}".strip()))
                ce_index.append((i, j))
        ce_scores = rer.predict(ce_pairs, batch_size=16,
                                convert_to_numpy=True) if ce_pairs else []
        ce_pos = {ij: k for k, ij in enumerate(ce_index)}

        for i, fe in enumerate(from_side):
            cand = []
            for j, te in enumerate(to_side):
                if te["source_span"] == fe["source_span"]:
                    continue
                r1 = float(np.dot(q_emb[i], d_emb[j])) if len(q_emb) else 0.0
                k = ce_pos.get((i, j))
                r2 = float(ce_scores[k]) if k is not None else 0.0
                feat = structural_features(parsed, fe, te)
                r3 = structural_score(feat)
                compat = ROLE_COMPAT.get((fe["role"], te["role"]), 0.2)
                cand.append({"to_span": te["source_span"], "to_role": te["role"],
                             "r1": round(r1, 6), "r2": round(r2, 6),
                             "r3": round(r3, 6), "compat": compat,
                             "r3_features": feat})
            # per-query normalisation + hybrid combination
            r1n = norm_minmax([c["r1"] for c in cand])
            r2n = norm_minmax([c["r2"] for c in cand])
            r3n = norm_minmax([c["r3"] for c in cand])
            for k, c in enumerate(cand):
                c["r1_norm"] = round(r1n[k], 6)
                c["r2_norm"] = round(r2n[k], 6)
                c["r3_norm"] = round(r3n[k], 6)
                c["r4"] = round(0.40 * r1n[k] + 0.25 * r2n[k] + 0.20 * r3n[k]
                                + 0.15 * c["compat"], 6)
            for key in ("r1", "r2", "r3", "r4"):
                cand.sort(key=lambda c: -c[key])
                for rank, c in enumerate(cand, 1):
                    c[f"rank_{key}"] = rank
            rows.append({"from_span": fe["source_span"], "from_role": fe["role"],
                         "candidates": cand})
            n_pairs += len(cand)

        path.write_text(json.dumps({
            "case_id": case["case_id"],
            "queries": rows,
        }, ensure_ascii=False, indent=1), encoding="utf-8")

    write_usage(arm + suffix_for(which), {
        "wall_seconds": round(time.time() - t0, 1),
        "suite": which, "pairs": n_pairs,
        "models": ["BAAI/bge-base-en-v1.5", "BAAI/bge-reranker-base",
                   "stanza en depparse"],
    })
    print(f"R1-R4 done {which}: {n_pairs} pairs")


if __name__ == "__main__":
    main()
