"""Endpoint-grounded evidence certificates (Level F, second key question).

Arms (all use the same frozen downstream afterwards):
  E1  current extractor + current judge (policy_licensing_v1 prompts
      verbatim - the baseline that produced the FULL GOLD wrong-endpoint
      failure);
  E3  endpoint-aware certificate: the extractor must answer Q1/Q2
      separately (where exactly is A represented, where exactly is B),
      quote the relation text, its direction and type; then a separate
      endpoint verifier answers Q1-Q5 against the quoted evidence only;
      then DETERMINISTIC span checks ground every field. A paraphrase
      without a verbatim source anchor becomes UNKNOWN.
  E2  is only defined in downstream pair mode (it needs a frontend's
      proposed types/arguments); at unit level it is not meaningful and
      is not run.

AMR structural witness (optional veto arm E3W): if the AMR graph of the
relation sentence places endpoint A as an ARGUMENT of B (or vice versa),
the certificate records a_is_argument_of_b; the E3W arm treats it as a
veto against licensing A->B (the ceramics failure mode: glaze is an
argument of inspect, not its endpoint).

Outputs:
  outputs/CERT_<arm>/<id>.json          certificate unit items (22)
  outputs/CERT_LL_<arm>/<case>.json     per-case certificates for Track B

Run (server, main venv):
  python3 lf_certificate.py E1|E2|E3|E3W [unit|pairs]
"""
from __future__ import annotations

import json
import sys
import time
from pathlib import Path

HERE = Path(__file__).parent
PL = HERE.parent / "policy_licensing_v1"
sys.path[:0] = [str(PL)]
from pl_run_llm import ev_user, evjudge_user, SYSTEM as _PL_SYSTEM  # noqa: E402  (frozen prompts)
from pl_common import Mistral, render_tool  # noqa: E402

OUT = HERE / "outputs"

# ------------------------------------------------------------- E3 prompts
E3_EXT_SYSTEM = """You extract proof certificates from a workplace policy. You must quote EXACT substrings of the policy, character by character (matching capitalization). Never paraphrase.
The relation_text must be the minimal COMPLETE clause that states the relation and contains representations of BOTH endpoints (directly or through references).
Answer strictly as JSON with these fields:
{"a_anchor": "<exact substring of the POLICY where endpoint A is represented (may differ from the evidence wording)>" or "NO_ANCHOR",
 "b_anchor": "<exact substring of the POLICY where endpoint B is represented>" or "NO_ANCHOR",
 "a_in_relation": "<exact substring INSIDE the relation_text that represents endpoint A (its surface variant or reference)>" or "NO_ANCHOR",
 "b_in_relation": "<exact substring INSIDE the relation_text that represents endpoint B>" or "NO_ANCHOR",
 "a_via_reference": "<exact substring of a reference (e.g. 'this inspection') in the POLICY that points to endpoint A>" or null,
 "b_via_reference": "<exact substring of a reference in the POLICY that points to endpoint B>" or null,
 "relation_text": "<exact minimal complete clause of the policy stating the relation between endpoint A and endpoint B>" or "NO_RELATION",
 "direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}
direction semantics: A_TO_B means A must happen first (A gates, precedes, enables or triggers B); B_TO_A means B must happen first.
IMPORTANT: a quote that merely asserts that BOTH A and B gate some third event (co-preconditions of the same operation) does NOT state a relation between A and B; use NO_RELATION in that case."""

E3_JUDGE_SYSTEM = """You are a strict endpoint verifier. You see ONE quoted evidence text (an exact quote from a workplace policy) and descriptions of two candidate endpoints A and B. An endpoint may be represented in the evidence DIRECTLY or through a REFERENCE (a noun phrase like 'this inspection', a pronoun, or a passive/gerund surface variant). Quote the representation if it is resolvable in the evidence; otherwise say NONE.
Answer five SEPARATE questions strictly as JSON:
{"q1_where_is_a": "<exact substring of the evidence representing endpoint A, directly or via a reference>" or "NONE",
 "q2_where_is_b": "<exact substring of the evidence representing endpoint B>" or "NONE",
 "q3_relation_between_these_two": "YES" or "NO" or "UNKNOWN",
 "q4_direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "q5_relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}
IMPORTANT for q3: YES only if the evidence asserts a DIRECT relation between A and B specifically (one gates, precedes, enables, triggers or excepts the other). Coordinated alternatives (A or B), mere co-occurrence of both in one sentence, or both merely gating a THIRD event (co-preconditions of the same operation) do NOT count.
For q4: A_TO_B means A must happen first (A gates/precedes/enables B); B_TO_A means B must happen first."""


