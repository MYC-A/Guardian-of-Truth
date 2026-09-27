"""Synthetic smoke test for the solver arms (CP-SAT + clingo) — no real data."""
import sys
sys.path.insert(0, '/workspace/guardian/repos/Guardian-of-Truth/experiments/searh_23/policy_licensing_v1')
from pl_run_solver import solve_cpsat, solve_clingo, SUPPORT_VARIANTS


class FakeEv(dict):
    pass


def ev(eid):
    return {"eid": eid}


def run(name, events, cands, dir_map, grp_rows):
    sup = SUPPORT_VARIANTS["primary"]
    sel_c, obj = solve_cpsat(events, cands, dir_map, grp_rows, sup)
    sel_k, _ = solve_clingo(events, cands, dir_map, grp_rows, sup)
    print(f"[{name}] cpsat={sel_c} obj={obj}")
    print(f"[{name}] clingo={sel_k}")
    return sel_c, sel_k


# case 1: simple chain, all candidates accepted
events = [ev("A"), ev("B"), ev("C")]
cands = [
    {"pair": frozenset(("A", "B")), "a_eid": "A", "b_eid": "B", "ce": 0.9, "llm": 1.0, "gold": "POSITIVE", "hard": True},
    {"pair": frozenset(("B", "C")), "a_eid": "B", "b_eid": "C", "ce": 0.8, "llm": 1.0, "gold": "POSITIVE", "hard": True},
]
run("chain", events, cands, {}, [])

# case 2: cycle A->B, B->C, C->A -> solver must drop one (lowest support)
cands2 = cands + [
    {"pair": frozenset(("C", "A")), "a_eid": "C", "b_eid": "A", "ce": 0.1, "llm": 1.0, "gold": "NEGATIVE", "hard": True},
]
run("cycle", events, cands2, {}, [])

# case 3: DIR-fixed contradictory directions
dir_map = {frozenset(("A", "B")): {"a_eid": "A", "first": "B"},   # B->A
           frozenset(("B", "C")): {"a_eid": "B", "first": "B"}}  # C->B
run("dir-fixed chain", events, cands, dir_map, [])

# case 4: XOR group on target C with parents A, B
grp = [{"target_eid": "C", "parent_eids": ["A", "B"], "logic": "XOR"}]
cands4 = [
    {"pair": frozenset(("A", "C")), "a_eid": "A", "b_eid": "C", "ce": 0.9, "llm": 1.0, "gold": "POSITIVE", "hard": True},
    {"pair": frozenset(("B", "C")), "a_eid": "B", "b_eid": "C", "ce": 0.8, "llm": 1.0, "gold": "NEGATIVE", "hard": True},
]
run("xor group", events, cands4, {}, grp)

# case 5: AND group all-or-nothing
grp_and = [{"target_eid": "C", "parent_eids": ["A", "B"], "logic": "AND"}]
run("and group", events, cands4, {}, grp_and)

print("SOLVER SMOKE DONE")
