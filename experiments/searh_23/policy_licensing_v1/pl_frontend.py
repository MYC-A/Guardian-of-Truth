"""REAL FRONTEND TRACK - event discovery without gold spans.

Port of the best previous frontend (operation_check arm H2) onto the new
frozen dataset, feeding the relation stack with PREDICTED events:

  1. stanza UD parse -> verb-headed clause candidates + NP argument
     candidates (structural, closed-class function words only, no domain
     vocab);
  2. tool grounding with bge-reranker over (span, tool description) pairs -
     name-blind; top-3 tools per candidate;
  3. ONE narrow LLM role question per candidate (the H2 resolver);
     structural override kept from frozen H: UD mark in {if, unless, until,
     once} upgrades OPERATION_EFFECT answers to PRECONDITION_CHECK.

Output: outputs/FRONTEND/<case_id>.json with predicted events
(span/role/governed_tools) - the input of the real-track relation run.

Run: python3 pl_frontend.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import Mistral, load_suite, out_dir, write_usage, render_tool

SUBORDINATORS = {"if", "unless", "until", "once", "when", "whenever",
                 "before", "after"}
COND_MARKS = {"if", "unless", "until", "once"}
DEONTIC = {"must", "shall", "may", "might", "can", "could", "should",
           "will", "would"}
CLAUSE_DEPS = {"root", "advcl", "acl", "ccomp", "xcomp", "conj", "parataxis"}

RESOLVER_SYSTEM = """You see one candidate span from a policy and the three most similar tools from the catalog. Decide what kind of mention the span is by judging the tools from their description and schema (never by name):
- REALIZES_OPERATION: executing the tool performs the action in the span
- CHECKS_PRECONDITION: executing the tool verifies whether the state in the span holds
- OBSERVES_STATE: executing the tool reads or observes the state in the span
- COMMUNICATES: executing the tool sends a communication about the span
- UNRELATED: no tool matches the span
- UNKNOWN: cannot decide
Answer with JSON only: {"label": "..."}."""

LABEL_TO_ROLE = {
    "REALIZES_OPERATION": "OPERATION_EFFECT",
    "CHECKS_PRECONDITION": "PRECONDITION_CHECK",
    "OBSERVES_STATE": "STATE_OBSERVATION",
    "COMMUNICATES": "COMMUNICATION",
}


def clause_span(policy, sentence, head_id):
    words = [w for w in sentence.words]

    def subtree_ids(tid, seen=None):
        if seen is None:
            seen = set()
        if tid in seen:
            return seen
        seen.add(tid)
        for w in words:
            if w.head == tid and w.id not in seen:
                subtree_ids(w.id, seen)
        return seen

    ids = subtree_ids(head_id)
    for w in words:
        if w.head == head_id and w.deprel.split(":")[0] in {"advcl", "acl"}:
            for sid in list(subtree_ids(w.id)):
                ids.discard(sid)
    ids = sorted(ids)
    if not ids:
        return None, None, ""
    start_char = words[ids[0] - 1].start_char
    end_char = words[ids[-1] - 1].end_char
    while ids:
        w = words[ids[0] - 1]
        if w.upos in {"PUNCT", "CCONJ"} and w.id != head_id:
            ids = ids[1:]
            if not ids:
                return None, None, ""
            start_char = words[ids[0] - 1].start_char
        else:
            break
    while ids:
        w = words[ids[-1] - 1]
        if w.upos in {"PUNCT", "CCONJ"} and w.id != head_id:
            ids = ids[:-1]
            if not ids:
                return None, None, ""
            end_char = words[ids[-1] - 1].end_char
        else:
            break
    return start_char, end_char, policy[start_char:end_char]


def np_candidates(policy, sentence, words, verb):
    out = []
    by_id = {w.id: w for w in words}

    def subtree_tokens(tid, seen=None):
        if seen is None:
            seen = set()
        if tid in seen:
            return []
        seen.add(tid)
        result = [by_id[tid]]
        for w in words:
            if w.head == tid and w.id not in seen:
                result.extend(subtree_tokens(w.id, seen))
        return result

    for child in words:
        if child.head != verb.id:
            continue
        rel = child.deprel.split(":")[0]
        if rel not in {"obj", "iobj", "obl", "nsubj"}:
            continue
        toks = subtree_tokens(child.id)
        if any(t.upos in {"VERB", "AUX", "SCONJ"} and t.id != child.id for t in toks):
            continue
        if child.upos in {"PRON", "DET"} and len(toks) <= 1:
            continue
        conjs = [c for c in words if c.head == child.id and c.deprel == "conj"]
        members = [child] + [c for c in conjs
                             if not any(t.upos in {"VERB", "AUX"}
                                        for t in subtree_tokens(c.id))]
        for m in members:
            mtoks = subtree_tokens(m.id)
            if not mtoks:
                continue
            ids = sorted(t.id for t in mtoks)
            st = by_id[ids[0]].start_char
            en = by_id[ids[-1]].end_char
            while ids:
                wd = by_id[ids[0]]
                if wd.upos in {"PUNCT", "CCONJ", "DET", "ADP"} and wd.id != m.id:
                    ids = ids[1:]
                    if not ids:
                        break
                    st = by_id[ids[0]].start_char
                else:
                    break
            while ids:
                wd = by_id[ids[-1]]
                if wd.upos in {"PUNCT", "CCONJ"} and wd.id != m.id:
                    ids = ids[:-1]
                    if not ids:
                        break
                    en = by_id[ids[-1]].end_char
                else:
                    break
            if not ids:
                continue
            span = policy[st:en]
            if span.strip() and len(span.split()) >= 2:
                out.append({"span": span, "start": st, "end": en,
                            "np_of_verb": verb.lemma,
                            "dep_in_verb": rel, "is_np": True,
                            "role_hypothesis": "UNKNOWN"})
    return out


def analyse_case(nlp, case):
    policy = case["policy"]
    doc = nlp(policy)
    cands = []
    for s_idx, sentence in enumerate(doc.sentences):
        words = [w for w in sentence.words]
        for w in words:
            dep = w.deprel.split(":")[0]
            if dep not in CLAUSE_DEPS:
                continue
            has_cop = any(c.deprel == "cop" for c in words if c.head == w.id)
            if w.upos != "VERB" and not has_cop:
                continue
            marks = [c.lemma for c in words
                     if c.head == w.id and c.lemma in SUBORDINATORS and
                     c.deprel in {"mark", "case", "advmod"}]
            st, en, span = clause_span(policy, sentence, w.id)
            if st is None or not span.strip() or len(span.split()) < 2:
                continue
            cands.append({"span": span, "start": st, "end": en,
                          "dep": dep, "mark": marks[0] if marks else None,
                          "verb": w.lemma, "is_np": False})
            cands.extend(np_candidates(policy, sentence, words, w))
    # dedup by span, prefer non-NP
    seen = {}
    for c in cands:
        if c["span"] not in seen or not c.get("is_np"):
            if c["span"] not in seen:
                seen[c["span"]] = c
    return list(seen.values())


def main():
    suite = load_suite("original")
    import numpy as np
    import torch
    from sentence_transformers import CrossEncoder
    import stanza

    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda", max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    nlp = stanza.Pipeline("en", processors="tokenize,pos,lemma,depparse",
                          verbose=False, use_gpu=True)
    client = Mistral(model="ministral-14b-latest", cache_dir=out_dir("_cache"))

    outdir = out_dir("FRONTEND")
    t0 = time.time()
    n_calls = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        policy = case["policy"]
        cands = analyse_case(nlp, case)
        # grounding: rerank (span, tool description) over the whole catalog
        pairs, owners = [], []
        for i, c in enumerate(cands):
            for t in case["tools"]:
                pairs.append((c["span"], render_tool(t)))
                owners.append(i)
        scores = rer.predict(pairs, batch_size=32, convert_to_numpy=True) if pairs else []
        top3_by_cand = {}
        for i, s in zip(owners, scores):
            top3_by_cand.setdefault(i, []).append((float(s)))
        # rebuild per-candidate ranking with tool names
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
            role = LABEL_TO_ROLE.get(label, "UNKNOWN") if isinstance(label, str) else "UNKNOWN"
            # structural override kept from frozen H
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
        print(f"[{case['case_id']}] {len(cands)} candidates -> {len(events)} events")

    write_usage("FRONTEND", {"phase": "frontend", "model": "ministral-14b-latest",
                             "calls": n_calls,
                             "wall_seconds": round(time.time() - t0, 1)})
    print(f"frontend done: {n_calls} resolver calls")


if __name__ == "__main__":
    main()
