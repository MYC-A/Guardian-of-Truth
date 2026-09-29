"""Track B: full Step 1 downstream over frontend candidate graphs.

FAITHFUL port of the frozen policy_licensing_v1 / event_canon_v1 stack:
  candidate nodes -> member-level CE band 0.35 (sentence context +
  tool semantics construction, any-member-pair gating) -> EXTRACTIVE
  EVIDENCE -> evidence judge -> DIR (with role/position fallback) -> CLS.

Evidence arms:
  E1  current extractor + judge (frozen prompts verbatim, frozen
       node_event_view: source_span/role/governed_tools/tool_semantics);
  E2  frontend-informed: endpoint rendering enriched with the frontend's
       proposed type and arguments (the ONLY delta vs E1);
  E3  endpoint-aware certificate (Q1-Q5 extractor + separate endpoint
       verifier + deterministic span grounding; UNKNOWN discipline);
  E3W = E3 + AMR predicate-vs-argument witness veto (AMR arm only).

Node construction per arm (a priori rules, identical for every arm):
  - candidates with type in {EVENT, EVENT_REFERENCE, STATE_OR_FACET,
    CHECK, UNKNOWN} become event-node members; ENTITY/ARTIFACT are
    typed OUT (the new ontology's junk gate);
  - canonical grouping via the frontend's proposed SAME_EVENT /
    REFERENCE_OF relations; no links -> singleton nodes;
  - role mapping (common, a priori): EVENT->OPERATION_EFFECT,
    CHECK->PRECONDITION_CHECK, STATE_OR_FACET->STATE_OBSERVATION,
    EVENT_REFERENCE/UNKNOWN->UNKNOWN; CUR keeps its resolver roles;
  - tool grounding: name-blind bge-reranker top-1.

Oracle controls through the same downstream: ORACLE_MENTIONS (gold
spans, type UNKNOWN, singleton nodes), ORACLE_TYPES (+ types),
ORACLE_LINKS (+ grouping by canonical event), FULL_GOLD (+ gold
roles/tools).

Run:  python3 lf_downstream.py <ARM|ORACLE_*> E1|E2|E3|E3W
"""
from __future__ import annotations

import json
import os
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL), str(HERE)]
from pl_run_llm import SYSTEM, ev_user, evjudge_user, dir_user, cls_user  # noqa
from pl_common import Mistral, render_tool  # noqa: E402
from lf_certificate import (E3_EXT_SYSTEM, E3_JUDGE_SYSTEM,  # noqa: E402
                            e3_ext_user, e3_judge_user,
                            verify_certificate, sanitize_quote,
                            amr_argument_witness)

OUT = HERE / "outputs"
CE_BAND = 0.35
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "CHECK",
             "UNKNOWN"}
TYPE_TO_ROLE = {"EVENT": "OPERATION_EFFECT", "CHECK": "PRECONDITION_CHECK",
                "STATE_OR_FACET": "STATE_OBSERVATION",
                "EVENT_REFERENCE": "UNKNOWN", "UNKNOWN": "UNKNOWN"}


def load_gold(which: str = "original") -> dict[str, dict]:
    fname = ("level_f_cases.json" if which == "original"
             else "level_f_cases_renamed.json")
    import os
    if os.environ.get("LF_SUITE") == "f2":
        fname = ("level_f2_cases.json" if which == "original"
                 else "level_f2_cases_renamed.json")
    return {c["case_id"]: c for c in json.loads(
        (HERE / "frozen" / fname).read_text(encoding="utf-8"))}


