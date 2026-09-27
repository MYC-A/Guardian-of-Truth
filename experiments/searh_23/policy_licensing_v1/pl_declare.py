"""Declare4Py investigation — formal layer AFTER extraction.

Questions (from the research brief):
  - which Guardian relation types map naturally onto Declare templates?
  - can the Declare/LTLf layer detect internally contradictory graph
    candidates (cycles, precedence/not-response clashes)?
  - does conformance checking work on simple compliant/violating traces?

What is ACTUALLY used from Declare4Py 2.2.0:
  - DeclareModel.parse_from_string / get_decl_model_constraints /
    get_model_activities: every mapped constraint in .decl syntax is parsed
    and validated by Declare4Py itself.
  - DeclareModelTemplate (via DeclareModel parsing): template inventory.

What is NOT used and why (honest limitation): Declare4Py's
check_satisfiability() requires the external `lydia` binary, which is not
available in this environment (build from source not attempted - out of
scope). Satisfiability and trace conformance are therefore computed by a
bounded model checker over the SAME canonical Declare semantics, implemented
with clingo (bounded traces of length n_events+1). This tests the formal
layer, not Declare4Py's internals.

Guardian -> Declare mapping (documented):
  PRECONDITION A->B      precedence(A, B)
  STATE_GATE  A->B       precedence(A, B)   (state observed before op)
  ORDER_BEFORE A->B      precedence(A, B)
  ORDER_AFTER  A->B      precedence(B, A)
  RESPONSE    A->B       response(A, B)
  EXCEPTION   A->B       not_response(A, B) (B forbidden once A holds)
  EVEN_IF     A->B       no template (documented non-blocking)
  AND group {A,B}->C     precedence(A,C) & precedence(B,C)
  OR group  {A,B}->C     NOT expressible in plain Declare (disjunction);
                         approximated by the two precedence constraints
                         (weaker) - documented limitation
  SUCCESSION             precedence + response (both directions) - no such
                         edge in this dataset, mapping documented for
                         completeness

Run: python3 pl_declare.py
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, out_dir, ev_by_eid

import clingo

MAPPING = {
    "PRECONDITION": "precedence",
    "STATE_GATE": "precedence",
    "ORDER_BEFORE": "precedence",
    "ORDER_AFTER": "precedence(reversed)",
    "RESPONSE": "response",
    "EXCEPTION": "not_response",
    "EVEN_IF": None,  # documented non-blocking, no template
}


def decl_text_for_case(case, edges):
    """Build .decl syntax: activities + one constraint per typed edge."""
    acts = sorted({ed["from_eid"] for ed in edges} | {ed["to_eid"] for ed in edges})
    lines = [f"activity {a}" for a in acts]
    for ed in edges:
        rel = ed["relation"]
        if rel == "ORDER_AFTER":
            lines.append(f"precedence[{ed['to_eid']},{ed['from_eid']}]")
        elif MAPPING.get(rel) == "precedence":
            lines.append(f"precedence[{ed['from_eid']},{ed['to_eid']}]")
        elif MAPPING.get(rel) == "response":
            lines.append(f"response[{ed['from_eid']},{ed['to_eid']}]")
        elif MAPPING.get(rel) == "not_response":
            lines.append(f"not_response[{ed['from_eid']},{ed['to_eid']}]")
        # EVEN_IF and unknown types: no constraint (documented)
    return "\n".join(lines) + "\n", lines


def parse_with_declare4py(decl_text):
    from Declare4Py.ProcessModels.DeclareModel import DeclareModel
    m = DeclareModel()
    m.parse_from_string(decl_text)
    return m.get_decl_model_constraints(), m.get_model_activities()


def bmc_program(events, edges, trace=None):
    """clingo bounded model checker over canonical Declare semantics.

    Trace semantics: positions 0..k-1, exactly one event per position,
    k = len(events)+1 (enough room for any acyclic order plus slack).
    precedence(a,b): every b-occurrence has a strictly earlier a-occurrence.
    response(a,b):   every a-occurrence has a b-occurrence at position >= it.
    not_response(a,b): no b-occurrence strictly after an a-occurrence.
    occurrence F(e): each event that participates in an edge occurs >= once.
    """
    k = len(events) + 1
    evs = sorted({e for ed in edges for e in (ed["from_eid"], ed["to_eid"])})
    prog = [
        f"#const k = {k}.",
        "pos(0..k-1).",
        *[f"ev(\"{e}\")." for e in evs],
        "1 { occ(P,E) : ev(E) } 1 :- pos(P).",
        "occurs(E) :- occ(_, E).",
    ]
    for ed in edges:
        a, b, rel = ed["from_eid"], ed["to_eid"], ed["relation"]
        if rel == "ORDER_AFTER":
            a, b = b, a
            rel = "ORDER_BEFORE"
        if rel in ("PRECONDITION", "STATE_GATE", "ORDER_BEFORE"):
            prog.append(f':- occ(P,"{b}"), not before("{a}","{b}",P).')
            prog.append(f'before("{a}","{b}",P) :- pos(P), occ(Q,"{a}"), Q < P.')
        elif rel == "RESPONSE":
            prog.append(f':- occ(P,"{a}"), not after("{b}","{a}",P).')
            prog.append(f'after("{b}","{a}",P) :- pos(P), occ(Q,"{b}"), Q >= P.')
        elif rel == "EXCEPTION":
            prog.append(f':- occ(P,"{a}"), occ(Q,"{b}"), Q > P.')
        # EVEN_IF: no constraint
    for e in evs:
        prog.append(f':- not occurs("{e}").')
    if trace is not None:
        for p, e in enumerate(trace):
            prog.append(f'occ({p},"{e}").')
        prog.append("pos(0..%d)." % (len(trace) - 1,))
    return "\n".join(prog)


def check_sat(events, edges):
    prog = bmc_program(events, edges)
    ctl = clingo.Control()
    ctl.add("base", [], prog)
    ctl.ground([("base", [])])
    sat = False
    with ctl.solve(yield_=True) as hnd:
        for _ in hnd:
            sat = True
            break
    return sat


def check_trace(events, edges, trace):
    """Conformance: True iff the trace satisfies all constraints."""
    prog = bmc_program(events, edges, trace=trace)
    ctl = clingo.Control()
    ctl.add("base", [], prog)
    ctl.ground([("base", [])])
    sat = False
    with ctl.solve(yield_=True) as hnd:
        for _ in hnd:
            sat = True
            break
    return sat


def synthesize_compliant_trace(events, edges):
    """Find a trace satisfying all constraints (topological-ish order)."""
    prog = bmc_program(events, edges)
    ctl = clingo.Control()
    ctl.add("base", [], prog)
    ctl.ground([("base", [])])
    with ctl.solve(yield_=True) as hnd:
        for mdl in hnd:
            occ = {}
            for a in mdl.symbols(atoms=True):
                if a.name == "occ" and len(a.arguments) == 2:
                    p, e = a.arguments
                    occ[p.number] = e.string if str(e.type) == "SymbolType.String" else str(e).strip('"')
            return [occ[i] for i in sorted(occ)]
    return None


def main():
    results = []
    for case in load_suite("original", split="test"):
        edges = case["edges"]
        if not edges:
            continue
        decl_text, constraint_lines = decl_text_for_case(case, edges)
        d4p_constraints, d4p_activities = parse_with_declare4py(decl_text)
        gold_sat = check_sat(case["events"], edges)
        compliant = synthesize_compliant_trace(case["events"], edges)
        # a violating trace: reverse of a compliant one (violates precedence
        # wherever an edge exists)
        violating = list(reversed(compliant)) if compliant else None
        conf_ok = check_trace(case["events"], edges, compliant) if compliant else None
        conf_bad = (not check_trace(case["events"], edges, violating)) if violating else None
        results.append({
            "case_id": case["case_id"],
            "declare4py_parsed_constraints": d4p_constraints,
            "declare4py_activities": d4p_activities,
            "gold_graph_satisfiable": gold_sat,
            "compliant_trace": compliant,
            "violating_trace": violating,
            "compliant_conforms": conf_ok,
            "violating_rejected": conf_bad,
        })

    # contradictory-graph detection demo: inject a cycle into test_cinema
    cin = next(c for c in load_suite("original", split="test")
               if c["case_id"] == "test_cinema")
    cyclic_edges = json.loads(json.dumps(cin["edges"]))
    cyclic_edges.append({"from_eid": "C", "to_eid": "A",
                         "relation": "ORDER_BEFORE"})
    cycle_detected = not check_sat(cin["events"], cyclic_edges)

    # Declare4Py parses the artificial cycle constraints too
    cyc_text, _ = decl_text_for_case(cin, cyclic_edges)
    cyc_parsed, _ = parse_with_declare4py(cyc_text)

    summary = {
        "declare4py_version": "2.2.0",
        "lydia_backend_available": False,
        "sat_engine": "clingo BMC over canonical Declare semantics",
        "mapping": MAPPING,
        "per_case": results,
        "contradiction_detection": {
            "injected_cycle_case": "test_cinema (A->B->C + injected C->A)",
            "declare4py_parses_cycle_constraints": len(cyc_parsed) > len(results[1]["declare4py_parsed_constraints"]) if len(results) > 1 else True,
            "cycle_detected_unsat": cycle_detected,
        },
        "template_notes": {
            "natural": ["precedence (PRECONDITION/STATE_GATE/ORDER)",
                        "response (RESPONSE)", "succession (bidirectional, not needed here)",
                        "not_response / not_coexistence (EXCEPTION approximations)"],
            "not_expressible": ["OR groups (plain Declare has no template disjunction)",
                                "EVEN_IF (documented non-blocking)",
                                "cardinality constraints (absent in this dataset)"],
        },
    }
    out_dir("DECLARE").joinpath("declare.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=1), encoding="utf-8")
    print(json.dumps({"cases": len(results),
                      "all_gold_sat": all(r["gold_graph_satisfiable"] for r in results),
                      "all_compliant_conform": all(r["compliant_conforms"] for r in results if r["compliant_conforms"] is not None),
                      "all_violating_rejected": all(r["violating_rejected"] for r in results if r["violating_rejected"] is not None),
                      "cycle_detected": cycle_detected}, indent=1))


if __name__ == "__main__":
    main()
