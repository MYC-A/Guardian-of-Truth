"""EVENT_CANON_v1 - Track B: canonicalization over PREDICTED mentions.

Pipeline: predicted frontend events -> pair signals (local: lexical /
embedding / CE / UD-signature; LLM: narrow pair judge with exact spans +
local context, policy-only or with tool descriptions) -> clustering
(config frozen on dev from Track A) -> canonical nodes with majority-vote
attributes (role / governed_tools from members - no gold leak).

Track B metrics vs the gold alignment: merge precision / recall, false-merge
and missed-merge rates (pairs of predicted events whose alignment labels say
same canonical event should be merged; pairs with different labels or
NON_EVENT members must not be merged).

Usage: python3 ec_track_b.py [pair_arm] [cluster_method] [context_mode]
  pair_arm in {F_pol, F_tool, lex, emb, ce, ud}   (default F_pol)
  cluster_method in {cc, veto, al, cl, corr}       (default veto)
  context_mode: dev (F_tool ablation on dev only) or full
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path
from itertools import combinations

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import (Mistral, load_suite, out_dir, write_usage,
                       local_context, render_tool, tools_by_name, MODELS)
from ec_feats import (content_tokens, overlap_coeff, ud_signature,
                      lemma_family_match, candidate_pairs)
from ec_run_llm import SYSTEM_F
from ec_cluster import build_clusters, pair_score

CE_BAND = 0.35  # frozen from policy_licensing_v1 (real track)


def predicted_mentions(case, frontend_dir):
    data = json.loads((frontend_dir / f"{case['case_id']}.json")
                      .read_text(encoding="utf-8"))["events"]
    out = []
    for i, p in enumerate(data):
        out.append({"mid": f"P{i:02d}", "span": p["span"],
                    "start": p["span_start"], "end": p["span_end"],
                    "sentence_index": _sent_idx(case["policy"], p["span_start"]),
                    "role": p["role"], "governed_tools": p.get("governed_tools", []),
                    "is_np": p.get("is_np", False)})
    return out


def _sent_idx(policy, start):
    import re
    pos, k = 0, 0
    for s in re.split(r"(?<=[.!?])\s+", policy):
        if pos <= start < pos + len(s):
            return k
        pos += len(s) + 1
        k += 1
    return -1


def pair_records_local(case, mentions, emb=None, ce_scores=None, sigs=None):
    """Local pair signals over ALL predicted-mention pairs (cheap)."""
    recs = []
    for i in range(len(mentions)):
        for j in range(i + 1, len(mentions)):
            a, b = mentions[i], mentions[j]
            r = {"a": a["mid"], "b": b["mid"]}
            ta = set(content_tokens(a["span"]))
            tb = set(content_tokens(b["span"]))
            r["lex_overlap"] = round(overlap_coeff(ta, tb), 4)
            if emb is not None:
                r["emb"] = round(float(emb[i] @ emb[j]), 4)
            if ce_scores is not None:
                r["ce"] = round(float(ce_scores.get((i, j), 0.0)), 4)
            if sigs is not None:
                from ec_feats import signature_compare
                lab, why = signature_compare(sigs[a["mid"]], sigs[b["mid"]])
                r["ud_label"] = lab
                r["ud_reason"] = why
            recs.append(r)
    return recs


def run_f_judge(client, case, mentions, cands, with_tools=False):
    policy = case["policy"]
    by_name = tools_by_name(case)
    out = []
    for a_mid, b_mid in cands:
        a = next(m for m in mentions if m["mid"] == a_mid)
        b = next(m for m in mentions if m["mid"] == b_mid)
        payload = {
            "mention_a": a["span"],
            "context_a": local_context(policy, a["start"], window=1),
            "mention_b": b["span"],
            "context_b": local_context(policy, b["start"], window=1),
        }
        if with_tools:
            for key, m in (("tool_a", a), ("tool_b", b)):
                payload[key] = " ".join(
                    render_tool(by_name[n]) for n in m["governed_tools"]
                    if n in by_name) or "none"
        rec = client.ask(SYSTEM_F, json.dumps(payload, ensure_ascii=False),
                         max_tokens=220)
        ans, err = Mistral.parse_json(rec["raw"])
        label = (ans or {}).get("label")
        if isinstance(label, str):
            label = label.strip().upper()
        if label not in ("SAME_EVENT", "RELATED_BUT_DIFFERENT",
                         "DIFFERENT", "UNKNOWN"):
            label = "UNKNOWN"
        out.append({"a": a_mid, "b": b_mid, "label": label,
                    "reason": (ans or {}).get("reason", "")[:200]})
    return out


def cluster_to_nodes(case, mentions, assign):
    nodes = []
    by_cluster = {}
    for m in mentions:
        by_cluster.setdefault(assign.get(m["mid"], f"s_{m['mid']}"), []).append(m)
    for k, (cl, mem) in enumerate(sorted(by_cluster.items(),
                                         key=lambda kv: min(m["start"] for m in kv[1]))):
        roles = [m["role"] for m in mem if m["role"] != "UNKNOWN"]
        role = max(set(roles), key=roles.count) if roles else "UNKNOWN"
        tools = [t for m in mem for t in m["governed_tools"]]
        tool = max(set(tools), key=tools.count) if tools else None
        span = min(mem, key=lambda m: m["start"])["span"]
        nodes.append({"node_id": f"N{k:02d}", "cluster": cl,
                      "members": [m["mid"] for m in mem],
                      "span": span, "role": role,
                      "governed_tools": [tool] if tool else [],
                      "start": min(m["start"] for m in mem)})
    return nodes


def main():
    import os
    pair_arm = sys.argv[1] if len(sys.argv) > 1 else "F_pol"
    method = sys.argv[2] if len(sys.argv) > 2 else "veto"
    ctx = sys.argv[3] if len(sys.argv) > 3 else "full"
    from sentence_transformers import SentenceTransformer, CrossEncoder
    import stanza
    import numpy as np

    which = os.environ.get("EC_SUITE", "original")
    frontend_dir = out_dir("FRONTEND" if which == "original" else "FRONTEND_renamed")
    enc = SentenceTransformer("BAAI/bge-base-en-v1.5", device="cuda",
                              cache_folder="/workspace/guardian/hf_cache")
    ce = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                      cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    client = Mistral(model=MODELS["mistral"], cache_dir=out_dir("_cache"))

    suite = load_suite(which)
    if ctx == "dev":
        suite = [c for c in suite if c["split"] == "dev"]
    t0 = time.time()
    n_calls = 0
    arm_dir = out_dir(f"TRACKB_{pair_arm}_{method}" + ("_dev" if ctx == "dev" else "")
                      + ("" if which == "original" else "_renamed"))
    for case in suite:
        cid_ = case["case_id"]
        outpath = arm_dir / f"{cid_}.json"
        if outpath.is_file():
            continue
        mentions = predicted_mentions(case, frontend_dir)
        policy = case["policy"]
        # local signals
        spans = [m["span"] for m in mentions]
        ctxs = [f"{m['span']} || " + (local_context(policy, m["start"]) or "")
                for m in mentions]
        V = enc.encode(ctxs, batch_size=32, normalize_embeddings=True,
                       show_progress_bar=False)
        emb = {m["mid"]: V[i] for i, m in enumerate(mentions)}
        ce_inputs, ce_keys = [], []
        for i in range(len(mentions)):
            for j in range(i + 1, len(mentions)):
                sa = local_context(policy, mentions[i]["start"])
                sb = local_context(policy, mentions[j]["start"])
                ce_inputs.append((
                    f'Do these two policy text mentions refer to the same single event? Mention 1: "{spans[i]}". Mention 2: "{spans[j]}".',
                    f'Mention 1 appears in: {sa} Mention 2 appears in: {sb}'))
                ce_keys.append((i, j))
        ce_scores = {}
        if ce_inputs:
            raw = ce.predict(ce_inputs, batch_size=32, convert_to_numpy=True)
            ce_scores = {k: float(v) for k, v in zip(ce_keys, raw)}
        doc = nlp(policy)
        sigs = {m["mid"]: ud_signature(policy, doc, m["start"], m["end"])
                for m in mentions}
        local_recs = pair_records_local(case, mentions, emb=V,
                                        ce_scores=ce_scores, sigs=sigs)
        # candidate pairs (blocking)
        cands = candidate_pairs(mentions, embeddings=emb, sim_topk=3,
                                sent_window=1)
        # pair arm
        if pair_arm in ("F_pol", "F_tool"):
            f_recs = run_f_judge(client, case, mentions, cands,
                                 with_tools=(pair_arm == "F_tool"))
            n_calls += len(f_recs)
            pair_src = f_recs
        elif pair_arm == "lex":
            pair_src = [{"a": r["a"], "b": r["b"],
                         "label": "SAME_EVENT" if r["lex_overlap"] >= 0.5
                         else "DIFFERENT"} for r in local_recs]
        elif pair_arm == "emb":
            pair_src = [{"a": r["a"], "b": r["b"],
                         "label": "SAME_EVENT" if r.get("emb", 0) >= 0.93
                         else "DIFFERENT"} for r in local_recs]
        elif pair_arm == "ce":
            pair_src = [{"a": r["a"], "b": r["b"],
                         "label": "SAME_EVENT" if r.get("ce", 0) >= 0.0
                         else "DIFFERENT"} for r in local_recs]
        elif pair_arm == "ud":
            pair_src = [{"a": r["a"], "b": r["b"], "label": r["ud_label"]}
                        for r in local_recs]
        else:
            raise SystemExit(f"unknown arm {pair_arm}")
        # clustering
        assign = build_clusters(pair_src, method)
        nodes = cluster_to_nodes(case, mentions, assign)
        outpath.parent.mkdir(parents=True, exist_ok=True)
        outpath.write_text(json.dumps({
            "case_id": cid_, "mentions": mentions,
            "local_pairs": local_recs, "pair_src": pair_src,
            "candidates": [list(c) for c in cands],
            "assign": assign, "nodes": nodes,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{cid_}] {len(mentions)} mentions -> {len(nodes)} nodes "
              f"({pair_arm}+{method})", flush=True)
    write_usage(f"TRACKB_{pair_arm}_{method}", {
        "llm_calls": n_calls, "wall_seconds": round(time.time() - t0, 1)})
    print(f"TrackB done: {n_calls} LLM calls")


if __name__ == "__main__":
    main()