# ------------------------------------------------------------ nodes
def build_nodes(arm: str, case: dict) -> list[dict]:
    f = OUT / arm / f"{case['case_id']}.json"
    if not f.exists():
        return []
    data = json.loads(f.read_text(encoding="utf-8"))
    cands = data["candidates"]
    keep = [c for c in cands if c.get("type", "UNKNOWN") in EVENTLIKE]
    parent = {c["cid_local"]: c["cid_local"] for c in keep}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for c in keep:
        for r in c.get("relations", []):
            if r.get("type") in ("SAME_EVENT", "REFERENCE_OF") \
                    and r.get("to") in parent:
                union(c["cid_local"], r["to"])
    groups: dict[str, list] = defaultdict(list)
    for c in keep:
        groups[find(c["cid_local"])].append(c)
    nodes = []
    for i, (root, members) in enumerate(
            sorted(groups.items(),
                   key=lambda kv: min(m.get("start") or 10**6
                                      for m in kv[1]))):
        spans = [m["span"] for m in members if m.get("span")]
        types = [m.get("type", "UNKNOWN") for m in members]
        mtype = max(set(types), key=types.count)
        roles = [m.get("role") for m in members if m.get("role")
                 and m["role"] != "UNKNOWN"]
        role = (max(set(roles), key=roles.count) if roles
                else TYPE_TO_ROLE.get(mtype, "UNKNOWN"))
        nodes.append({
            "node_id": f"N{i+1:02d}",
            "members": [m["cid_local"] for m in members],
            "span": spans[0] if spans else "",
            "start": min((m.get("start") or 10**6) for m in members),
            "type": mtype, "role": role,
            "member_spans": spans,
            "arguments": [a for m in members for a in m.get("arguments", [])],
            "amr_graphs": data.get("amr_graphs") if arm == "AMR" else None})
    return nodes


def oracle_nodes(case: dict, level: str) -> list[dict]:
    if level in ("ORACLE_MENTIONS", "ORACLE_TYPES"):
        groups = [(m["mid"], [m]) for m in case["mentions"]]
    else:  # ORACLE_LINKS / FULL_GOLD: group by canonical event
        by_cid: dict[str, list] = defaultdict(list)
        for m in case["mentions"]:
            if m["type"] in EVENTLIKE:
                by_cid[m["cid"]].append(m)
        groups = list(by_cid.items())
    nodes = []
    for i, (gid, mem) in enumerate(sorted(
            groups, key=lambda kv: min(m["start"] for m in kv[1]))):
        if level == "ORACLE_MENTIONS":
            mtype = "UNKNOWN"
        else:
            mtype = mem[0]["type"]
        role = TYPE_TO_ROLE.get(mtype, "UNKNOWN")
        if level == "FULL_GOLD":
            ev = next((e for e in case["canonical_events"]
                       if e["cid"] == gid), None)
            if ev:
                role = ev["role"]
        nodes.append({"node_id": f"O{i+1:02d}", "members": [m["mid"]
                                                      for m in mem],
                      "span": mem[0]["span"], "start": mem[0]["start"],
                      "type": mtype, "role": role,
                      "member_spans": [m["span"] for m in mem],
                      "arguments": [], "amr_graphs": None})
    return nodes


# -------------------------------------------------------- views (frozen)
def node_view(case: dict, n: dict, enriched: bool = False) -> dict:
    """Frozen node_event_view construction (source_span, role,
    governed_tools, span_start, tool_semantics; multispan rendering).
    E2 additionally appends the frontend's proposed type/arguments."""
    by_name = {t["name"]: t for t in case["tools"]}
    tools = " ".join(render_tool(by_name[t]) for t in n.get(
        "governed_tools", []) if t in by_name)
    span = n["span"]
    spans = sorted(set(n.get("member_spans", [])), key=len)
    if len(spans) > 1:
        span = f'"{spans[0]}" (also referenced as: ' + \
               "; ".join(f'"{x}"' for x in spans[1:]) + ")"
    view = {"source_span": span, "role": n["role"],
            "governed_tools": n.get("governed_tools", []),
            "span_start": n.get("start", 0), "tool_semantics": tools}
    if enriched:
        view["source_span"] = span + \
            f" [frontend type: {n.get('type', 'UNKNOWN')}]"
        if n.get("arguments"):
            args = "; ".join(f"{a.get('role')}: \"{a.get('span')}\""
                             for a in n["arguments"][:4])
            view["source_span"] += f" [arguments: {args}]"
    return view


