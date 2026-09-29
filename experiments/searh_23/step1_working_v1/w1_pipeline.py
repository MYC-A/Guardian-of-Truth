"""W1-H1 pipeline: boundary-normalized frontend -> E3v2 certificate -> edges.

Changes vs frozen lf_downstream.py (each one a hypothesis of arm H1):
  1. candidates from W1_BNORM (hygiene + boundary normalization, DROP out);
  2. node_view lists ALL member representations ordered by position
     (v1 displayed the shortest span first -> g_watertower b_in_relation
     failure);
  3. anchor-set verification: a_in_relation / b_in_relation may match ANY
     member span of the endpoint (v1 checked only the quoted strings but the
     extractor quoted display names that need not occur in relation_text;
     the determinstic check now accepts any member span or subspan of one);
  4. E3v2 prompts: extractor sees all surface forms; judge q5 gains
     SEMANTIC_LINK (same underlying action / descriptive facet) which routes
     a pair OUT of normative edges;
  5. direction "UNKNOWN" string no longer bypasses the DIR fallback
     (v1 bug: 4 F2 edges died as unknown_direction);
  6. self-loop gate: pairs of a node with itself are never proposed;
  7. observability: ALL CE-passing pairs are saved with stage/verdict/reason
     (v1 saved only licensed edges - loss attribution was impossible).

Everything else (CE band construction, tool grounding, DIR/CLS fallbacks)
is the frozen policy_licensing_v1 stack, ported verbatim.

Run:  python3 w1_pipeline.py <FRONTEND_ARM> [E3V2]
      FRONTEND_ARM = LLM_SG | CUR  (reads W1_BNORM/<arm>)
Env:  LF_SUITE=main|f2
Out:  outputs/W1_DOWN_<ARM>/<case>.json
"""
from __future__ import annotations

import json
import os
import re
import sys
import time
from collections import defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL), str(IE)]
from pl_run_llm import SYSTEM, dir_user, cls_user  # noqa: E402
from pl_common import Mistral, render_tool  # noqa: E402
from lf_certificate import sanitize_quote, span_in  # noqa: E402

OUT = HERE / "outputs"
CE_BAND = 0.35
EVENTLIKE = {"EVENT", "EVENT_REFERENCE", "STATE_OR_FACET", "CHECK",
             "UNKNOWN"}
TYPE_TO_ROLE = {"EVENT": "OPERATION_EFFECT", "CHECK": "PRECONDITION_CHECK",
                "STATE_OR_FACET": "STATE_OBSERVATION",
                "EVENT_REFERENCE": "UNKNOWN", "UNKNOWN": "UNKNOWN"}

# ------------------------------------------------------------ E3 v2 prompts
E3_EXT_SYSTEM_V2 = """You extract proof certificates from a workplace policy. You must quote EXACT substrings of the policy, character by character (matching capitalization). Never paraphrase.
The relation_text must be the minimal COMPLETE clause that states the relation and contains representations of BOTH endpoints (directly or through references).
Answer strictly as JSON with these fields:
{"a_anchor": "<exact substring of the POLICY where endpoint A is represented (any of its surface forms)" or "NO_ANCHOR",
 "b_anchor": "<exact substring of the POLICY where endpoint B is represented>" or "NO_ANCHOR",
 "a_in_relation": "<exact substring INSIDE the relation_text that represents endpoint A (any of its surface forms or a reference to them)>" or "NO_ANCHOR",
 "b_in_relation": "<exact substring INSIDE the relation_text that represents endpoint B>" or "NO_ANCHOR",
 "a_via_reference": "<exact substring of a reference (e.g. 'this inspection') in the POLICY that points to endpoint A>" or null,
 "b_via_reference": "<exact substring of a reference in the POLICY that points to endpoint B>" or null,
 "relation_text": "<exact minimal complete clause of the policy stating the relation between endpoint A and endpoint B>" or "NO_RELATION",
 "direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}
direction semantics: A_TO_B means A must happen first (A gates, precedes, enables or triggers B); B_TO_A means B must happen first.
IMPORTANT: a quote that merely asserts that BOTH A and B gate some third event (co-preconditions of the same operation) does NOT state a relation between A and B; use NO_RELATION in that case.
IMPORTANT: if A and B denote the SAME underlying action (one mention is a passive/nominalized/reference variant of the other, or a state describing the other), the pair is not a relation between two distinct actions; use NO_RELATION."""

