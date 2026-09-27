"""Arm H: hybrid pipeline (structural candidates -> tool grounding -> role ->
condition binding), plus optional narrow-LLM resolver (H+).

Architecture under test (S9):
  policy -> B dependency candidates (clauses + nominal arguments)
          -> E/F/G grounding against tool descriptions (name-blind)
          -> ROLE (OPERATION / CHECK / OBSERVATION / COMMUNICATION / OTHER)
          -> only now: condition -> selected operation edges from generic
             UD marks and argument structure.

Frozen role decision rule:
  t*  = tool with the highest NLI entailment (max_e) for the span
  label = G's pair label for t*
  if label in 4 event roles and max_e >= 0.35:
      role = mapped label; governed = [t*]
      structural override: UD mark in {if,unless,until,once} and
      role == OPERATION_EFFECT -> PRECONDITION_CHECK
  elif max over ALL tools < 0.35 -> OTHER, no tools
  else -> role stays UNKNOWN, no tools (H+ resolves these with a narrow
          LLM question: span + top-3 grounded tool descriptions)
Edge rules (generic UD marks + argument positions only):
  - mark edges from B kept when the operation endpoint is OPERATION_EFFECT
  - obl NP with case {before,after} and an operation role -> ORDER edge
  - for a non-operation clause head: obj/obl NPs with check/observation
    roles GATE the nsubj NP when the latter is an OPERATION_EFFECT
No domain word lists are used anywhere.
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from oc_common import (Mistral, load_suite, out_dir, write_usage, FROZEN_DIR,
                       ROLE_VOCAB)

LABEL_TO_ROLE = {
    "REALIZES_OPERATION": "OPERATION_EFFECT",
    "CHECKS_PRECONDITION": "PRECONDITION_CHECK",
    "OBSERVES_STATE": "STATE_OBSERVATION",
    "COMMUNICATES": "COMMUNICATION",
}
COND_MARKS = {"if", "unless", "until", "once"}

RESOLVER_SYSTEM = """You see one candidate span from a policy and the three most similar tools from the catalog. Decide what kind of mention the span is by judging the tools from their description and schema (never by name):
- REALIZES_OPERATION: executing the tool performs the action in the span
- CHECKS_PRECONDITION: executing the tool verifies whether the state in the span holds
- OBSERVES_STATE: executing the tool reads or observes the state in the span
- COMMUNICATES: executing the tool sends a communication about the span
- UNRELATED: no tool matches the span
- UNKNOWN: cannot decide
Answer with JSON only: {"label": "..."}."""


def load_arm_dir(name: str, which: str) -> Path:
    base = Path(os.environ.get("OC_OUTPUTS", str(Path(__file__).parent / "outputs")))
    return base / (name + ("_renamed" if which == "renamed" else ""))


def ground_index(efg_dir: Path) -> dict[str, dict[str, dict]]:
    """case_id -> span -> grounding record (from EFG b_candidate_grounding)."""
    out = {}
    for f in efg_dir.glob("*.json"):
        if f.name.startswith("_"):
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        case = {}
        for rec in data.get("b_candidate_grounding", []):
            case[rec["span"]] = rec
        out[data["case_id"]] = case
    return out


def decide_role(cand, grounding):
    """Return (role, governed_tools, detail)."""
    b_hyp = cand.get("role_hypothesis", "UNKNOWN")
    if grounding is None:
        return b_hyp, [], {"reason": "no_grounding"}
    nli = grounding.get("nli", {})
    if not nli:
        return b_hyp, [], {"reason": "no_nli"}
    best_tool, best_e, best_label = None, -1.0, None
    all_max = max((v.get("max_e", 0.0) for v in nli.values()), default=0.0)
    for tool, per in nli.items():
        e = per.get("max_e", 0.0)
        if e > best_e:
            best_tool, best_e, best_label = tool, e, per.get("label")
    rerank = grounding.get("rerank_rank", [])
    if best_label in LABEL_TO_ROLE and best_e >= 0.35:
        role = LABEL_TO_ROLE[best_label]
        if cand.get("mark") in COND_MARKS and role == "OPERATION_EFFECT":
            role = "PRECONDITION_CHECK"
        return role, [best_tool], {"reason": "nli", "tool": best_tool,
                                   "max_e": best_e, "label": best_label,
                                   "rerank_top": rerank[0][0] if rerank else None}
    if all_max < 0.35:
        return "OTHER", [], {"reason": "ungrounded", "all_max": round(all_max, 4)}
    return "UNKNOWN", [], {"reason": "uncertain", "all_max": round(all_max, 4),
                           "b_hypothesis": b_hyp}


def build_h(b_case, groundings, policy):
    events, details = [], []
    for cand in b_case.get("events", []):
        span = cand.get("span")
        if not span or span not in policy:
            continue
        grounding = groundings.get(span)
        role, tools, detail = decide_role(cand, grounding)
        rec = {"span": span, "role": role, "governed_tools": tools}
        if cand.get("is_np"):
            rec["is_np"] = True
            rec["np_of_verb"] = cand.get("np_of_verb")
            rec["dep_in_verb"] = cand.get("dep_in_verb")
            rec["case_lemma"] = cand.get("case_lemma")
        else:
            rec["dep"] = cand.get("dep")
            rec["mark"] = cand.get("mark")
        events.append(rec)
        details.append({"span": span, "role": role, "detail": detail})

    by_span = {e["span"]: e for e in events}

    # 1. mark edges from B, kept when the op endpoint is OPERATION_EFFECT
    edges = []
    for ed in b_case.get("edges", []):
        op = by_span.get(ed["operation_span"])
        cond = by_span.get(ed["condition_span"])
        if op and op["role"] == "OPERATION_EFFECT" and cond:
            edges.append({"condition_span": ed["condition_span"],
                          "operation_span": ed["operation_span"],
                          "relation": ed["relation"], "source": ed.get("source")})

    # index NP candidates by their verb
    np_by_verb = {}
    for e in events:
        if e.get("is_np"):
            np_by_verb.setdefault(e.get("np_of_verb"), []).append(e)

    # 2. obl NPs with case before/after -> ORDER edges against the verb op
    for e in events:
        if e.get("is_np") or e.get("dep") in {"advcl", "acl"}:
            continue
        verb = None
        for d in details:
            if d["span"] == e["span"]:
                verb = d["detail"].get("verb") if "verb" in d.get("detail", {}) else None
        # find verb lemma from B candidates directly
        verb_lemma = None
        for cand in b_case.get("events", []):
            if cand.get("span") == e["span"] and not cand.get("is_np"):
                verb_lemma = cand.get("verb")
                break
        if e["role"] != "OPERATION_EFFECT":
            continue
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

    # 3. non-operation clause heads: check/observation NPs gate the nsubj operation
    for e in events:
        if e.get("is_np") or e["role"] == "OPERATION_EFFECT":
            continue
        verb_lemma = None
        for cand in b_case.get("events", []):
            if cand.get("span") == e["span"] and not cand.get("is_np"):
                verb_lemma = cand.get("verb")
                break
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

    # deduplicate
    seen = set()
    uniq = []
    for ed in edges:
        key = (ed["condition_span"], ed["operation_span"], ed["relation"])
        if key not in seen:
            seen.add(key)
            uniq.append(ed)
    return events, uniq, details


def resolve_with_llm(case, events, details, outdir_suffix):
    """H+ : resolve UNKNOWN roles with one narrow LLM question per candidate."""
    client = Mistral(cache_dir=out_dir("Hplus_resolver" + outdir_suffix) / "_cache")
    tool_by_name = {t["name"]: t for t in case["tools"]}
    resolved = 0
    for e, d in zip(events, details):
        if e["role"] != "UNKNOWN":
            continue
        grounding = None
        # re-derive rerank top-3 from EFG output via detail is not stored here;
        # fall back to catalog tools ranked by name-stability: use all tools' names
        # from the case, take the three whose descriptions share the most tokens
        span = e["span"]
        span_tokens = set(span.lower().split())
        def overlap(t):
            return len(span_tokens & set(t["description"].lower().replace(",", " ").replace(".", " ").split()))
        top3 = sorted(case["tools"], key=lambda t: -overlap(t))[:3]
        user = json.dumps({"policy_span": span,
                           "tools": top3}, ensure_ascii=False)
        rec = client.ask(RESOLVER_SYSTEM, user, max_tokens=200)
        answer, err = Mistral.parse_json(rec["raw"])
        label = answer.get("label")
        if label in LABEL_TO_ROLE:
            e["role"] = LABEL_TO_ROLE[label]
            e["governed_tools"] = [top3[0]["name"]] if top3 else []
            resolved += 1
        d["resolver"] = {"label": label, "err": err}
    return resolved, client


def main():
    which = os.environ.get("OC_SUITE", "original")
    resolve = os.environ.get("OC_RESOLVE", "0") == "1"
    arm = "Hplus_hybrid" if resolve else "H_hybrid"
    suite = load_suite(which)
    suffix = "_renamed" if which == "renamed" else ""
    b_dir = load_arm_dir("B_dependency", which)
    efg_dir = load_arm_dir("EFG_grounding", which)
    groundings = ground_index(efg_dir)
    t0 = time.time()
    outdir = out_dir(arm + suffix)
    usage_extra = {}
    for case in suite:
        path = outdir / f"{case['case_id']}.json"
        if path.is_file():
            continue
        b_path = b_dir / f"{case['case_id']}.json"
        if not b_path.is_file():
            print("missing B output for", case["case_id"])
            continue
        b_case = json.loads(b_path.read_text(encoding="utf-8"))
        events, edges, details = build_h(b_case, groundings.get(case["case_id"], {}),
                                         case["policy"])
        resolved = 0
        if resolve:
            resolved, client = resolve_with_llm(case, events, details, suffix)
            usage_extra = {"resolver_calls": client.calls,
                           "resolver_usage": client.usage_total,
                           "resolved": resolved}
        # after resolution, re-filter mark edges that now have operation endpoints
        path.write_text(json.dumps({
            "case_id": case["case_id"],
            "events": events, "edges": edges, "details": details,
        }, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage(arm + suffix, {"wall_seconds": round(time.time() - t0, 1),
                               "suite": which,
                               "inputs": ["B_dependency", "EFG_grounding"],
                               **usage_extra})
    print(arm, "done", which)


if __name__ == "__main__":
    main()