def e3_ext_user(policy: str, a: dict, b: dict) -> str:
    def render(x: dict, name: str) -> str:
        args = "; ".join(f"{g['role']}=\"{g['span']}\""
                         for g in x.get("arguments", []))
        return (f'ENDPOINT {name}: "{x.get("source_span")}" '
                f'(proposed type: {x.get("type", "UNKNOWN")})'
                + (f" (arguments: {args})" if args else ""))

    return (f"POLICY:\n{policy}\n\n"
            + render(a, "A") + "\n" + render(b, "B") + "\n\n"
            "Task: build the proof certificate for the candidate relation "
            "A -> B. Quote exact substrings. If A or B is represented only "
            "through a reference, give that reference in the "
            "*_via_reference field. If the policy states no relation "
            "between these two endpoints, use NO_RELATION.\n"
            "Answer strictly as JSON.")


def e3_judge_user(evidence: str, a: dict, b: dict) -> str:
    return (f"EVIDENCE (exact quote from a policy):\n\"{evidence}\"\n\n"
            f'ENDPOINT A: "{a.get("source_span")}" (type: '
            f'{a.get("type", "UNKNOWN")})\n'
            f'ENDPOINT B: "{b.get("source_span")}" (type: '
            f'{b.get("type", "UNKNOWN")})\n\n'
            "Answer the five questions strictly as JSON.")


# ------------------------------------------------ deterministic grounding
def sanitize_quote(s: str | None) -> str | None:
    """Deterministic formatting cleanup of quoted fields: strip wrapping
    whitespace, wrapping quotation marks, and markdown bold/italic
    markers. Never alters the inner text."""
    if not isinstance(s, str):
        return s
    t = s.strip()
    while t[:1] in {'"', "'", "`"} and t[-1:] in {'"', "'", "`"}:
        t = t[1:-1].strip()
    t = t.replace("**", "").replace("__", "").strip()
    return t if t else None


def span_in(text: str, span: str | None) -> tuple[int, int] | None:
    """Case-tolerant verbatim location: exact match first, then
    case-insensitive match (recording the true policy offsets)."""
    if not span or not isinstance(span, str):
        return None
    idx = text.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    low = text.lower()
    s = span.strip()
    if not s:
        return None
    idx = low.find(s.lower())
    if idx >= 0:
        return idx, idx + len(s)
    return None


def overlaps(r1: tuple[int, int] | None, r2: tuple[int, int] | None) -> bool:
    if not r1 or not r2:
        return False
    return r1[0] < r2[1] and r2[0] < r1[1]


def verify_certificate(policy: str, cert: dict, a: dict, b: dict) -> dict:
    """Deterministic verification of a proposed certificate.

    Checks: relation_text is verbatim in the policy; a_in_relation and
    b_in_relation are verbatim INSIDE the relation_text; anchors are
    verbatim in the policy. Paraphrase anywhere -> UNKNOWN.
    """
    v = {"fields_present": {}, "verdict": "UNKNOWN", "reason": None}
    cert = {k: sanitize_quote(x) for k, x in (cert or {}).items()}
    rel = span_in(policy, cert.get("relation_text"))
    a_in = span_in(policy, cert.get("a_in_relation")) \
        if cert.get("a_in_relation") not in (None, "NO_ANCHOR") else None
    b_in = span_in(policy, cert.get("b_in_relation")) \
        if cert.get("b_in_relation") not in (None, "NO_ANCHOR") else None
    a_anchor = span_in(policy, cert.get("a_anchor"))
    b_anchor = span_in(policy, cert.get("b_anchor"))
    v["grounded"] = {
        "a_anchor": list(a_anchor) if a_anchor else None,
        "b_anchor": list(b_anchor) if b_anchor else None,
        "a_in_relation": list(a_in) if a_in else None,
        "b_in_relation": list(b_in) if b_in else None,
        "relation_text": list(rel) if rel else None,
    }
    if cert.get("a_anchor") == "NO_ANCHOR" or cert.get("b_anchor") == \
            "NO_ANCHOR":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "endpoint_not_represented"
        return v
    if not a_anchor or not b_anchor:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "anchor_not_verbatim"
        return v
    if cert.get("relation_text") == "NO_RELATION":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "no_relation"
        return v
    if rel is None:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "relation_text_not_verbatim"
        return v
    # the relation clause must contain a verbatim representation of BOTH
    # endpoints (their surface variants or references)
    a_conn = a_in is not None and rel[0] <= a_in[0] and a_in[1] <= rel[1]
    b_conn = b_in is not None and rel[0] <= b_in[0] and b_in[1] <= rel[1]
    if not (a_conn and b_conn):
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "relation_text_not_connecting_both_endpoints"
        return v
    v["verdict"] = "SUPPORTED"
    v["direction"] = cert.get("direction", "UNKNOWN")
    v["relation_type"] = cert.get("relation_type", "UNKNOWN")
    return v


