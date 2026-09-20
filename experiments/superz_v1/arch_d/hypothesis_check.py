"""Architecture D — local formal verification of a specific violation hypothesis.

Instead of formalizing the whole policy, one hypothesis at a time:
  1. hypothesis source: an atomic suspicion (from B1) or a dedicated prompt
  2. the LLM maps the hypothesis to a TYPED template:
     - the triggering action (observed tool call / statement in response)
     - applicability conditions with explicit evidence bindings to tool
       result fields (numeric ops, flags, absence)
     - exceptions with evidence bindings
     - the anchored rule span (verified byte-exact)
  3. Python resolves each condition against the trace fact ledger with
     entity-scoped bindings -> ok / failed / unknown
  4. Clingo re-verifies the assembled program (formal cross-check with
     explicit three-valued condition states)
  5. Verdict: CONFIRMED only if all conditions positively hold AND every
     exception is positively absent. Any unknown -> UNRESOLVED (never a
     silent stricter rule). Condition failing -> REFUTED.

No effect invention: tool success does not prove state change; values come
only from explicit tool result fields.
"""
from __future__ import annotations

import json
import re
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from common.trace_parser import Trace, parse_trace
from common.zai_client import chat, extract_json
from common.clingo_bridge import solve

HERE = Path(__file__).resolve().parent

FORMALIZE_SYS = """You convert ONE suspected violation into a typed, checkable template.

You receive:
- POLICY (full text),
- the final agent RESPONSE,
- ONE suspicion (atomic alleged violation),
- the ordered TOOL EVENTS (calls and results, with parsed fields).

Return strictly JSON:
{
 "rule_quote": "<exact quote of the policy clause that makes this a violation>",
 "hypothesis": "<one sentence>",
 "trigger": {"kind": "observed_call"|"statement",
             "tool": "<tool name or null>",
             "match_response_fragment": "<exact fragment of response that triggers>"},
 "conditions": [
   {"id": "c1", "desc": "...", "kind": "numeric|flag|absence|temporal",
    "evidence": {"tool": "<tool that reports the field>", "field": "<field name or path>",
                 "entity_ref": "<which argument of the trigger call links to this evidence, e.g. 'order' or 'account'>",
                 "op": ">|<|>=|<=|==|!=", "value": <number or string>},
    "required": true}
 ],
 "exceptions": [
   {"id": "e1", "desc": "...", "evidence": {"tool": "...", "field": "...", "entity_ref": "...",
                 "present_value": "<value that would mean the exception applies>"}}
 ]
}

Rules:
- Bind every condition/exception to a CONCRETE field of a CONCRETE tool result that is
  able to report it. If nothing in the tool outputs can report the condition, set
  "evidence": null and "required": false, and add "unverifiable": true.
- Do NOT invent conditions the policy does not state.
- Quote the policy clause exactly.
"""


def _entity_values(payload, field: str) -> list:
    """All values under a field name (searched recursively) in a payload."""
    found = []

    def walk(obj):
        if isinstance(obj, dict):
            for k, v in obj.items():
                if k == field:
                    found.append(v)
                walk(v)
        elif isinstance(obj, list):
            for v in obj:
                walk(v)

    walk(payload)
    return found


def _coerce(v):
    if isinstance(v, bool):
        return v
    if isinstance(v, (int, float)):
        return v
    s = str(v).strip().replace(",", ".")
    try:
        f = float(s)
        return int(f) if f == int(f) else f
    except (ValueError, TypeError):
        return str(v)


def _cmp(left, op: str, right) -> bool:
    l, r = _coerce(left), _coerce(right)
    if isinstance(l, str) or isinstance(r, str):
        ls, rs = str(l).strip(), str(r).strip()
        return {
            "==": ls == rs, "!=": ls != rs, ">": ls > rs, "<": ls < rs,
            ">=": ls >= rs, "<=": ls <= rs,
        }.get(op, False)
    return {
        "==": l == r, "!=": l != r, ">": l > r, "<": l < r,
        ">=": l >= r, "<=": l <= r,
    }.get(op, False)


