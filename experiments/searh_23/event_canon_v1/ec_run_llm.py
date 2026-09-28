"""EVENT_CANON_v1 - LLM arms over GOLD mentions (Track A).

Arm E (X-AMR-style): one narrow extraction call per mention -> structured
event graph; pair decisions via a deterministic, pre-registered comparator
(predicate family, entities, polarity, time, occurrence index, event_mode).

Arm F (narrow pair judge): one call per candidate pair with exact spans +
minimal local context (containing sentence + 1 preceding). Policy text only,
name-blind by construction (Track A arms never see tool names; the renamed
suite is therefore structurally identical for them - rename checks apply to
Track B / downstream).

Candidate generation for F: union of locality / lexical / embedding-top3
signals (recall-optimized, frozen on dev).
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
sys.path.insert(0, str(HERE))

from ec_common import (Mistral, load_suite, load_pairs_gold, out_dir,
                       write_usage, local_context, MODELS)
from ec_feats import (content_tokens, lemma_family_match, norm_lemma,
                      candidate_pairs)

SYSTEM_E = """You convert one event mention from a policy text into a small structured event graph (AMR style). Read the mention and its local context. Extract JSON only:
{"predicate": "<base verb-like lemma of the event this mention refers to, e.g. inspect / approve / weigh>", "event_mode": "ACTION"|"STATE"|"OBSERVATION"|"CHECK"|"REFERENCE"|"COMMUNICATION"|"UNKNOWN", "actor": "<who performs it, or null>", "patient": "<what it acts on, or null>", "entities": ["<distinct entity identifiers mentioned, e.g. 'bus 12', 'left wing'>"], "polarity": "POS"|"NEG", "modality": "REQUIRED"|"PERMITTED"|"PROHIBITED"|"REPORTED"|"NONE", "time": "<temporal anchor of THIS mention, e.g. 'before delivery', 'Monday', or null>", "occurrence_index": <integer 1 for the first occurrence, 2+ if the text marks a distinct later occurrence (e.g. 'again', 'repeat', 'November')>}
Rules:
- predicate: the underlying event lemma the mention refers to; for references like 'this inspection', 'the weighing', 'after approval', 'each bake' give the base event lemma (inspect / weigh / approve / bake);
- for a resultant state ('the film is developed', 'the request is approved') use event_mode STATE with the state's base predicate;
- for a passive action ('the batch is weighed', 'it is certified') use ACTION;
- for a check/verification of another event use CHECK with the checked event's predicate;
- entities: only clear participant identifiers; ignore generic words;
- Answer with JSON only."""

SYSTEM_F = """You decide whether two event mentions from the same policy text refer to the SAME single event, are merely related but distinct events, are distinct events, or the text is insufficient to decide.

SAME single event: the two spans denote one and the same prescribed or reported occurrence - e.g. an imperative and a later passive or nominal reference to it ('Weigh each batch' / 'after the batch is weighed'), or a pronoun/nominal reference ('This verification').
Merely related but DISTINCT events include: an action vs a check or observation of that action; an action vs its result state; the same predicate on different entities, actors or times; a requirement vs a performance report; a positive vs a negated occurrence; a generic prescription vs a specific occurrence.
Judge ONLY from the given text; do not use world knowledge to merge similar-sounding events.

