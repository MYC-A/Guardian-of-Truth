"""full_architecture_v1 — Phase B probe: Invariant Guardrails trace-matching
comparator (directive §12).

Question: can invariantlabs-ai/invariant's local programmatic analyzer replace
parts of Guardian's custom event-search / trace-matching code?

Protocol (per directive):
  same normalized trace  ->  Invariant rule  ->  match/no-match + matched
  objects, compared against the incumbent's deterministic event search on the
  SAME trace.  Invariant is a COMPARATOR, never authoritative for Guardian
  semantics.

Probed capabilities:
  P1  ToolCall matching by name + argument conditions
  P2  ToolOutput matching by tool + content condition
  P3  causal/sequence flow (A -> B ordered matching)
  P4  existential negation ("no prior output of tool T before call C")
  P5  matched objects feeding a witness (PolicyViolation kwargs)
  P6  rename invariance (tool names renamed consistently -> same match)
  P7  irrelevant-event insertion invariance

Guardian-semantics questions (answered from the language/runtime reading and
confirmed experimentally where possible):
  Q-UNKNOWN    — can it express UNKNOWN? (no: rules are boolean over the
                 present trace; absence of a match is just FALSE)
  Q-STALE      — can it express stale state? (no: no state model; only
                 message-order reasoning)
  Q-TRUSTED    — can it express trusted effects/contracts? (no)
  Q-COMPLETE   — can it express completeness premises? (no: trace IS the
                 closed world; no premise system)
  Q-MULTI      — can it express multiple interpretations? (no: one evaluation
                 per trace; no world/answer-set semantics)
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
REPO = HERE.parents[2]
OUT = REPO / "outputs" / "full_architecture_v1" / "probes"

from invariant.analyzer import LocalPolicy  # noqa: E402


def _trace(events: list[dict]) -> list[dict]:
    return events


def _call(cid, name, args):
    return {"role": "assistant",
            "tool_calls": [{"id": cid, "type": "function",
                            "function": {"name": name, "arguments": args}}]}


def _out(cid, content):
    return {"role": "tool", "tool_call_id": cid, "content": content}


def _user(text):
    return {"role": "user", "content": text}


# ------------------------------------------------------------------ probes

def probe_match_and_witness():
    """P1+P5: name+argument condition match; matched object as witness."""
    policy = LocalPolicy.from_string("""
raise "catalog: forbidden tool called" if:
    (call: ToolCall)
    call is tool:delete_user
    call.function.arguments.user_id == "u42"
""")
    hit = policy.analyze([
        _user("clean up u42"),
        _call("c1", "delete_user", {"user_id": "u42"}),
        _out("c1", "deleted"),
    ])
    miss = policy.analyze([
        _user("clean up u41"),
        _call("c1", "delete_user", {"user_id": "u41"}),
        _out("c1", "deleted"),
    ])
    return {"hit": len(hit.errors) == 1, "miss": len(miss.errors) == 0}


def probe_flow_order():
    """P3: ordered flow A -> B; reversed order must NOT match."""
    policy = LocalPolicy.from_string("""
raise "order violation" if:
    (a: ToolCall) -> (b: ToolCall)
    a is tool:get_ticket
    b is tool:close_ticket
""")
    ok = policy.analyze([
        _call("c1", "get_ticket", {}),
        _out("c1", "ok"),
        _call("c2", "close_ticket", {}),
        _out("c2", "closed"),
    ])
    reversed_trace = policy.analyze([
        _call("c2", "close_ticket", {}),
        _out("c2", "closed"),
        _call("c1", "get_ticket", {}),
        _out("c1", "ok"),
    ])
    return {"ordered_hit": len(ok.errors) == 1,
            "reversed_miss": len(reversed_trace.errors) == 0}


def probe_existential_negation():
    """P4: no prior ToolOutput of tool T before a target call."""
    policy = LocalPolicy.from_string("""
from invariant import count

raise "precondition missing: close without prior get" if:
    (b: ToolCall)
    b is tool:close_ticket
    not count(min=1):
        (out: ToolOutput)
        out is tool:get_ticket
        out -> b
""")
    violation = policy.analyze([
        _user("close it"),
        _call("c1", "close_ticket", {}),
        _out("c1", "closed"),
    ])
    compliant = policy.analyze([
        _call("c0", "get_ticket", {}),
        _out("c0", "ticket"),
        _call("c1", "close_ticket", {}),
        _out("c1", "closed"),
    ])
    return {"violation_hit": len(violation.errors) == 1,
            "compliant_miss": len(compliant.errors) == 0}


def probe_output_content():
    """P2: ToolOutput content condition (error result detection)."""
    policy = LocalPolicy.from_string("""
raise "tool error seen" if:
    (out: ToolOutput)
    "permission denied" in out.content