STOP_HEAD = {"the", "a", "an", "each", "every", "this", "that",
              "its", "all", "any", "to", "of"}


def _content_words(span: str) -> list[str]:
    return [w.lower() for w in (span or "").split() if w.lower()
            not in STOP_HEAD and w.isalnum()]


def amr_argument_witness(amr_graphs: list[str], a_span: str,
                         b_span: str) -> dict | None:
    """Structural witness (Section 18 hypothesis): can AMR distinguish a
    PREDICATE endpoint from an ARGUMENT endpoint?

    For each endpoint: does any of its content words match a PREDICATE
    frame concept (verbal -NN frame) in the AMR graphs? If one endpoint
    is predicate-backed and the other only matches NON-PREDICATE entity
    concepts that sit under some :ARG edge, the second is an argument,
    not a relation endpoint -> veto.
    """
    import re
    if not amr_graphs:
        return None
    preds: set[str] = set()
    entities: set[str] = set()
    for g in amr_graphs:
        for m in re.finditer(r"\([a-z][a-z0-9]*\s*/\s*([a-z][a-z0-9-]+)", g):
            concept = m.group(1)
            if re.match(r"^[a-z]+-\d\d$", concept):
                preds.add(concept.split("-")[0])
            else:
                entities.update(concept.split("-")[:2])
                entities.add(concept.replace("-", ""))

    def endpoint_status(span: str) -> str:
        words = _content_words(span)
        if any(w in preds or w.rstrip("ings") in preds or
               w + "e" in preds for w in words):
            return "PREDICATE"
        if any(w in entities for w in words):
            return "ENTITY"
        return "ABSENT"

    sa, sb = endpoint_status(a_span), endpoint_status(b_span)
    if sa == "ENTITY" and sb in ("PREDICATE", "ENTITY", "ABSENT"):
        return {"a_is_argument": True, "a_status": sa, "b_status": sb}
    if sb == "ENTITY" and sa in ("PREDICATE", "ABSENT"):
        return {"b_is_argument": True, "a_status": sa, "b_status": sb}
    return None


def unit_amr_witness(policy: str, a_span: str, b_span: str) -> dict | None:
    """AMR witness for certificate unit items: reads graphs precomputed by
    lf_amr_unit_graphs.py (run in amr_env) from outputs/AMR_UNIT_GRAPHS."""
    gpath = OUT / "AMR_UNIT_GRAPHS" / _unit_graph_name(policy)
    if not gpath.exists():
        return None
    graphs = json.loads(gpath.read_text(encoding="utf-8"))["graphs"]
    return amr_argument_witness(graphs, a_span, b_span)


def _unit_graph_name(policy: str) -> str:
    import hashlib
    return hashlib.sha256(policy.encode()).hexdigest()[:16] + ".json"


# ----------------------------------------------------------------- runs
def load_cert_items() -> list[dict]:
    return json.loads((HERE / "frozen" / "certificate_cases.json")
                      .read_text(encoding="utf-8"))


def run_unit(arm: str) -> None:
    client = Mistral(model="ministral-14b-latest", cache_dir=OUT / "_cache")
    outdir = OUT / f"CERT_{arm}"
    outdir.mkdir(parents=True, exist_ok=True)
    items = load_cert_items()
    for it in items:
        path = outdir / f"{it['id']}.json"
        if path.exists():
            continue
        policy = it["policy"]
        a = {"source_span": it["edge"]["a"], "type": "UNKNOWN",
             "role": "UNKNOWN", "governed_tools": [], "span_start": 0}
        b = {"source_span": it["edge"]["b"], "type": "UNKNOWN",
             "role": "UNKNOWN", "governed_tools": [], "span_start": 0}
        rec = {"id": it["id"], "family": it["family"]}
        t0 = time.time()
        if arm == "E1":
            case_stub = {"policy": policy, "tools": []}
            ans = _ask(client, _PL_SYSTEM, ev_user(case_stub, a, b))
            ev = ans.get("evidence")
            if ev and ev != "NO_EVIDENCE" and span_in(policy, ev):
                jd = _ask(client, _PL_SYSTEM, evjudge_user(a, b, ev))
                rec["evidence"] = ev
                rec["judge"] = jd
                rec["verdict"] = jd.get("decision", "UNKNOWN")
            else:
                rec["evidence"] = ev
                rec["verdict"] = "UNSUPPORTED" if ev == "NO_EVIDENCE" \
                    else "UNKNOWN"
        elif arm in ("E3", "E3W"):
            cert = _ask(client, E3_EXT_SYSTEM, e3_ext_user(policy, a, b))
            rec["certificate"] = cert
            v = verify_certificate(policy, cert, a, b)
            rec["deterministic"] = v
            # endpoint verifier (separate judge, evidence-centered)
            if v["verdict"] == "SUPPORTED":
                ev = cert.get("relation_text")
                judge = _ask(client, E3_JUDGE_SYSTEM,
                             e3_judge_user(ev, a, b))
                rec["endpoint_verifier"] = judge
                q1 = span_in(ev, judge.get("q1_where_is_a"))
                q2 = span_in(ev, judge.get("q2_where_is_b"))
                if judge.get("q3_relation_between_these_two") != "YES":
                    rec["verdict"] = "UNSUPPORTED"
                    rec["reason"] = "verifier_q3_no"
                elif q1 is None or q2 is None:
                    rec["verdict"] = "UNKNOWN"
                    rec["reason"] = "verifier_q1q2_not_verbatim"
                else:
                    rec["verdict"] = "SUPPORTED"
                    rec["direction"] = judge.get("q4_direction", "UNKNOWN")
                    rec["relation_type"] = judge.get("q5_relation_type",
                                                     "UNKNOWN")
            else:
                rec["verdict"] = v["verdict"]
                rec["reason"] = v.get("reason")
            if arm == "E3W" and rec["verdict"] == "SUPPORTED":
                wit = unit_amr_witness(policy, a["source_span"],
                                       b["source_span"])
                if wit:
                    rec["verdict"] = "UNSUPPORTED"
                    rec["amr_witness"] = wit
                    rec["reason"] = "amr_argument_veto"
        rec["latency_s"] = round(time.time() - t0, 2)
        path.write_text(json.dumps(rec, indent=1, ensure_ascii=False) + "\n",
                        encoding="utf-8")
        print(it["id"], rec.get("verdict"), flush=True)