Compare: predicate compatibility, participants/entities, polarity, time/occurrence, and whether one span merely references the other's event.
Answer with JSON only: {"label": "SAME_EVENT"|"RELATED_BUT_DIFFERENT"|"DIFFERENT"|"UNKNOWN", "reason": "<one short sentence citing the decisive text>"}."""


def run_arm_e(client, case):
    policy = case["policy"]
    out = {}
    for m in case["mentions"]:
        ctx = local_context(policy, m["start"], window=1)
        user = json.dumps({"mention": m["span"], "local_context": ctx},
                          ensure_ascii=False)
        rec = client.ask(SYSTEM_E, user, max_tokens=280)
        ans, err = Mistral.parse_json(rec["raw"])
        out[m["mid"]] = ans or {}
    return out


def norm_time(t):
    if not t or not isinstance(t, str):
        return None
    return norm_lemma(t.strip().lower())


def graph_compare(ga, gb):
    """Deterministic comparator over arm-E graphs (pre-registered rules)."""
    if not ga or not gb:
        return "UNKNOWN", "missing-graph"
    pa = norm_lemma(str(ga.get("predicate") or ""))
    pb = norm_lemma(str(gb.get("predicate") or ""))
    if not pa or not pb:
        return "UNKNOWN", "no-predicate"
    if not lemma_family_match(pa, pb):
        return "DIFFERENT", "predicate-mismatch"
    if str(ga.get("polarity")) != str(gb.get("polarity")):
        return "RELATED_BUT_DIFFERENT", "polarity-conflict"
    ea = {norm_lemma(str(x)) for x in (ga.get("entities") or []) if x}
    eb = {norm_lemma(str(x)) for x in (gb.get("entities") or []) if x}
    if ea and eb and not (ea & eb):
        return "RELATED_BUT_DIFFERENT", "entity-conflict"
    ta, tb = norm_time(ga.get("time")), norm_time(gb.get("time"))
    if ta and tb and ta != tb:
        return "RELATED_BUT_DIFFERENT", "time-conflict"
    oa = ga.get("occurrence_index")
    ob = gb.get("occurrence_index")
    if isinstance(oa, int) and isinstance(ob, int) and oa > 0 and ob > 0 \
            and oa != ob:
        return "RELATED_BUT_DIFFERENT", "occurrence-conflict"
    ma, mb = str(ga.get("event_mode")), str(gb.get("event_mode"))
    state_like = {"STATE"}
    action_like = {"ACTION", "REFERENCE", "COMMUNICATION"}
    if (ma in state_like and mb in action_like) or \
            (mb in state_like and ma in action_like):
        return "RELATED_BUT_DIFFERENT", "action-vs-state"
    if {ma, mb} == {"ACTION", "CHECK"} or {ma, mb} == {"REFERENCE", "CHECK"}:
        return "RELATED_BUT_DIFFERENT", "action-vs-check"
    return "SAME_EVENT", "graph-compatible"


def e_pair_records(case, graphs):
    ms = case["mentions"]
    out = []
    for i in range(len(ms)):
        for j in range(i + 1, len(ms)):
            a, b = ms[i], ms[j]
            label, reason = graph_compare(graphs.get(a["mid"]),
                                          graphs.get(b["mid"]))
            out.append({"a": a["mid"], "b": b["mid"], "label": label,
                        "reason": reason})
    return out


def run_arm_f(client, case, cands):
    policy = case["policy"]
    by_mid = {m["mid"]: m for m in case["mentions"]}
    out = []
    for a_mid, b_mid in cands:
        a, b = by_mid[a_mid], by_mid[b_mid]
        user = json.dumps({
            "mention_a": a["span"],
            "context_a": local_context(policy, a["start"], window=1),
            "mention_b": b["span"],
            "context_b": local_context(policy, b["start"], window=1),
        }, ensure_ascii=False)
        rec = client.ask(SYSTEM_F, user, max_tokens=220)
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


def load_embeddings(which, case_id):
    import numpy as np
    p = out_dir(f"ARMS_{which}") / "B_emb" / f"{case_id}.npy"
    if p.is_file():
        return {m["mid"]: v for m, v in zip(
            load_case_mentions(which, case_id), np.load(p))}
    return None


def load_case_mentions(which, case_id):
    for c in load_suite(which):
        if c["case_id"] == case_id:
            return c["mentions"]
    return []


def main():
    which = sys.argv[1] if len(sys.argv) > 1 else "original"
    arm = sys.argv[2] if len(sys.argv) > 2 else "EF"
    model = MODELS["mistral"]
    client = Mistral(model=model, cache_dir=out_dir("_cache"))
    suite = load_suite(which)
    t0 = time.time()
    n_calls = 0
    for case in suite:
        cid_ = case["case_id"]
        # ---- arm E ----
        gpath = out_dir("E_xamr") / f"{cid_}.json"
        if "E" in arm and not gpath.is_file():
            graphs = run_arm_e(client, case)
            n_calls += len(graphs)
            gpath.parent.mkdir(parents=True, exist_ok=True)
            gpath.write_text(json.dumps(graphs, ensure_ascii=False, indent=1),
                             encoding="utf-8")
            recs = e_pair_records(case, graphs)
            (out_dir("E_xamr") / f"{cid_}_pairs.json").write_text(
                json.dumps(recs, ensure_ascii=False), encoding="utf-8")
            print(f"[{cid_}] E: {len(graphs)} graphs", flush=True)
        # ---- arm F (candidate pairs) ----
        fpath = out_dir("F_judge") / f"{cid_}.json"
        if "F" in arm and not fpath.is_file():
            emb = load_embeddings(which, cid_)
            cands = candidate_pairs(case["mentions"], embeddings=emb,
                                    sim_topk=3, sent_window=1)
            recs = run_arm_f(client, case, cands)
            n_calls += len(recs)
            fpath.parent.mkdir(parents=True, exist_ok=True)
            fpath.write_text(json.dumps(
                {"candidates": [list(c) for c in cands], "pairs": recs},
                ensure_ascii=False), encoding="utf-8")
            print(f"[{cid_}] F: {len(recs)} candidate pairs", flush=True)
    write_usage("E_F", {"model": model, "calls": n_calls,
                        "wall_seconds": round(time.time() - t0, 1)})
    print(f"LLM arms done ({which}/{arm}): {n_calls} calls")


if __name__ == "__main__":
    main()
