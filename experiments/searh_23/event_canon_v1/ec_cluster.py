"""EVENT_CANON_v1 - clustering construction over pair decisions.

Methods (all name-blind, generic):
  cc   : connected components over SAME-labeled pairs (transitive closure
         - the known A~B, B~C over-merge danger)
  veto : union-find merge, blocked when any cross pair is labeled
         DIFFERENT / RELATED_BUT_DIFFERENT (constrained clustering)
  al   : agglomerative average-linkage over SAME-scores
  cl   : agglomerative complete-linkage over SAME-scores
  corr : correlation clustering via CP-SAT (pre-registered objective:
         minimize disagreeing pairs; transitivity constraints)

Pair sources provide either discrete labels or numeric scores; labels are
mapped to pseudo-scores SAME=1.0 > UNKNOWN=0.5 > RELATED=0.25 > DIFFERENT=0.
"""
from __future__ import annotations

import json
from pathlib import Path

LABEL_SCORE = {"SAME_EVENT": 1.0, "UNKNOWN": 0.4,
               "RELATED_BUT_DIFFERENT": 0.25, "DIFFERENT": 0.0}
# UNKNOWN (0.4) stays BELOW the default merge threshold (0.5): uncertain
# pairs must not merge (discipline: uncertain -> SAME is forbidden); they
# also do not veto (only definite DIFFERENT/RELATED veto).


def pair_score(rec, score_key=None):
    if score_key and score_key in rec:
        return float(rec[score_key])
    return LABEL_SCORE.get(rec.get("label"), 0.0)


def _adjacency(pairs, score_fn, thresh):
    by_pair = {}
    for r in pairs:
        key = tuple(sorted((r["a"], r["b"])))
        by_pair[key] = score_fn(r)
    return by_pair


def cluster_cc(pairs, score_fn, thresh):
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for r in pairs:
        if score_fn(r) >= thresh:
            union(r["a"], r["b"])
    out = {}
    for m in parent:
        out.setdefault(find(m), []).append(m)
    return {mid: i for i, (root, mids) in enumerate(
        sorted(out.items(), key=lambda kv: min(kv[1]))) for mid in mids}


def cluster_veto(pairs, score_fn, thresh):
    """Union-find over SAME pairs, but a merge is rolled back if any pair
    inside the resulting cluster is definitely non-same (label in
    DIFFERENT/RELATED with score below veto_floor)."""
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    members = {}

    def cluster_of(x):
        root = find(x)
        return members.get(root, [x])

    veto = {}
    for r in pairs:
        key = tuple(sorted((r["a"], r["b"])))
        veto[key] = r.get("label") in ("DIFFERENT", "RELATED_BUT_DIFFERENT") \
            and score_fn(r) <= 0.25

    for r in sorted(pairs, key=lambda r: -score_fn(r)):
        if score_fn(r) < thresh:
            continue
        a, b = r["a"], r["b"]
        ma, mb = cluster_of(a), cluster_of(b)
        if find(a) == find(b):
            continue
        blocked = any(veto.get(tuple(sorted((x, y))), False)
                      for x in ma for y in mb)
        if blocked:
            continue
        ra, rb = find(a), find(b)
        parent[ra] = rb
        members[rb] = sorted(set(ma) | set(mb))
        members.pop(ra, None)
    out = {}
    for m in parent:
        out.setdefault(find(m), []).append(m)
    return {mid: i for i, (root, mids) in enumerate(
        sorted(out.items(), key=lambda kv: min(kv[1]))) for mid in mids}


def _agglomerative(pairs, score_fn, thresh, linkage):
    mids = sorted({r["a"] for r in pairs} | {r["b"] for r in pairs})
    sim = {}
    for r in pairs:
        key = tuple(sorted((r["a"], r["b"])))
        sim[key] = score_fn(r)
    clusters = [[m] for m in mids]

    def link(ca, cb):
        vals = [sim.get(tuple(sorted((x, y))), 0.0)
                for x in ca for y in cb]
        if not vals:
            return 0.0
        return sum(vals) / len(vals) if linkage == "average" else min(vals)

    while True:
        best, best_v = None, thresh
        for i in range(len(clusters)):
            for j in range(i + 1, len(clusters)):
                v = link(clusters[i], clusters[j])
                if v >= best_v:
                    best, best_v = (i, j), v
        if best is None:
            break
        i, j = best
        clusters[i] = sorted(clusters[i] + clusters[j])
        clusters.pop(j)
    return {m: i for i, c in enumerate(clusters) for m in c}