E3_JUDGE_SYSTEM_V2 = """You are a strict endpoint verifier. You see ONE quoted evidence text (an exact quote from a workplace policy) and descriptions of two candidate endpoints A and B. An endpoint may be represented in the evidence DIRECTLY or through a REFERENCE (a noun phrase like 'this inspection', a pronoun, or a passive/gerund surface variant). Quote the representation if it is resolvable in the evidence; otherwise say NONE.
Answer five SEPARATE questions strictly as JSON:
{"q1_where_is_a": "<exact substring of the evidence representing endpoint A, directly or via a reference>" or "NONE",
 "q2_where_is_b": "<exact substring of the evidence representing endpoint B>" or "NONE",
 "q3_relation_between_these_two": "YES" or "NO" or "UNKNOWN",
 "q4_direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "q5_relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "SEMANTIC_LINK" or "UNKNOWN"}
IMPORTANT for q3: YES only if the evidence asserts a DIRECT relation between A and B specifically (one gates, precedes, enables, triggers or excepts the other). Coordinated alternatives (A or B), mere co-occurrence of both in one sentence, or both merely gating a THIRD event (co-preconditions of the same operation) do NOT count.
For q5 SEMANTIC_LINK: choose it when A and B denote the SAME underlying action (one is a passive, nominalized, reference or state facet of the other) - that is a semantic structure, not a normative relation between two distinct actions.
For q4: A_TO_B means A must happen first (A gates/precedes/enables B); B_TO_A means B must happen first."""


def e3_ext_user_v2(policy: str, a: dict, b: dict) -> str:
    def render(x: dict, name: str) -> str:
        forms = x.get("all_forms") or [x.get("source_span")]
        args = "; ".join(f"{g['role']}=\"{g['span']}\""
                         for g in x.get("arguments", [])[:4])
        return (f"ENDPOINT {name} is represented by these surface forms "
                f"(any of them may appear in the policy):\n"
                + "\n".join(f'  - "{f}"' for f in forms if f)
                + f"\n  (proposed type: {x.get('type', 'UNKNOWN')})" +
                (f"\n  (arguments: {args})" if args else ""))

    return (f"POLICY:\n{policy}\n\n"
            + render(a, "A") + "\n" + render(b, "B") + "\n\n"
            "Task: build the proof certificate for the candidate relation "
            "A -> B. Quote exact substrings. If A or B is represented only "
            "through a reference, give that reference in the "
            "*_via_reference field. If the policy states no relation "
            "between these two endpoints, or they are the same action, use "
            "NO_RELATION.\nAnswer strictly as JSON.")


def e3_judge_user_v2(evidence: str, a: dict, b: dict) -> str:
    def forms(x):
        return " / ".join(f'"{f}"' for f in (x.get("all_forms") or
                                             [x.get("source_span")]) if f)
    return (f"EVIDENCE (exact quote from a policy):\n\"{evidence}\"\n\n"
            f"ENDPOINT A surface forms: {forms(a)} "
            f"(type: {a.get('type', 'UNKNOWN')})\n"
            f"ENDPOINT B surface forms: {forms(b)} "
            f"(type: {b.get('type', 'UNKNOWN')})\n\n"
            "Answer the five questions strictly as JSON.")


# ------------------------------------------------------ anchor-set verify
def verify_certificate_v2(policy: str, cert: dict, a: dict, b: dict) -> dict:
    """Deterministic verification, anchor-set variant (change 3).

    a_in_relation / b_in_relation are accepted when they are verbatim
    inside the relation_text AND (approximately) represent the endpoint:
    either they overlap some member span of the endpoint in the policy, or
    they are inside a member span, or they contain a member span.
    """
    v = {"fields_present": {}, "verdict": "UNKNOWN", "reason": None}
    cert = {k: sanitize_quote(x) for k, x in (cert or {}).items()}
    rel = span_in(policy, cert.get("relation_text"))
    a_in = span_in(policy, cert.get("a_in_relation")) \
        if cert.get("a_in_relation") not in (None, "NO_ANCHOR") else None
    b_in = span_in(policy, cert.get("b_in_relation")) \
        if cert.get("b_in_relation") not in (None, "NO_ANCHOR") else None
    a_forms = [span_in(policy, f) for f in (a.get("all_forms") or
                                            [a.get("source_span")])]
    b_forms = [span_in(policy, f) for f in (b.get("all_forms") or
                                            [b.get("source_span")])]
    a_forms = [f for f in a_forms if f]
    b_forms = [f for f in b_forms if f]
    v["grounded"] = {
        "a_forms": [list(x) for x in a_forms],
        "b_forms": [list(x) for x in b_forms],
        "a_in_relation": list(a_in) if a_in else None,
        "b_in_relation": list(b_in) if b_in else None,
        "relation_text": list(rel) if rel else None}
    if cert.get("a_anchor") == "NO_ANCHOR" or cert.get("b_anchor") == \
            "NO_ANCHOR":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "endpoint_not_represented"
        return v
    if not a_forms or not b_forms:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "endpoint_form_not_verbatim"
        return v
    if cert.get("relation_text") == "NO_RELATION":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "no_relation"
        return v
    if rel is None:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "relation_text_not_verbatim"
        return v

    def represents(in_span, forms):
        """in_span (inside relation) represents the endpoint if it overlaps
        / is-inside / contains any policy-anchored member form."""
        if in_span is None:
            return False
        for f in forms:
            if in_span[0] < f[1] and f[0] < in_span[1]:    # overlap
                return True
            if f[0] <= in_span[0] and in_span[1] <= f[1]:  # inside form
                return True
            if in_span[0] <= f[0] and f[1] <= in_span[1]:  # contains form
                return True
        return False

    a_conn = represents(a_in, a_forms) and rel[0] <= a_in[0] \
        and a_in[1] <= rel[1]
    b_conn = represents(b_in, b_forms) and rel[0] <= b_in[0] \
        and b_in[1] <= rel[1]
    if not (a_conn and b_conn):
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "relation_text_not_connecting_both_endpoints"
        v["forms_in_rel"] = [a_in, b_in]
        return v
    v["verdict"] = "SUPPORTED"
    v["direction"] = cert.get("direction", "UNKNOWN")
    v["relation_type"] = cert.get("relation_type", "UNKNOWN")
    return v


