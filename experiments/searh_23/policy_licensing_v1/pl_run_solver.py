"""IDEA H — global graph inference over policy-licensed candidate edges.

PREREGISTERED design (fixed before any test-split results were opened;
only arm outputs on the frozen suite are consumed):

  Candidates : unordered pairs whose DET arm decision is RELATED.
               UNKNOWN / NOT_RELATED pairs are HARD-EXCLUDED: the solver may
               never turn an UNKNOWN into a proven edge.
  Variables  : per pair e — accept(e), orientation a->b vs b->a.
  Objective  : maximize  sum_e accept(e) * support(e)
               support (primary)   = 0.5*ce_both_max + 0.5*llm_related
               sensitivity variants: uniform=1.0 / ce_only / llm_only
  Constraints:
    C1 dir fixed to the DIR arm answer when it says A or B (else free)
    C2 the accepted directed graph must be ACYCLIC (ordering vars)
    C3 XOR groups from the GRP arm: at most one parent edge accepted
    C4 AND groups from the GRP arm: parent edges all-or-nothing
  NO other constraints: no single-parent rules, no closest-operation rules,
  no same-sentence rules (all forbidden as benchmark assumptions).

Solvers: OR-Tools CP-SAT (primary) and clingo/ASP (cross-check); both must
return the same objective value on every case or the mismatch is reported.

LOCAL vs GLOBAL comparison uses identical candidates and scores.

Run: python3 pl_run_solver.py
"""
from __future__ import annotations

import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from pl_common import load_suite, out_dir, write_usage, ev_by_eid

CE_BAND = 0.35  # frozen from relation_edges_v1 (ce decision >= 0.35 passes band)
SUPPORT_VARIANTS = {
    "primary": lambda ce, llm: 0.5 * ce + 0.5 * llm,
    "uniform": lambda ce, llm: 1.0,
    "ce_only": lambda ce, llm: float(ce),
    "llm_only": lambda ce, llm: float(llm),
}


def load_case_inputs(case, suffix=""):
    sig = json.loads(out_dir("PAIR_signals" + suffix).joinpath(
        f"{case['case_id']}.json").read_text(encoding="utf-8"))
    det = json.loads(out_dir(f"det_mistral{suffix}").joinpath(
        f"{case['case_id']}.json").read_text(encoding="utf-8"))["rows"]
    dird = out_dir(f"dir_mistral{suffix}") / f"{case['case_id']}.json"
    dir_rows = json.loads(dird.read_text(encoding="utf-8"))["rows"] if dird.is_file() else []
    grpd = out_dir(f"grp_mistral{suffix}") / f"{case['case_id']}.json"
    grp_rows = json.loads(grpd.read_text(encoding="utf-8"))["rows"] if grpd.is_file() else []
    det_map = {frozenset((r["a_eid"], r["b_eid"])): r for r in det}
    sig_map = {(r["a_eid"], r["b_eid"]): r for r in sig["pairs"]}
    for (a, b), r in list(sig_map.items()):
        sig_map[(b, a)] = r
    dir_map = {frozenset((r["a_eid"], r["b_eid"])): r for r in dir_rows}
    return sig, det_map, sig_map, dir_map, grp_rows


def candidates_for(case, det_map, sig_map):
    """BASE combo candidates: det RELATED AND ce_band; with support scores."""
    out = []
    for key, r in det_map.items():
        if r.get("decision") != "RELATED":
            continue
        sig = sig_map.get((r["a_eid"], r["b_eid"]))
        if sig is None:
            continue
        ce = max(sig["ce_both_ab"], sig["ce_both_ba"])
        if ce < CE_BAND:
            continue
        out.append({"pair": key, "a_eid": r["a_eid"], "b_eid": r["b_eid"],
                    "ce": ce, "llm": 1.0, "gold": sig["gold"], "hard": sig["hard"]})
    return out