def _extract_claim_from_response(trace: Trace, claim_spec: dict) -> dict:
    """Extract a claimed value from the response text.

    claim_spec: {"extract": "number|string", "near": "<fragment to locate>"}
    Returns {"found": bool, "value": ...}.
    """
    resp = trace.response_segment
    if resp is None:
        return {"found": False, "value": None}
    near = claim_spec.get("near", "")
    base = resp.text
    if near:
        i = base.find(near)
        if i >= 0:
            base = base[max(0, i - 60) : i + 160]
    if claim_spec.get("extract") == "number":
        # exclude ID-like tokens: numbers glued to letters/hyphen (ACC-100, HAT078)
        m = re.search(r"(?<![\w/-])\d[\d\s]*(?:[.,]\d+)?(?![\w-])", base)
        if m:
            return {"found": True, "value": _coerce(m.group(0))}
        return {"found": False, "value": None}
    # string: whole located fragment
    return {"found": True, "value": base.strip()[:200]}


def resolve_condition(cond: dict, trace: Trace, trigger_args: dict) -> dict:
    """Resolve one condition against entity-scoped tool evidence."""
    if cond.get("unverifiable") or not cond.get("evidence"):
        return {"id": cond.get("id"), "status": "unknown", "why": "no evidence binding"}
    ev = cond["evidence"]
    # claim-match condition: compare response claim vs evidence value
    if cond.get("kind") == "claim_match":
        claim = _extract_claim_from_response(trace, cond.get("claim") or {})
        tool, fld = ev.get("tool"), ev.get("field")
        ent_ref = ev.get("entity_ref")
        ent_val = trigger_args.get(ent_ref) if (ent_ref and isinstance(trigger_args, dict)) else None
        found_vals = []
        for e in trace.tool_events:
            if e.kind != "RESPONSE" or e.payload is None:
                continue
            if tool and e.tool != tool:
                continue
            vals = _entity_values(e.payload, fld)
            if vals:
                payload_str = json.dumps(e.payload, ensure_ascii=False)
                scoped = ent_val is not None and str(ent_val) in payload_str
                found_vals.append({"vals": vals, "seq": e.seq, "scoped": scoped})
        if not claim.get("found"):
            return {"id": cond.get("id"), "status": "unknown", "why": "claim not extractable from response"}
        if not found_vals:
            return {"id": cond.get("id"), "status": "unknown", "why": f"field {fld} not reported"}
        scoped = [x for x in found_vals if x["scoped"]]
        latest = max(scoped or found_vals, key=lambda x: x["seq"])
        observed = latest["vals"][-1]
        # compare claim vs observed with the given op
        ok = _cmp(claim["value"], ev.get("op", "=="), observed) or _cmp(
            observed, ev.get("op", "=="), claim["value"]
        )
        # normalize equality both ways
        if ev.get("op", "==") in ("==", "!="):
            eq = _coerce(claim["value"]) == _coerce(observed)
            ok = eq if ev.get("op") == "==" else not eq
        return {
            "id": cond.get("id"),
            "status": "ok" if ok else "failed",
            "observed": observed,
            "claimed": claim["value"],
            "seq": latest["seq"],
            "scoped": latest["scoped"],
        }
    tool, fld = ev.get("tool"), ev.get("field")
    ent_ref = ev.get("entity_ref")
    # entity key value from trigger args (e.g. entity_ref='order' -> args['order'])
    ent_val = None
    if ent_ref and isinstance(trigger_args, dict):
        ent_val = trigger_args.get(ent_ref)
    found_vals = []
    for e in trace.tool_events:
        if e.kind != "RESPONSE" or e.payload is None:
            continue
        if tool and e.tool != tool:
            continue
        vals = _entity_values(e.payload, fld)
        if vals:
            # entity scoping: if the payload contains the entity id, prefer it
            payload_str = json.dumps(e.payload, ensure_ascii=False)
            scoped = ent_val is not None and str(ent_val) in payload_str
            found_vals.append({"vals": vals, "seq": e.seq, "scoped": scoped})
    if not found_vals:
        return {"id": cond.get("id"), "status": "unknown", "why": f"field {fld} not reported by any {tool} result"}
    # prefer scoped hits; among them take the LATEST (max seq)
    scoped = [x for x in found_vals if x["scoped"]]
    chosen = scoped or found_vals
    latest = max(chosen, key=lambda x: x["seq"])
    val = latest["vals"][-1]
    op, target = ev.get("op", "=="), ev.get("value")
    ok = _cmp(val, op, target)
    return {
        "id": cond.get("id"),
        "status": "ok" if ok else "failed",
        "observed": val,
        "expected": f"{op} {target}",
        "seq": latest["seq"],
        "scoped": latest["scoped"],
    }