# ----------------------------------------------------------------- nodes
BNORM_DIRS = sorted(OUT.glob("W1_BNORM*"), key=lambda p: p.stat().st_mtime
                    if p.exists() else 0)


def _bnorm_candidates(arm: str, case_id: str) -> list[dict]:
    for d in reversed(BNORM_DIRS):
        f = d / arm / f"{case_id}.json"
        if f.exists():
            return json.loads(f.read_text(encoding="utf-8"))["candidates"]
    return []


def build_nodes(arm: str, case: dict) -> list[dict]:
    cands = [c for c in _bnorm_candidates(arm, case["case_id"])
             if c.get("bnorm_decision") != "DROP"
             and c.get("type", "UNKNOWN") in EVENTLIKE]
    parent = {c["cid_local"]: c["cid_local"] for c in cands}

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    for c in cands:
        for r in c.get("relations", []):
            if r.get("type") in ("SAME_EVENT", "REFERENCE_OF") \
                    and r.get("to") in parent:
                union(c["cid_local"], r["to"])
    groups: dict[str, list] = defaultdict(list)
    for c in cands:
        groups[find(c["cid_local"])].append(c)
    nodes = []
    for i, (root, members) in enumerate(sorted(
            groups.items(),
            key=lambda kv: min(m.get("start") or 10 ** 6 for m in kv[1]))):
        ms = sorted([m for m in members if m.get("span")],
                    key=lambda m: m.get("start") or 10 ** 6)
        if not ms:
            continue
        types = [m.get("type", "UNKNOWN") for m in ms]
        mtype = max(set(types), key=types.count)
        nodes.append({
            "node_id": f"N{i+1:02d}",
            "members": [m["cid_local"] for m in ms],
            "span": ms[0]["span"],
            "start": ms[0]["start"],
            "type": mtype,
            "role": TYPE_TO_ROLE.get(mtype, "UNKNOWN"),
            "member_spans": [m["span"] for m in ms],
            "arguments": [a for m in ms for a in m.get("arguments", [])]})
    return nodes


def node_view(case: dict, n: dict) -> dict:
    """Change 2: all forms ordered by position; primary = first form."""
    by_name = {t["name"]: t for t in case["tools"]}
    tools = " ".join(render_tool(by_name[t]) for t in n.get(
        "governed_tools", []) if t in by_name)
    forms = n.get("member_spans") or [n["span"]]
    span = forms[0]
    if len(forms) > 1:
        span = f'"{forms[0]}" (also referenced as: ' + \
               "; ".join(f'"{x}"' for x in forms[1:]) + ")"
    return {"source_span": span, "role": n["role"],
            "all_forms": forms,
            "governed_tools": n.get("governed_tools", []),
            "span_start": n.get("start", 0), "tool_semantics": tools}