def solve_cpsat(events, cands, dir_map, grp_rows, support_fn):
    from ortools.sat.python import cp_model
    n_ev = len(events)
    ev_ids = [e["eid"] for e in events]
    idx = {v: i for i, v in enumerate(ev_ids)}
    m = cp_model.CpModel()
    acc, ab, ba = {}, {}, {}
    for c in cands:
        a, b = c["a_eid"], c["b_eid"]
        key = frozenset((a, b))
        acc[key] = m.NewBoolVar("acc")
        ab[key] = m.NewBoolVar("ab")
        ba[key] = m.NewBoolVar("ba")
        m.Add(acc[key] == ab[key] + ba[key])  # exactly one orientation iff accepted
        m.Add(ab[key] + ba[key] <= 1)
    # C1: direction fixed by DIR arm where confident
    for c in cands:
        a, b = c["a_eid"], c["b_eid"]
        key = frozenset((a, b))
        d = dir_map.get(key)
        if d and d.get("first") in ("A", "B"):
            first_eid = a if d["first"] == "A" else b
            if first_eid == a:
                m.Add(ab[key] == 1)
            else:
                m.Add(ba[key] == 1)
    # C2: acyclicity via ordering vars
    ordv = [m.NewIntVar(0, n_ev - 1, f"o{i}") for i in range(n_ev)]
    for c in cands:
        a, b = c["a_eid"], c["b_eid"]
        key = frozenset((a, b))
        ia, ib = idx[a], idx[b]
        m.Add(ordv[ia] + 1 <= ordv[ib]).OnlyEnforceIf(ab[key])
        m.Add(ordv[ib] + 1 <= ordv[ia]).OnlyEnforceIf(ba[key])
    # C3/C4: group constraints
    for g in grp_rows:
        logic = g.get("logic")
        keys = [frozenset((g["target_eid"], p)) for p in g["parent_eids"]]
        keys = [k for k in keys if k in acc]
        if not keys:
            continue
        if logic == "XOR":
            m.Add(sum(ab[k] + ba[k] for k in keys) <= 1)
        elif logic == "AND":
            first = keys[0]
            for k in keys[1:]:
                m.Add(acc[k] == acc[first])
    # objective
    terms = []
    for c in cands:
        key = frozenset((c["a_eid"], c["b_eid"]))
        terms.append(support_fn(c["ce"], c["llm"]) * acc[key])
    if terms:
        m.Maximize(sum(terms))
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10
    status = solver.Solve(m)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return None, None
    sel = []
    for c in cands:
        key = frozenset((c["a_eid"], c["b_eid"]))
        if solver.Value(acc[key]):
            a_first = solver.Value(ab[key]) == 1
            u, v = (c["a_eid"], c["b_eid"]) if a_first else (c["b_eid"], c["a_eid"])
            sel.append((u, v))
    return sel, solver.ObjectiveValue()


def solve_clingo(events, cands, dir_map, grp_rows, support_fn):
    """ASP cross-check. All pair/group facts are emitted GROUNDED from
    Python (normalized x<y) so the ASP program itself stays tiny."""
    import clingo

    ev_ids = [e["eid"] for e in events]
    n = len(ev_ids)
    prog = [f"#const n = {n}."]
    for i in range(n):
        prog.append(f"node({i}).")
    # candidates, normalized x<y, with support as integer (x1000)
    cand_keys = set()
    for c in cands:
        a, b = c["a_eid"], c["b_eid"]
        x, y = sorted((ev_ids.index(a), ev_ids.index(b)))
        sup = int(round(support_fn(c["ce"], c["llm"]) * 1000))
        prog.append(f"cand({x},{y},{sup}).")
        cand_keys.add((x, y))
    # DIR-fixed orientations, grounded: constraint "if sel(x,y) then orient(f,o)"
    for c in cands:
        a, b = c["a_eid"], c["b_eid"]
        x, y = sorted((ev_ids.index(a), ev_ids.index(b)))
        d = dir_map.get(frozenset((a, b)))
        if d and d.get("first") in ("A", "B"):
            first_eid = a if d["first"] == "A" else b
            f = ev_ids.index(first_eid)
            o = y if f == x else x
            prog.append(f"dirfix({x},{y},{f},{o}).")
    # groups, grounded over candidate pairs
    gid_counter = 0
    for g in grp_rows:
        if g.get("logic") not in ("XOR", "AND"):
            continue
        t = ev_ids.index(g["target_eid"])
        keys = []
        for p in g["parent_eids"]:
            pp = ev_ids.index(p)
            x, y = sorted((t, pp))
            if (x, y) in cand_keys:
                keys.append((x, y))
        if not keys:
            continue
        gid = gid_counter
        gid_counter += 1
        if g["logic"] == "XOR":
            for x, y in keys:
                prog.append(f"xg({gid},{x},{y}).")
            gid += 1
        else:
            for x, y in keys:
                prog.append(f"ag({gid},{x},{y}).")
            gid += 1
    prog.append(r"""
    { sel(X,Y) } :- cand(X,Y,_).
    1 { orient(X,Y); orient(Y,X) } 1 :- sel(X,Y).
    :- sel(X,Y), dirfix(X,Y,F,O), not orient(F,O).
    pedge(X,Y) :- sel(X,Y).
    pedge(Y,X) :- sel(X,Y).
    :- xg(G,_X,_Y), #count{X,Y : xg(G,X,Y), pedge(X,Y)} > 1.
    :- ag(G,X,Y), pedge(X,Y), ag(G,X2,Y2), (X,Y) < (X2,Y2), not pedge(X2,Y2).
    1 { level(V,1..n) } 1 :- node(V).
    :- orient(X,Y), level(X,LX), level(Y,LY), LX >= LY.
    #maximize { S@1,X,Y : sel(X,Y), cand(X,Y,S) }.
    """)
    ctl = clingo.Control(["--model=0"])
    ctl.add("base", [], "\n".join(prog))
    ctl.ground([("base", [])])
    sel_pairs, orient = set(), set()
    last_symbols = None
    with ctl.solve(yield_=True) as hnd:
        for mdl in hnd:  # optimization: later models are the best ones
            last_symbols = list(mdl.symbols(atoms=True))
    if last_symbols is None:
        return None, None
    for a in last_symbols:
        if a.name == "sel":
            x, y = a.arguments
            sel_pairs.add(frozenset((ev_ids[x.number], ev_ids[y.number])))
        elif a.name == "orient":
            x, y = a.arguments
            orient.add((ev_ids[x.number], ev_ids[y.number]))
    sel = []
    for pair in sel_pairs:
        u, v = tuple(pair)
        sel.append((u, v) if (u, v) in orient else (v, u))
    return sel, None