def resolve_exception(exc: dict, trace: Trace, trigger_args: dict) -> dict:
    """Exception resolution: applies / absent / unknown."""
    ev = exc.get("evidence")
    if not ev:
        return {"id": exc.get("id"), "status": "unknown", "why": "no evidence binding"}
    tool, fld = ev.get("tool"), ev.get("field")
    ent_ref = ev.get("entity_ref")
    ent_val = trigger_args.get(ent_ref) if (ent_ref and isinstance(trigger_args, dict)) else None
    found = []
    for e in trace.tool_events:
        if e.kind != "RESPONSE" or e.payload is None:
            continue
        if tool and e.tool != tool:
            continue
        vals = _entity_values(e.payload, fld)
        if vals:
            payload_str = json.dumps(e.payload, ensure_ascii=False)
            scoped = ent_val is not None and str(ent_val) in payload_str
            found.append({"vals": vals, "seq": e.seq, "scoped": scoped})
    if not found:
        return {"id": exc.get("id"), "status": "unknown", "why": f"{fld} not observable"}
    scoped = [x for x in found if x["scoped"]]
    latest = max(scoped or found, key=lambda x: x["seq"])
    pv = str(ev.get("present_value", "")).strip()
    vals_str = [str(v).strip() for v in latest["vals"]]
    # applies if present_value is contained/equal in any value
    applies = any(pv and (pv == s or pv in s) for s in vals_str)
    # explicitly absent if the field exists with an empty/false/different enum
    explicitly_absent = any(
        s in ("", "false", "False", "none", "None", "null", "no", "not_received") for s in vals_str
    )
    if applies:
        return {"id": exc.get("id"), "status": "applies", "observed": vals_str, "seq": latest["seq"]}
    if explicitly_absent:
        return {"id": exc.get("id"), "status": "absent", "observed": vals_str, "seq": latest["seq"]}
    return {"id": exc.get("id"), "status": "unknown", "observed": vals_str,
            "why": "field present but neither matches present_value nor explicit absence"}


def build_asp(hyp: dict, cond_results: list[dict], exc_results: list[dict]) -> str:
    """ASP cross-check program with explicit three-valued states."""
    lines = ["% hypothesis cross-check (architecture D)"]
    for c in cond_results:
        st = {"ok": "cond_ok", "failed": "cond_failed", "unknown": "cond_unknown"}.get(c["status"], "cond_unknown")
        lines.append(f"{st}({c.get('id', 'c')}).")
    for e in exc_results:
        st = {"applies": "exc_applies", "absent": "exc_absent", "unknown": "exc_unknown"}.get(e["status"], "exc_unknown")
        lines.append(f"{st}({e.get('id', 'e')}).")
    lines.append("""
violation_confirmed :- trigger_observed, cond_ok(C1), not cond_unknown_missing, not exc_applies_any.
% engine: require ALL required conditions ok and NO unknown among them, and
% no exception applies; any unknown -> unresolved, never confirmed.
""")
    # simpler and auditable: compute in ASP via counts
    lines.append("""
n_unknown_cond(N) :- N = #count { C : cond_unknown(C) }.
n_failed_cond(N) :- N = #count { C : cond_failed(C) }.
n_exc_applies(N) :- N = #count { E : exc_applies(E) }.
n_exc_unknown(N) :- N = #count { E : exc_unknown(E) }.

verdict(confirmed) :- trigger_observed, n_unknown_cond(0), n_failed_cond(0), n_exc_applies(0), n_exc_unknown(0).
verdict(refuted) :- n_failed_cond(N), N > 0.
verdict(refuted) :- n_exc_applies(N), N > 0.
verdict(unresolved) :- not verdict(confirmed), not verdict(refuted).
trigger_observed.
""")
    return "\n".join(lines)