# ----------------------------------------------------------------- main
def main() -> None:
    from sentence_transformers import CrossEncoder

    arm = sys.argv[1] if len(sys.argv) > 1 else "LLM_SG"
    ev_arm = sys.argv[2] if len(sys.argv) > 2 else "E3V2"
    fname = ("level_f2_cases.json" if os.environ.get("LF_SUITE") == "f2"
             else "level_f_cases.json")
    gold = {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}
    rer = CrossEncoder("BAAI/bge-reranker-base", device="cuda",
                       max_length=512,
                       cache_folder="/workspace/guardian/hf_cache")
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / f"W1_DOWN_{arm}"
    outdir.mkdir(parents=True, exist_ok=True)

    def ask(system, user, max_tokens=600):
        for _ in range(4):
            try:
                r = client.ask(system, user, max_tokens=max_tokens)
                parsed, _err = Mistral.parse_json(r["raw"])
                if parsed:
                    return parsed
            except Exception:
                time.sleep(3)
        return {}

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
        nodes = build_nodes(arm, case)
        if not nodes:
            path.write_text(json.dumps({"case_id": cid_, "nodes": [],
                                        "edges": [], "pairs": []}) + "\n")
            continue
        # tool grounding (frozen: name-blind rerank top-1)
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

        # member-level CE gating (frozen construction)
        mpairs, owners2 = [], []
        for i in range(len(nodes)):
            for j in range(len(nodes)):
                if i >= j:
                    continue
                if set(nodes[i]["members"]) & set(nodes[j]["members"]):
                    continue  # change 6: self-loop gate
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
        edges, pair_log = [], []
        for (i, j), sc in sorted(best.items()):
            na, nb = nodes[i], nodes[j]
            rec = {"u": na["node_id"], "v": nb["node_id"],
                   "u_span": na["span"], "v_span": nb["span"],
                   "ce": round(sc, 4)}
            if sc < CE_BAND:
                rec["stage"] = "ce_band"
                pair_log.append(rec)
                continue
            ev_a, ev_b = node_view(case, na), node_view(case, nb)
            rec["stage"] = "certificate"
            cert = ask(E3_EXT_SYSTEM_V2, e3_ext_user_v2(policy, ev_a, ev_b),
                       500)
            v = verify_certificate_v2(policy, cert, ev_a, ev_b)
            rec["verify"] = v["verdict"]
            rec["verify_reason"] = v.get("reason")
            licensed, direction, rel = False, None, None
            if v["verdict"] == "SUPPORTED":
                ev = sanitize_quote(cert.get("relation_text"))
                judge = ask(E3_JUDGE_SYSTEM_V2,
                            e3_judge_user_v2(ev, ev_a, ev_b), 400)
                rec["stage"] = "judge"
                q1 = sanitize_quote(judge.get("q1_where_is_a"))
                q2 = sanitize_quote(judge.get("q2_where_is_b"))
                if judge.get("q3_relation_between_these_two") != "YES":
                    rec["judge_note"] = "verifier_q3_no"
                elif not (q1 and span_in(ev, q1) is not None
                          and q2 and span_in(ev, q2) is not None):
                    rec["judge_note"] = "verifier_q1q2_not_in_evidence"
                elif judge.get("q5_relation_type") == "SEMANTIC_LINK":
                    rec["judge_note"] = "semantic_link_routing"
                else:
                    licensed = True
                    direction = judge.get("q4_direction", "UNKNOWN")
                    rel = judge.get("q5_relation_type", "UNKNOWN")
                rec["judge"] = judge
            if not licensed:
                pair_log.append(rec)
                continue
            # change 5: UNKNOWN direction no longer bypasses DIR fallback
            if direction in (None, "UNKNOWN"):
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
                    elif (na.get("start") or 0) > (nb.get("start") or 0):
                        direction = "B_TO_A"
                    else:
                        direction = "A_TO_B"
            if rel in (None, "UNKNOWN"):
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
                          "ce": round(sc, 4),
                          "detail": {"certificate": cert, "verify": v}})
            rec["stage"] = "licensed"
            rec["direction"] = direction
            rec["relation"] = rel
            pair_log.append(rec)
        path.write_text(json.dumps({"case_id": cid_, "arm": arm,
                                    "ev_arm": ev_arm,
                                    "nodes": [{"node_id": n["node_id"],
                                               "span": n["span"],
                                               "type": n.get("type"),
                                               "start": n.get("start"),
                                               "members": n["members"],
                                               "member_spans":
                                                   n["member_spans"]}
                                              for n in nodes],
                                    "edges": edges, "pairs": pair_log},
                                   indent=1) + "\n", encoding="utf-8")
        print(cid_, len(nodes), "nodes ->", len(edges), "edges",
              f"({len(pair_log)} pairs logged)", flush=True)
    print("W1 DOWNSTREAM", arm, ev_arm, "done")


if __name__ == "__main__":
    main()