def cluster_corr(pairs, score_fn, thresh):
    """Correlation clustering via CP-SAT (ortools). Objective (preregistered):
    minimize sum over pairs of disagreement cost, where cost(+same)=w_pos if
    separated and cost(-same)=w_neg if merged. Transitivity enforced."""
    try:
        from ortools.sat.python import cp_model
    except ImportError:
        return cluster_veto(pairs, score_fn, thresh)
    mids = sorted({r["a"] for r in pairs} | {r["b"] for r in pairs})
    idx = {m: i for i, m in enumerate(mids)}
    n = len(mids)
    model = cp_model.CpModel()
    x = {}
    costs = {}
    for i in range(n):
        for j in range(i + 1, n):
            x[(i, j)] = model.NewBoolVar(f"x_{i}_{j}")
    for r in pairs:
        s = max(0.0, min(1.0, score_fn(r)))
        i, j = sorted((idx[r["a"]], idx[r["b"]]))
        # cost_split: evidence says same-ish but we separate
        # cost_merge: evidence says diff-ish but we merge
        costs[(i, j)] = (int(round(s * 100)), int(round((1.0 - s) * 100)))
    obj_terms = []
    for (i, j), var in x.items():
        cost_split, cost_merge = costs.get((i, j), (0, 0))
        b_split = model.NewBoolVar(f"bs_{i}_{j}")
        b_merge = model.NewBoolVar(f"bm_{i}_{j}")
        model.Add(var == 0).OnlyEnforceIf(b_split)
        model.Add(var == 1).OnlyEnforceIf(b_merge)
        model.AddBoolOr([b_split, b_merge])
        obj_terms.append(cost_split * b_split + cost_merge * b_merge)
    model.Minimize(sum(obj_terms))
    # transitivity: x_ij=1 & x_jk=1 -> x_ik=1
    for i in range(n):
        for j in range(i + 1, n):
            for k in range(j + 1, n):
                model.AddBoolOr([x[(i, j)].Not(), x[(j, k)].Not(),
                                 x[(i, k)]])
    solver = cp_model.CpSolver()
    solver.parameters.max_time_in_seconds = 10.0
    status = solver.Solve(model)
    if status not in (cp_model.OPTIMAL, cp_model.FEASIBLE):
        return cluster_veto(pairs, score_fn, thresh)
    same = {}
    for (i, j), var in x.items():
        same[tuple(sorted((mids[i], mids[j])))] = solver.Value(var)
    return cluster_cc([{"a": a, "b": b, "label": "SAME_EVENT" if v else
                        "DIFFERENT"} for (a, b), v in same.items()],
                      lambda r: LABEL_SCORE[r["label"]], 0.6)


METHODS = {
    "cc": lambda pairs, sf, th: cluster_cc(pairs, sf, th),
    "veto": lambda pairs, sf, th: cluster_veto(pairs, sf, th),
    "al": lambda pairs, sf, th: _agglomerative(pairs, sf, th, "average"),
    "cl": lambda pairs, sf, th: _agglomerative(pairs, sf, th, "complete"),
    "corr": cluster_corr,
}


def build_clusters(pairs, method, score_fn=None, thresh=0.5):
    sf = score_fn or (lambda r: pair_score(r))
    return METHODS[method](pairs, sf, thresh)


if __name__ == "__main__":
    # smoke test
    pairs = [
        {"a": "m1", "b": "m2", "label": "SAME_EVENT"},
        {"a": "m2", "b": "m3", "label": "SAME_EVENT"},
        {"a": "m1", "b": "m3", "label": "DIFFERENT"},
        {"a": "m4", "b": "m3", "label": "RELATED_BUT_DIFFERENT"},
    ]
    for m in METHODS:
        print(m, build_clusters(pairs, m))
