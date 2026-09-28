"""EVENT_CANON_v1 - Track C: downstream relation stack over canonical nodes.

REAL FRONTEND -> canonicalization -> EXISTING extractive-evidence licensing
-> EXISTING DIR -> EXISTING CLS. Relation components are NOT tuned: prompts
are reused verbatim from policy_licensing_v1 (pl_run_llm.ev_user /
evjudge_user / dir_user / cls_user), CE band frozen at 0.35.

Node modes:
  raw    : nodes = individual predicted events (no canonicalization control)
  canon  : nodes = Track B clusters (majority-vote attributes, no gold leak)
  oracle : nodes = gold canonical events via alignment members (upper bound
           isolating canonicalization from event-extraction noise)

Scoring vs gold edges between canonical events (alignment-mediated):
  correct  = predicted edge whose member alignments hit a gold edge pair
  extra    = predicted edge with no gold support (incl. NON_EVENT nodes)
  missing  = gold edge with no predicted edge over its aligned members
  + direction accuracy and relation-type accuracy on correct edges,
  graph exact match per case.
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

from pl_run_llm import (SYSTEM, ev_user, evjudge_user, dir_user, cls_user)
from pl_common import Mistral, render_tool
from ec_common import load_suite, out_dir, write_usage, MODELS

CE_BAND = 0.35


def _attach_member_spans(nodes, frontend_dir, case):
    data = json.loads((frontend_dir / f"{case['case_id']}.json")
                      .read_text(encoding="utf-8"))["events"]
    for n in nodes:
        n["member_spans"] = [data[int(m[1:])]["span"] for m in n["members"]
                             if m.startswith("P") and m[1:].isdigit()]
    return nodes


def load_nodes(mode, case, trackb_dir=None, fdir="FRONTEND"):
    """Return list of node dicts: node_id, span, start, role, governed_tools,
    members (predicted mention ids)."""
    if mode == "raw":
        data = json.loads((out_dir(fdir) / f"{case['case_id']}.json")
                          .read_text(encoding="utf-8"))["events"]
        return [{"node_id": f"P{i:02d}", "span": p["span"],
                 "start": p["span_start"], "role": p["role"],
                 "governed_tools": p.get("governed_tools", []),
                 "members": [f"P{i:02d}"]} for i, p in enumerate(data)]
    if mode == "canon":
        data = json.loads((trackb_dir / f"{case['case_id']}.json")
                          .read_text(encoding="utf-8"))
        return data["nodes"]
    if mode == "oracle":
        apath = out_dir("ALIGNMENT") / f"{case['case_id']}.json"
        align = json.loads(apath.read_text(encoding="utf-8"))["alignments"]
        frontend = json.loads((out_dir(fdir) /
                               f"{case['case_id']}.json")
                              .read_text(encoding="utf-8"))["events"]
        by_cid = {}
        for r in align:
            if r["label"] != "NON_EVENT":
                by_cid.setdefault(r["label"], []).append(
                    (r["i"], frontend[r["i"]]))
        nodes = []
        for k, (cid_, mem) in enumerate(sorted(by_cid.items(),
                                               key=lambda kv: min(
                                                   m[1]["span_start"]
                                                   for m in kv[1]))):
            roles = [m[1]["role"] for m in mem if m[1]["role"] != "UNKNOWN"]
            role = max(set(roles), key=roles.count) if roles else "UNKNOWN"
            tools = [t for _, m in mem for t in m.get("governed_tools", [])]
            tool = max(set(tools), key=tools.count) if tools else None
            nodes.append({"node_id": f"O{cid_}", "span": mem[0][1]["span"],
                          "start": mem[0][1]["span_start"], "role": role,
                          "governed_tools": [tool] if tool else [],
                          "members": [f"P{i:02d}" for i, _ in mem]})
        return nodes
    raise SystemExit(f"unknown mode {mode}")


def _attach_and_return(mode, nodes, case, fdir):
    if mode != "raw":
        _attach_member_spans(nodes, out_dir(fdir), case)
    return nodes


def node_event_view(case, n, multispan=False):
    by_name = {t["name"]: t for t in case["tools"]}
    tools = " ".join(render_tool(by_name[t]) for t in n["governed_tools"]
                     if t in by_name)
    span = n["span"]
    if multispan and len(n.get("member_spans", [])) > 1:
        spans = sorted(set(n["member_spans"]), key=len)
        alt = "; ".join('"' + x + '"' for x in spans[1:])
        span = '"' + spans[0] + '" (also referenced as: ' + alt + ")"
    return {"source_span": span, "role": n["role"],
            "governed_tools": n["governed_tools"], "span_start": n["start"],
            "tool_semantics": tools}


def main():
    import os
    mode = sys.argv[1] if len(sys.argv) > 1 else "canon"
    trackb_name = sys.argv[2] if len(sys.argv) > 2 else None
    from sentence_transformers import CrossEncoder
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model=MODELS["mistral"], cache_dir=out_dir("_cache"))
    which = os.environ.get("EC_SUITE", "original")
    multispan = os.environ.get("EC_MULTISPAN", "0") == "1"
    trackb_dir = out_dir(trackb_name) if trackb_name else None
    suite = load_suite(which)
    fdir = "FRONTEND" if which == "original" else "FRONTEND_renamed"
    t0 = time.time()
    n_calls = 0
    res_dir = out_dir(f"DOWNSTREAM_{mode}" + (f"_{trackb_name}" if trackb_name else "")
                      + ("_ms" if multispan else "")
                      + ("" if which == "original" else "_renamed"))
    for case in suite:
        cid_ = case["case_id"]
        outpath = res_dir / f"{cid_}.json"
        if outpath.is_file():
            continue
        nodes = _attach_and_return(mode, load_nodes(mode, case, trackb_dir, fdir),
                                   case, fdir)
        policy = case["policy"]
        apath = out_dir("ALIGNMENT") / f"{cid_}.json"
        align = {r["i"]: r for r in json.loads(
            apath.read_text(encoding="utf-8"))["alignments"]}
        gold_edges = {(e["from_cid"], e["to_cid"]): e for e in case["edges"]}
        gold_unordered = {frozenset((a, b)) for a, b in gold_edges}
        # CE band over node pairs (name-blind, same construction as the
        # policy_licensing_v1 real track: sentence context + tool semantics)
        import re
        by_name = {t["name"]: t for t in case["tools"]}

        def sent_of(start):
            pos, k = 0, 0
            for s in re.split(r"(?<=[.!?])\s+", policy):
                if pos <= start < pos + len(s):
                    return s.strip()
                pos += len(s) + 1
                k += 1
            return ""

        def tool_text(n):
            return " ".join(render_tool(by_name[t]) for t in n["governed_tools"]
                            if t in by_name)

        pairs = []
        for i in range(len(nodes)):
            for j in range(i + 1, len(nodes)):
                a, b = nodes[i], nodes[j]
                sa = sent_of(a["start"]) or a["span"]
                tb = f"{b['span']}. {sent_of(b['start'])} {tool_text(b)}".strip()
                pairs.append(((i, j), (sa, tb)))
        scores = rer.predict([p[1] for p in pairs], batch_size=32,
                             convert_to_numpy=True) if pairs else []
        ce = {p[0]: float(s) for p, s in zip(pairs, scores)}
        # evidence pipeline on CE-band pairs
        edges = []
        for (i, j), sc in ce.items():
            if sc < CE_BAND:
                continue
            a, b = nodes[i], nodes[j]
            ev_a, ev_b = (node_event_view(case, a, multispan),
                          node_event_view(case, b, multispan))
            rec = client.ask(SYSTEM, ev_user(case, ev_a, ev_b), max_tokens=260)
            n_calls += 1
            ans, _ = Mistral.parse_json(rec["raw"])
            evidence = (ans or {}).get("evidence")
            if not evidence or evidence == "NO_EVIDENCE":
                continue
            rec2 = client.ask(SYSTEM, evjudge_user(ev_a, ev_b, evidence),
                              max_tokens=200)
            n_calls += 1
            ans2, _ = Mistral.parse_json(rec2["raw"])
            if (ans2 or {}).get("decision") != "LICENSED":
                continue
            # direction
            rec3 = client.ask(SYSTEM, dir_user(case, ev_a, ev_b),
                              max_tokens=200)
            n_calls += 1
            ans3, _ = Mistral.parse_json(rec3["raw"])
            first = (ans3 or {}).get("first")
            u, v = i, j
            if first == "B":
                u, v = j, i
            elif first not in ("A", "B"):
                ra, rb = a["role"], b["role"]
                if rb in ("PRECONDITION_CHECK", "STATE_OBSERVATION") and ra not in (
                        "PRECONDITION_CHECK", "STATE_OBSERVATION"):
                    u, v = j, i
                elif a["start"] > b["start"]:
                    u, v = j, i
            # relation type
            rec4 = client.ask(SYSTEM, cls_user(
                case, node_event_view(case, nodes[u], multispan),
                node_event_view(case, nodes[v], multispan)),
                max_tokens=240)
            n_calls += 1
            ans4, _ = Mistral.parse_json(rec4["raw"])
            edges.append({"u": nodes[u]["node_id"], "v": nodes[v]["node_id"],
                          "u_members": nodes[u]["members"],
                          "v_members": nodes[v]["members"],
                          "ce": round(sc, 4), "evidence": evidence,
                          "relation": (ans4 or {}).get("relation"),
                          "dir_first": first})
        outpath.parent.mkdir(parents=True, exist_ok=True)
        outpath.write_text(json.dumps({"case_id": cid_, "nodes": [
            {"node_id": n["node_id"], "span": n["span"], "role": n["role"],
             "members": n["members"]} for n in nodes], "edges": edges},
            ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"[{cid_}] {len(nodes)} nodes -> {len(edges)} edges", flush=True)
    write_usage(f"DOWNSTREAM_{mode}", {"llm_calls": n_calls,
                                       "wall_seconds": round(time.time() - t0, 1)})
    print(f"downstream done ({mode}): {n_calls} calls")


if __name__ == "__main__":
    main()