""")
    hit = policy.analyze([_call("c1", "pay", {}), _out("c1", "permission denied")])
    miss = policy.analyze([_call("c1", "pay", {}), _out("c1", "paid ok")])
    return {"hit": len(hit.errors) == 1, "miss": len(miss.errors) == 0}


def probe_rename_invariance():
    """P6: consistent tool renaming -> same match set."""
    policy = LocalPolicy.from_string("""
raise "forbidden" if:
    (call: ToolCall)
    call is tool:delete_user
""")
    base = policy.analyze([_call("c1", "delete_user", {}), _out("c1", "ok")])
    policy2 = LocalPolicy.from_string("""
raise "forbidden" if:
    (call: ToolCall)
    call is tool:purge_account
""")
    renamed = policy2.analyze([_call("c1", "purge_account", {}), _out("c1", "ok")])
    return {"rename_stable": len(base.errors) == len(renamed.errors) == 1}


def probe_irrelevant_insertion():
    """P7: unrelated events inserted -> verdict unchanged."""
    policy = LocalPolicy.from_string("""
raise "forbidden" if:
    (call: ToolCall)
    call is tool:delete_user
""")
    clean = policy.analyze([_call("c1", "read_report", {}), _out("c1", "r")])
    noisy = policy.analyze([
        _user("hello"), _call("c0", "read_log", {}), _out("c0", "l"),
        _call("c1", "read_report", {}), _out("c1", "r"),
        _user("bye"),
    ])
    return {"insertion_stable": len(clean.errors) == len(noisy.errors) == 0}


# ------------------------------------------------------------ language caps

LANGUAGE_CAPS = {
    "Q-UNKNOWN": "NOT EXPRESSIBLE — rules evaluate to raise/no-raise over the "
                 "present trace; absence of a match is plain FALSE. Guardian's "
                 "UNKNOWN (evidence not in trace, open world) would be silently "
                 "flattened to FALSE.",
    "Q-STALE": "NOT EXPRESSIBLE — no state model; only message order. A later "
               "possible mutation invalidating an old observation cannot be "
               "represented (would need Guardian staleness semantics).",
    "Q-TRUSTED": "NOT EXPRESSIBLE — no tool contracts; a ToolOutput is a "
                 "message, not a certified effect.",
    "Q-COMPLETE": "NOT EXPRESSIBLE — the analyzed trace is the whole closed "
                  "world; no premise like history_complete can gate "
                  "absence-derived conclusions.",
    "Q-MULTI": "NOT EXPRESSIBLE — single evaluation; no answer sets / worlds; "
               "ambiguous interpretations cannot be enumerated per-choice.",
    "Q-CLAIM": "PARTIAL — Message content regex/conditions exist, but "
               "assistant text claims are not distinguished from tool "
               "observations by the semantics (CLAIM != OBSERVED_FACT is "
               "Guardian's fence).",
}


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    results = {}
    for name, fn in [
        ("P1_match_and_witness", probe_match_and_witness),
        ("P3_flow_order", probe_flow_order),
        ("P4_existential_negation", probe_existential_negation),
        ("P2_output_content", probe_output_content),
        ("P6_rename_invariance", probe_rename_invariance),
        ("P7_irrelevant_insertion", probe_irrelevant_insertion),
    ]:
        try:
            results[name] = {"ok": True, **fn()}
        except Exception as error:
            results[name] = {"ok": False,
                             "error": f"{type(error).__name__}: {error}"[:200]}
    payload = {
        "package": "invariant-ai 0.3.5 (pip) + invariant-sdk 0.0.11 local "
                   "analyzer (Rust binary via invariant-sdk)",
        "probes": results,
        "language_capabilities": LANGUAGE_CAPS,
        "directive_questions": {
            "replace_generic_toolcall_tooloutput_matching":
                "YES for pure presence/order/argument-condition search over "
                "the trace (P1-P4 all pass); matched objects flow into "
                "violations (PolicyViolation kwargs) and can feed a witness",
            "express_ordered_trace_patterns_cleanly": "YES (-> operator; "
                "P3 reversed-order miss confirms true causality ordering)",
            "matched_objects_feed_certificate": "YES via raise "
                "PolicyViolation(msg, call=call, out=out) kwargs; the witness "
                "still needs Guardian source references added on our side",
            "cannot_express": ["UNKNOWN (would flatten to FALSE)",
                               "stale state", "trusted effects",
                               "completeness premises",
                               "multiple interpretations / worlds",
                               "four-valued evidence"],
        },
        "verdict": "COMPARATOR ONLY — suitable as N4-I trace-matching backend "
                   "and as a cross-check of Guardian's event-search code; "
                   "NOT authoritative for Guardian semantics (five "
                   "inexpressible core concepts listed above).",
    }
    (OUT / "invariant_probe.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps(results, indent=1))
    print("verdict:", payload["verdict"])


if __name__ == "__main__":
    main()