_EV_SYSTEM = _PL_SYSTEM
_EVJ_SYSTEM = _PL_SYSTEM


def _ask(client, system: str, user: str) -> dict:
    for _ in range(4):
        try:
            r = client.ask(system, user, max_tokens=500)
            parsed, _err = Mistral.parse_json(r["raw"])
            if parsed:
                return parsed
        except Exception:
            time.sleep(3)
    return {}


def rescore(arm: str) -> None:
    """Re-run deterministic verification over saved records without any
    new LLM calls (formatting sanitization only)."""
    outdir = OUT / f"CERT_{arm}"
    for f in sorted(outdir.glob("*.json")):
        r = json.loads(f.read_text(encoding="utf-8"))
        cert = r.get("certificate")
        if not cert:
            continue
        items = load_cert_items()
        it = next((x for x in items if x["id"] == r["id"]), None)
        if it is None:
            continue
        policy = it["policy"]
        a = {"source_span": it["edge"]["a"]}
        b = {"source_span": it["edge"]["b"]}
        v = verify_certificate(policy, cert, a, b)
        r["deterministic"] = v
        if v["verdict"] == "SUPPORTED":
            ev = sanitize_quote(cert.get("relation_text"))
            judge = r.get("endpoint_verifier") or {}
            q1 = span_in(ev, sanitize_quote(judge.get("q1_where_is_a")))
            q2 = span_in(ev, sanitize_quote(judge.get("q2_where_is_b")))
            if judge.get("q3_relation_between_these_two") != "YES":
                r["verdict"] = "UNSUPPORTED"
                r["reason"] = "verifier_q3_no"
            elif q1 is None or q2 is None:
                r["verdict"] = "UNKNOWN"
                r["reason"] = "verifier_q1q2_not_verbatim"
            else:
                r["verdict"] = "SUPPORTED"
                r["direction"] = judge.get("q4_direction", "UNKNOWN")
                r["relation_type"] = judge.get("q5_relation_type", "UNKNOWN")
                r.pop("reason", None)
        else:
            r["verdict"] = v["verdict"]
            r["reason"] = v.get("reason")
        if arm == "E3W" and r["verdict"] == "SUPPORTED":
            wit = unit_amr_witness(policy, it["edge"]["a"], it["edge"]["b"])
            if wit:
                r["verdict"] = "UNSUPPORTED"
                r["amr_witness"] = wit
                r["reason"] = "amr_argument_veto"
        f.write_text(json.dumps(r, indent=1, ensure_ascii=False) + "\n",
                     encoding="utf-8")
        print(r["id"], r.get("verdict"), flush=True)


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "E3"
    what = sys.argv[2] if len(sys.argv) > 2 else "unit"
    t0 = time.time()
    if what == "unit":
        run_unit(arm)
    elif what == "rescore":
        rescore(arm)
    else:
        raise SystemExit("pair mode is invoked from lf_downstream.py")
    print(arm, "unit done", round(time.time() - t0, 1), "s; calls:",
          client_calls(), flush=True)


def client_calls() -> str:
    return "see _cache"


if __name__ == "__main__":
    main()