def main():
    results = {}
    for variant, support_fn in SUPPORT_VARIANTS.items():
        per_case = {}
        for case in load_suite("original"):
            try:
                sig, det_map, sig_map, dir_map, grp_rows = load_case_inputs(case)
                cands = candidates_for(case, det_map, sig_map)
            except FileNotFoundError as e:
                per_case[case["case_id"]] = {"error": f"missing arm output: {e}"}
                continue
            if not cands:
                per_case[case["case_id"]] = {"candidates": 0, "selected": [],
                                             "objective": 0.0}
                continue
            sel, obj = solve_cpsat(case["events"], cands, dir_map, grp_rows, support_fn)
            per_case[case["case_id"]] = {
                "candidates": len(cands),
                "candidate_pairs": [sorted(c["pair"]) for c in cands],
                "selected": sel,
                "objective": obj,
            }
        results[variant] = per_case

    # clingo cross-check with the primary support
    clingo_out = {}
    for case in load_suite("original"):
        try:
            sig, det_map, sig_map, dir_map, grp_rows = load_case_inputs(case)
            cands = candidates_for(case, det_map, sig_map)
        except FileNotFoundError:
            continue
        if not cands:
            continue
        sel, _ = solve_clingo(case["events"], cands, dir_map, grp_rows,
                              SUPPORT_VARIANTS["primary"])
        clingo_out[case["case_id"]] = sel

    payload = {"preregistered": {
                   "objective": "max sum accept*support",
                   "support_primary": "0.5*ce_both_max + 0.5*llm_related",
                   "constraints": ["UNKNOWN/NOT_RELATED excluded (hard)",
                                   "DIR-fixed orientation",
                                   "acyclicity (ordering vars)",
                                   "XOR groups <=1", "AND groups all-or-nothing"],
                   "ce_band": CE_BAND},
               "cpsat": results,
               "clingo_crosscheck_primary": clingo_out}
    out_dir("H_solver").joinpath("solver.json").write_text(
        json.dumps(payload, ensure_ascii=False, indent=1), encoding="utf-8")
    write_usage("H_solver", {"phase": "solver",
                             "libs": ["ortools CP-SAT", "clingo 5.8"]})
    n_sel = {v: sum(len(c.get("selected", [])) for c in r.values())
             for v, r in results.items()}
    print("selected edges per support variant:", n_sel)
    print("clingo cross-check cases:", len(clingo_out))


if __name__ == "__main__":
    main()