def main() -> None:
    from sentence_transformers import CrossEncoder

    arm = sys.argv[1] if len(sys.argv) > 1 else "LLM_SG"
    ev_arm = sys.argv[2] if len(sys.argv) > 2 else "E1"
    which = os.environ.get("LF_SUITE", "original")
    gold = load_gold(which)
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")

    outdir = OUT / f"DOWN_{arm}_{ev_arm}"
    outdir.mkdir(parents=True, exist_ok=True)

    def ask(system, user, max_tokens=600):
        for _ in range(4):
            try:
                r = client.ask(system, user, max_tokens=max_tokens)
                parsed, _ = Mistral.parse_json(r["raw"])
                if parsed:
                    return parsed
            except Exception:
                time.sleep(3)
        return {}

    import re

    def sent_of(start, policy):
        pos = 0
        for s in re.split(r"(?<=[.!?])\s+", policy):
            if pos <= start < pos + len(s):
                return s.strip()
            pos += len(s) + 1
        return ""

    for cid_, case in gold.items():
        path = outdir / f"{cid_}.json"
        if path.exists():
            continue
        policy = case["policy"]
        by_name = {t["name"]: t for t in case["tools"]}
        nodes = (oracle_nodes(case, arm) if arm.startswith(("ORACLE",
                                                            "FULL"))
                 else build_nodes(arm, case))
        if not nodes:
            path.write_text(json.dumps({"case_id": cid_, "nodes": [],
                                        "edges": []}) + "\n")
            continue
        # tool grounding: name-blind rerank top-1 (common machinery)
        pairs, owners = [], []
        for i, n in enumerate(nodes):
            for t in case["tools"]:
                pairs.append((n["span"], render_tool(t)))
                owners.append(i)
        scores = rer.predict(pairs, batch_size=32,
                             convert_to_numpy=True).tolist() if pairs else []
        top: dict[int, list] = defaultdict(list)
        for i, s in zip(owners, scores):
            top[i].append(float(s))
        for i, n in enumerate(nodes):
            tools = sorted(zip(case["tools"], top.get(i, [])),
                           key=lambda x: -x[1])
            n["governed_tools"] = [t["name"] for t, _ in tools[:1]]

        def tool_text(n):
            return " ".join(render_tool(by_name[t])
                            for t in n.get("governed_tools", [])
                            if t in by_name)

        # member-level CE gating (frozen construction: sentence context of
        # one member + span/sentence/tools of the other member)
        mpairs, owners2 = [], []
        for i in range(len(nodes)):
            for j in range(len(nodes)):
                if i >= j:
                    continue
                for ma in nodes[i]["member_spans"] or [nodes[i]["span"]]:
                    for mb in nodes[j]["member_spans"] or [nodes[j]["span"]]:
                        sa = sent_of(policy.find(ma), policy) or ma
                        tb = f"{mb}. {sent_of(policy.find(mb), policy)} " \
                             f"{tool_text(nodes[j])}".strip()
                        mpairs.append((sa, tb))
                        owners2.append((i, j))
        scores2 = rer.predict(mpairs, batch_size=32,
                              convert_to_numpy=True).tolist() if mpairs \
            else []
        best: dict[tuple, float] = {}
        for (i, j), sc in zip(owners2, scores2):
            best[(i, j)] = max(best.get((i, j), -1e9), float(sc))
        edges = []
        for (i, j), sc in sorted(best.items()):
            if sc < CE_BAND:
                continue
            na, nb = nodes[i], nodes[j]
            ev_a = node_view(case, na, enriched=(ev_arm == "E2"))
            ev_b = node_view(case, nb, enriched=(ev_arm == "E2"))
            licensed, direction, rel, detail = False, None, None, {}
            if ev_arm in ("E1", "E2"):
                ans = ask(SYSTEM, ev_user(case, ev_a, ev_b), 260)
                evidence = (ans or {}).get("evidence")
                if not evidence or evidence == "NO_EVIDENCE":
                    continue
                if evidence not in policy:
                    continue  # hallucinated quote -> no license
                ans2 = ask(SYSTEM, evjudge_user(ev_a, ev_b, evidence), 200)
                if (ans2 or {}).get("decision") != "LICENSED":
                    continue
                licensed = True
                detail = {"evidence": evidence, "judge": ans2}
            elif ev_arm in ("E3", "E3W"):
                cert = ask(E3_EXT_SYSTEM, e3_ext_user(policy, ev_a, ev_b),
                           500)
                v = verify_certificate(policy, cert, ev_a, ev_b)
                if v["verdict"] == "SUPPORTED":
                    ev = sanitize_quote(cert.get("relation_text"))
                    judge = ask(E3_JUDGE_SYSTEM, e3_judge_user(ev, ev_a, ev_b),
                                400)
                    q1 = sanitize_quote(judge.get("q1_where_is_a"))
                    q2 = sanitize_quote(judge.get("q2_where_is_b"))
                    if judge.get("q3_relation_between_these_two") != "YES":
                        licensed = False
                        detail = {"certificate": cert, "verify": v,
                                  "judge": judge, "note": "verifier_q3_no"}
                    elif not (q1 and q1 in ev and q2 and q2 in ev):
                        licensed = False
                        detail = {"certificate": cert, "verify": v,
                                  "judge": judge,
                                  "note": "verifier_q1q2_not_in_evidence"}
                    else:
                        licensed = True
                        direction = judge.get("q4_direction", "UNKNOWN")
                        rel = judge.get("q5_relation_type", "UNKNOWN")
                        detail = {"certificate": cert, "verify": v,
                                  "judge": judge}
                else:
                    licensed = False
                    detail = {"certificate": cert, "verify": v}
                if ev_arm == "E3W" and licensed:
                    wit = amr_argument_witness(
                        (na.get("amr_graphs") or []) +
                        (nb.get("amr_graphs") or []),
                        ev_a["source_span"], ev_b["source_span"])
                    if wit:
                        licensed = False
                        detail["amr_witness"] = wit
                        detail["note"] = "amr_argument_veto"
            if not licensed:
                continue
            # DIR with the frozen role/position fallback
            if direction is None:
                ans3 = ask(SYSTEM, dir_user(case, ev_a, ev_b), 200)
                first = (ans3 or {}).get("first")
                if first == "A":
                    direction = "A_TO_B"
                elif first == "B":
                    direction = "B_TO_A"
                else:
                    ra, rb = na["role"], nb["role"]
                    if rb in ("PRECONDITION_CHECK", "STATE_OBSERVATION") \
                            and ra not in ("PRECONDITION_CHECK",
                                           "STATE_OBSERVATION"):
                        direction = "B_TO_A"
                    elif na["start"] > nb["start"]:
                        direction = "B_TO_A"
                    else:
                        direction = "A_TO_B"
            # CLS on the directed pair (frozen)
            if rel is None:
                if direction == "B_TO_A":
                    cls_a, cls_b = ev_b, ev_a
                else:
                    cls_a, cls_b = ev_a, ev_b
                ans4 = ask(SYSTEM, cls_user(case, cls_a, cls_b), 240)
                rel = (ans4 or {}).get("relation", "UNKNOWN")
            edges.append({"u": na["node_id"], "v": nb["node_id"],
                          "u_members": na["members"],
                          "v_members": nb["members"],
                          "u_span": na["span"], "v_span": nb["span"],
                          "relation": rel, "direction": direction,
                          "ce": round(sc, 4), "detail": detail})
        path.write_text(json.dumps({"case_id": cid_, "arm": arm,
                                    "ev_arm": ev_arm, "nodes": [
                                        {"node_id": n["node_id"],
                                         "span": n["span"],
                                         "type": n.get("type"),
                                         "start": n.get("start"),
                                         "members": n["members"],
                                         "member_spans": n["member_spans"]}
                                        for n in nodes],
                                    "edges": edges}, indent=1) + "\n",
                        encoding="utf-8")
        print(cid_, len(nodes), "nodes ->", len(edges), "edges", flush=True)
    print("DOWNSTREAM", arm, ev_arm, "done")


if __name__ == "__main__":
    main()