def check_hypothesis(hyp: dict, trace: Trace) -> dict:
    """Full typed check + ASP cross-check for one formalized hypothesis."""
    # verify rule quote is real
    from arch_b.fact_ledger import locate_quote
    rq = hyp.get("rule_quote", "")
    loc = locate_quote(trace.policy_text, rq)
    rule_grounded = loc["found"]

    # trigger: find the tool call in the response segment
    trig = hyp.get("trigger", {})
    trigger_observed = False
    trigger_args = {}
    if trig.get("kind") == "observed_call" and trig.get("tool"):
        for e in trace.tool_events:
            if e.kind == "CALL" and e.tool == trig["tool"] and e.seg_idx == trace.response_segment.idx:
                trigger_observed = True
                trigger_args = e.payload if isinstance(e.payload, dict) else {}
                break
    else:
        # statement trigger: match_response_fragment must exist in response
        frag = trig.get("match_response_fragment", "")
        if frag and trace.response_segment and locate_quote(trace.response_segment.text, frag)["found"]:
            trigger_observed = True

    cond_results = [resolve_condition(c, trace, trigger_args) for c in hyp.get("conditions", [])]
    exc_results = [resolve_exception(e, trace, trigger_args) for e in hyp.get("exceptions", [])]

    # Python verdict
    if not trigger_observed:
        verdict = "REFUTED_NO_TRIGGER"
    elif any(c["status"] == "failed" for c in cond_results):
        verdict = "REFUTED_CONDITION_FAILS"
    elif any(e["status"] == "applies" for e in exc_results):
        verdict = "REFUTED_EXCEPTION_APPLIES"
    elif any(c["status"] == "unknown" for c in cond_results) or any(
        e["status"] == "unknown" for e in exc_results
    ):
        verdict = "UNRESOLVED_UNKNOWN_PREMISE"
    else:
        verdict = "CONFIRMED"

    # ASP cross-check (audit; only meaningful when trigger observed)
    asp = build_asp(hyp, cond_results, exc_results) if trigger_observed else build_asp({}, [], []) + "\n:- trigger_observed."
    asp_res = solve(asp)
    asp_verdict = "?"
    if asp_res.get("ok") and asp_res.get("models"):
        atoms = asp_res["models"][0]
        for a in atoms:
            if a.startswith("verdict(confirmed)"):
                asp_verdict = "CONFIRMED"
            elif a.startswith("verdict(refuted)"):
                asp_verdict = "REFUTED"
            elif a.startswith("verdict(unresolved)"):
                asp_verdict = "UNRESOLVED"

    return {
        "hypothesis": hyp.get("hypothesis"),
        "rule_grounded": rule_grounded,
        "trigger_observed": trigger_observed,
        "conditions": cond_results,
        "exceptions": exc_results,
        "verdict_python": verdict,
        "verdict_asp": asp_verdict,
        "verdict": verdict if rule_grounded else "UNRESOLVED_RULE_UNGROUNDED",
    }


def formalize_suspicion(suspicion: dict, row: dict, trace: Trace) -> Optional[dict]:
    """LLM: suspicion -> typed hypothesis template."""
    tool_lines = [
        f"[{e.kind} {e.tool} seq={e.seq}] {e.raw_payload[:500]}"
        for e in trace.tool_events
    ][:80]
    user = (
        "POLICY:\n" + trace.policy_text
        + "\n\nTOOL EVENTS (ordered):\n" + "\n".join(tool_lines)
        + "\n\nFINAL RESPONSE:\n" + row["response"]
        + "\n\nSUSPICION:\n" + json.dumps(suspicion, ensure_ascii=False)
        + "\n\nConvert to the typed template. Output strictly the JSON."
    )
    resp = chat(user=user, system=FORMALIZE_SYS, thinking=True, tag=f"archD/formalize")
    if not resp.ok:
        return None
    data = extract_json(resp.content)
    if not data or "conditions" not in data:
        return None
    return data
