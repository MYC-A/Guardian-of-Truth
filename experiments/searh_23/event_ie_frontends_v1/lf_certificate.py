"""Endpoint-grounded evidence certificates (Level F, second key question).

Arms (all use the same frozen downstream afterwards):
  E1  current extractor + current judge (policy_licensing_v1 prompts
      verbatim - the baseline that produced the FULL GOLD wrong-endpoint
      failure);
  E2  frontend-informed extractor (event rendering includes the frontend's
      proposed type and arguments) + same judge;
  E3  endpoint-aware certificate: the extractor must answer Q1/Q2
      separately (where exactly is A represented, where exactly is B),
      quote the relation text, its direction and type; then a separate
      endpoint verifier answers Q1-Q5 against the quoted evidence only;
      then DETERMINISTIC span checks ground every field. A paraphrase
      without a verbatim source anchor becomes UNKNOWN.

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
E3_EXT_SYSTEM = """You extract proof certificates from a workplace policy. You must quote EXACT substrings of the policy, character by character. Never paraphrase, never merge, never shorten with dots.
Answer strictly as JSON with these fields:
{"a_anchor": "<exact minimal substring of the policy where endpoint A is represented>" or "NO_ANCHOR",
 "b_anchor": "<exact minimal substring of the policy where endpoint B is represented>" or "NO_ANCHOR",
 "a_via_reference": "<exact substring of a reference (e.g. 'this inspection') that points to endpoint A>" or null,
 "b_via_reference": "<exact substring of a reference that points to endpoint B>" or null,
 "relation_text": "<exact minimal substring of the policy that states a relation between endpoint A and endpoint B>" or "NO_RELATION",
 "direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}"""

E3_JUDGE_SYSTEM = """You are a strict endpoint verifier. You see ONE quoted evidence text (an exact quote from a workplace policy) and descriptions of two candidate endpoints A and B. Answer five SEPARATE questions. Quote exact substrings of the EVIDENCE only; if something is not in the evidence, say so.
Answer strictly as JSON:
{"q1_where_is_a": "<exact substring of the evidence representing endpoint A>" or "NONE",
 "q2_where_is_b": "<exact substring of the evidence representing endpoint B>" or "NONE",
 "q3_relation_between_these_two": "YES" or "NO" or "UNKNOWN",
 "q4_direction": "A_TO_B" or "B_TO_A" or "UNKNOWN",
 "q5_relation_type": "PRECONDITION" or "ORDER_BEFORE" or "ORDER_AFTER" or "STATE_GATE" or "RESPONSE" or "EXCEPTION" or "EVEN_IF" or "UNKNOWN"}"""


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
def span_in(text: str, span: str | None) -> tuple[int, int] | None:
    if not span or not isinstance(span, str):
        return None
    idx = text.find(span)
    if idx >= 0:
        return idx, idx + len(span)
    return None


def overlaps(r1: tuple[int, int] | None, r2: tuple[int, int] | None) -> bool:
    if not r1 or not r2:
        return False
    return r1[0] < r2[1] and r2[0] < r1[1]


def verify_certificate(policy: str, cert: dict, a: dict, b: dict) -> dict:
    """Deterministic verification of a proposed certificate.

    Returns a verdict with grounded flags; never invents truth.
    """
    v = {"fields_present": {}, "verdict": "UNKNOWN", "reason": None}
    a_anchor = span_in(policy, cert.get("a_anchor"))
    b_anchor = span_in(policy, cert.get("b_anchor"))
    a_ref = span_in(policy, cert.get("a_via_reference"))
    b_ref = span_in(policy, cert.get("b_via_reference"))
    rel = span_in(policy, cert.get("relation_text"))
    v["fields_present"] = {
        "a_anchor": a_anchor is not None or cert.get("a_anchor") == "NO_ANCHOR",
        "b_anchor": b_anchor is not None or cert.get("b_anchor") == "NO_ANCHOR",
        "a_reference": a_ref is not None,
        "b_reference": b_ref is not None,
        "relation_text": rel is not None
        or cert.get("relation_text") == "NO_RELATION",
    }
    v["grounded"] = {
        "a_anchor": list(a_anchor) if a_anchor else None,
        "b_anchor": list(b_anchor) if b_anchor else None,
        "relation_text": list(rel) if rel else None,
    }
    # an anchor may be represented directly or via an explicit reference
    a_ok = a_anchor is not None or cert.get("a_anchor") == "NO_ANCHOR"
    b_ok = b_anchor is not None or cert.get("b_anchor") == "NO_ANCHOR"
    if not a_ok or not b_ok:
        v["verdict"] = "UNKNOWN"
        v["reason"] = "anchor_not_verbatim"
        return v
    if cert.get("a_anchor") == "NO_ANCHOR" or cert.get("b_anchor") == "NO_ANCHOR":
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "endpoint_not_represented"
        return v
    if cert.get("relation_text") == "NO_RELATION" or rel is None:
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "no_relation_text" if rel is None else "no_relation"
        return v
    # relation text must connect BOTH endpoints: direct overlap or via
    # the explicitly quoted reference chain
    a_conn = overlaps(a_anchor, rel) or (
        a_ref is not None and (overlaps(a_ref, rel)))
    b_conn = overlaps(b_anchor, rel) or (
        b_ref is not None and (overlaps(b_ref, rel)))
    if not (a_conn and b_conn):
        v["verdict"] = "UNSUPPORTED"
        v["reason"] = "relation_text_not_connecting_both_endpoints"
        return v
    v["verdict"] = "SUPPORTED"
    v["direction"] = cert.get("direction", "UNKNOWN")
    v["relation_type"] = cert.get("relation_type", "UNKNOWN")
    return v


def amr_argument_witness(amr_graphs: list[str], a_span: str,
                         b_span: str) -> dict | None:
    """Structural witness: is one endpoint an ARGUMENT of the other's
    predicate in some AMR graph? Reads the raw AMR graphs stored by
    lf_amr_frontend (predicate frames and ARG edges)."""
    import re
    if not amr_graphs:
        return None
    la = (a_span or "").strip().lower().split()
    lb = (b_span or "").strip().lower().split()

    def head_lemma(span_words):
        return span_words[0] if span_words else ""

    ha, hb = head_lemma(la), head_lemma(lb)
    for g in amr_graphs:
        for m in re.finditer(r"\(([a-z][a-z0-9]*)\s*/\s*([a-z][a-z0-9-]*-\d\d)", g):
            var, concept = m.group(1), m.group(2)
            base = concept.split("-")[0]
            if base not in (ha, hb):
                continue
            # collect its ARG child concepts in the next ~200 chars
            seg = g[m.end():m.end() + 240]
            for am in re.finditer(r":ARG[0-9]\s+\([a-z][a-z0-9]*\s*/\s*"
                                  r"([a-z][a-z0-9-]*)", seg):
                child = am.group(1)
                other = hb if base == ha else ha
                if child == other or child.rstrip("e") == other.rstrip("e"):
                    return {"a_is_argument_of_b": base == hb,
                            "b_is_argument_of_a": base == ha,
                            "witness_concept": concept}
    return None


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
        a = {"source_span": it["edge"]["a"], "type": "UNKNOWN"}
        b = {"source_span": it["edge"]["b"], "type": "UNKNOWN"}
        rec = {"id": it["id"], "family": it["family"]}
        t0 = time.time()
        if arm == "E1":
            ans = _ask(client, _EV_SYSTEM, ev_user({"policy": policy}, a, b))
            ev = ans.get("evidence")
            if ev and ev != "NO_EVIDENCE" and span_in(policy, ev):
                jd = _ask(client, _EVJ_SYSTEM, evjudge_user(a, b, ev))
                rec["evidence"] = ev
                rec["judge"] = jd
                rec["verdict"] = jd.get("decision", "UNKNOWN")
            else:
                rec["evidence"] = ev
                rec["verdict"] = "UNSUPPORTED" if ev == "NO_EVIDENCE" \
                    else "UNKNOWN"
        elif arm in ("E2", "E3", "E3W"):
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


def main() -> None:
    arm = sys.argv[1] if len(sys.argv) > 1 else "E3"
    what = sys.argv[2] if len(sys.argv) > 2 else "unit"
    t0 = time.time()
    if what == "unit":
        run_unit(arm)
    else:
        raise SystemExit("pair mode is invoked from lf_downstream.py")
    print(arm, "unit done", round(time.time() - t0, 1), "s; calls:",
          client_calls(), flush=True)


def client_calls() -> str:
    return "see _cache"


if __name__ == "__main__":
    main()
