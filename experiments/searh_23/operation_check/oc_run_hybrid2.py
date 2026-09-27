"""Arm H2: POST-HOC hybrid variant (designed AFTER opening the frozen main
results; validated on the NEW mini set per S15).

Failure analysis of frozen H showed: (a) NLI pair labels mislabel roles
(CHECKS vs OBSERVES confusion, phrasing sensitivity), (b) ungrounded spans
fell to OTHER. H2 changes only the ROLE SOURCE: every B candidate gets ONE
narrow LLM question with the top-3 tools selected by the cross-encoder
reranker (F, the strongest grounder: 88% top-1). Structural overrides and
edge construction stay exactly as in frozen H.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import (Mistral, load_suite, out_dir, write_usage, suffix_for)
from oc_run_hybrid import LABEL_TO_ROLE, COND_MARKS, RESOLVER_SYSTEM, ground_index


def load_arm_dir(name: str, which: str) -> Path:
    base = Path(os.environ.get("OC_OUTPUTS", str(Path(__file__).parent / "outputs")))
    return base / (name + suffix_for(which))


def top3_by_rerank(grounding, tools):
    if grounding and grounding.get("rerank_rank"):
        names = [row[0] for row in grounding["rerank_rank"][:3]]
        by_name = {t["name"]: t for t in tools}
        chosen = [by_name[n] for n in names if n in by_name]
        if chosen:
            return chosen, names[0]
    span_words = None
    return tools[:3], tools[0]["name"] if tools else None


def build_h2(b_case, groundings, tools, client, policy):
    by_name = {t["name"]: t for t in tools}
    events, details = [], []
    calls = 0
    for cand in b_case.get("events", []):
        span = cand.get("span")
        if not span or span not in policy:
            continue
        grounding = groundings.get(span)
        top3, top1_name = top3_by_rerank(grounding, tools)
        label = None
        if top3:
            user = json.dumps({"policy_span": span, "tools": top3},
                              ensure_ascii=False)
            rec = client.ask(RESOLVER_SYSTEM, user, max_tokens=200)
            calls += 1
            answer, err = Mistral.parse_json(rec["raw"])
            label = answer.get("label")
        role = "UNKNOWN"
        governed = []
        if label in LABEL_TO_ROLE:
            role = LABEL_TO_ROLE[label]
            if cand.get("mark") in COND_MARKS and role == "OPERATION_EFFECT":
                role = "PRECONDITION_CHECK"
            governed = [top1_name] if top1_name else []
        elif label == "UNRELATED":
            role = "OTHER"
        rec_e = {"span": span, "role": role, "governed_tools": governed}
        if cand.get("is_np"):
            rec_e.update({"is_np": True, "np_of_verb": cand.get("np_of_verb"),
                          "dep_in_verb": cand.get("dep_in_verb"),
                          "case_lemma": cand.get("case_lemma")})
        else:
            rec_e.update({"dep": cand.get("dep"), "mark": cand.get("mark")})
        events.append(rec_e)
        details.append({"span": span, "resolver_label": label,
                        "top3": [t["name"] for t in top3]})

    by_span = {e["span"]: e for e in events}

    # mark edges from B: keep when op endpoint is OPERATION_EFFECT; retype
    # "X before Y" by the prior event's final role
    edges = []
    for ed in b_case.get("edges", []):
        op = by_span.get(ed["operation_span"])
        cond = by_span.get(ed["condition_span"])
        if op and op["role"] == "OPERATION_EFFECT" and cond:
            rel = ed["relation"]
            if ed.get("source") in {"mark:before", "obl:before"} and \
                    cond["role"] in {"PRECONDITION_CHECK", "STATE_OBSERVATION",
                                     "COMMUNICATION"}:
                rel = "GATE"
            edges.append({"condition_span": ed["condition_span"],
                          "operation_span": ed["operation_span"],
                          "relation": rel, "source": ed.get("source")})

    # NP argument edges (same generic rules as H)
    np_by_verb = {}
    for e in events:
        if e.get("is_np"):
            np_by_verb.setdefault(e.get("np_of_verb"), []).append(e)
    verb_of = {}
    for cand in b_case.get("events", []):
        if not cand.get("is_np"):
            verb_of[cand.get("span")] = cand.get("verb")

    for e in events:
        if e.get("is_np") or e["role"] != "OPERATION_EFFECT":
            continue
        verb_lemma = verb_of.get(e["span"])
        for np in np_by_verb.get(verb_lemma, []):
            case = np.get("case_lemma")
            if case == "before" and np["role"] in {"OPERATION_EFFECT", "OTHER", "UNKNOWN"}:
                edges.append({"condition_span": e["span"], "operation_span": np["span"],
                              "relation": "ORDER_BEFORE", "source": "obl:before"})
            elif case == "after" and np["role"] in {"OPERATION_EFFECT", "OTHER", "UNKNOWN"}:
                edges.append({"condition_span": np["span"], "operation_span": e["span"],
                              "relation": "ORDER_BEFORE", "source": "obl:after"})
            elif case in {"before", "after"} and np["role"] in {"PRECONDITION_CHECK",
                                                                "STATE_OBSERVATION"}:
                edges.append({"condition_span": np["span"], "operation_span": e["span"],
                              "relation": "GATE", "source": f"obl:{case}"})
    for e in events:
        if e.get("is_np") or e["role"] == "OPERATION_EFFECT":
            continue
        verb_lemma = verb_of.get(e["span"])
        if not verb_lemma:
            continue
        nps = np_by_verb.get(verb_lemma, [])
        subj_ops = [np for np in nps if np.get("dep_in_verb") == "nsubj"
                    and np["role"] == "OPERATION_EFFECT"]
        if not subj_ops:
            continue
        for np in nps:
            if np.get("dep_in_verb") in {"obj", "obl"} and np["role"] in {
                    "PRECONDITION_CHECK", "STATE_OBSERVATION"}:
                for subj in subj_ops:
                    edges.append({"condition_span": np["span"],
                                  "operation_span": subj["span"],
                                  "relation": "GATE", "source": "argstructure"})
    seen = set()
    uniq = []
    for ed in edges:
        key = (ed["condition_span"], ed["operation_span"], ed["relation"])
        if key not in seen:
            seen.add(key)
            uniq.append(ed)
    return events, uniq, details, calls


def main():
    which = os.environ.get("OC_SUITE", "mini")
    arm = "H2_hybrid"
    suite = load_suite(which)
    suffix = suffix_for(which)
    b_dir = load_arm_dir("B_dependency", which)
    efg_dir = load_arm_dir("EFG_grounding", which)
    groundings = ground_index(efg_dir)
    client = Mistral(cache_dir=out_dir(arm + suffix) / "_cache")
    t0 = time.time()
    outdir = out_dir(arm + suffix)
    total_calls = 0
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        b_path = b_dir / f"{case['case_id']}.json"
        if not b_path.is_file():
            print("missing B output for", case["case_id"])
            continue
        b_case = json.loads(b_path.read_text(encoding="utf-8"))
        events, edges, details, calls = build_h2(
            b_case, groundings.get(case["case_id"], {}), case["tools"], client,
            case["policy"])
        total_calls += calls
        path.write_text(json.dumps({
            "case_id": case["case_id"],
            "events": events, "edges": edges, "details": details,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage(arm + suffix, {"wall_seconds": round(time.time() - t0, 1),
                               "suite": which,
                               "inputs": ["B_dependency", "EFG_grounding", "Mistral"],
                               "resolver_calls": total_calls,
                               "resolver_usage": client.usage_total,
                               "post_hoc": True})
    print(arm, "done", which, "calls", total_calls, client.usage_total)


if __name__ == "__main__":
    main()
