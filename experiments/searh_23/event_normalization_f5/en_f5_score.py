"""EN-7/8: F5 master scorer — three-level evaluation (directive §17),
oracle decomposition (§18), rename invariance (§14), guard replay
(C-decomposition transfer), failure taxonomy (§22).

Levels:
  L1 mention/identity: node_precision, junk, false_split, cluster_recall
     + identity pair metrics (from en_f5_identity outputs)
  L2 clusters: B3/MUC/CEAF/CoNLL + false merges (en_common.cluster_scores)
  L3 graph: w1_score.score_case semantics (strict; duplicate no recall,
     reverse not correct, contaminated no credit) vs F5 gold edges

Arms scored (f5): v10, v11, oracleA, oracleB, modular; rename (f5r):
  v10, v11 + behavioral agreement vs the original runs.

Oracle decomposition (deterministic, from saved outputs):
  - node-ceiling: max achievable R given predicted nodes (gold edges
    whose both endpoint cids are covered by clean labeled nodes)
  - proposal-ceiling: gold edges whose endpoint NODE pair appears in the
    saved pair log with stage>=certificate (reached the relation stack)
  - oracleA/B arms: full stack with gold nodes / gold identity

Guard replay (F5 v10 pair logs): per-guard gold-killed / extra-killed
counts for cross_sentence / coordination / no-connective /
object-containment gates (post-hoc, zero LLM).

Run (server): /workspace/guardian/venv/bin/python en_f5_score.py
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
sys.path[:0] = [str(W1), str(IE), str(HERE)]

import w1_pipe3 as v10  # noqa: E402
from w1_score import score_case, node_label  # noqa: E402
from en_common import (node_cluster_metrics, cluster_scores,  # noqa: E402
                       node_clusters_as_sets, gold_clusters_as_sets)

ARMDIR = HERE / "outputs" / "arms"
OUTD = HERE / "outputs" / "score"
OUTD.mkdir(parents=True, exist_ok=True)

ARMS_F5 = ["v10", "v11", "oracleA", "oracleB", "modular"]
ARMS_F5R = ["v10", "v11"]


def load_f5(suite="f5") -> dict[str, dict]:
    fname = ("level_f5_cases.json" if suite == "f5"
             else "level_f5r_cases.json")
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}


def score_arm(arm: str, suite: str = "f5") -> dict:
    gold = load_f5(suite)
    d = ARMDIR / f"{suite}_{arm}"
    if not d.exists():
        return {"missing": True}
    per_case = {}
    node_rows = {}
    total = Counter()
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        row = score_case(case, data)
        per_case[cid] = row
        total.update(row["counts"])
        # L1/L2 node metrics
        nodes = data.get("nodes", [])
        nm = node_cluster_metrics(case, nodes)
        nm.update(cluster_scores(node_clusters_as_sets(case, nodes),
                                 gold_clusters_as_sets(case)))
        node_rows[cid] = nm
    correct = total["correct_unique"]
    extra = total["extra_strict"]
    missing = total["missing_directed"]
    p = correct / (correct + extra) if correct + extra else 0.0
    r = correct / (correct + missing) if correct + missing else 0.0
    agg_nodes = {}
    n_cases = len(node_rows)
    for k in ("n_nodes", "junk_or_unlabeled_nodes", "mixed_nodes",
              "clean_nodes", "false_merge_nodes", "false_split_cids",
              "cid_coverage", "n_gold_cids"):
        agg_nodes[k] = sum(v.get(k, 0) for v in node_rows.values())
    for k in ("cluster_recall", "node_precision", "conll_f", "b3_f",
              "muc_f", "ceaf_e_f"):
        vals = []
        for v in node_rows.values():
            if k == "b3_f":
                vals.append(v["b3"][2])
            elif k == "muc_f":
                vals.append(v["muc"][2])
            elif k == "ceaf_e_f":
                vals.append(v["ceaf_e"][2])
            else:
                vals.append(v.get(k, 0))
        agg_nodes[k] = round(sum(vals) / max(1, n_cases), 4)
    return {
        "suite": suite, "arm": arm, "cases": n_cases,
        "P": round(p, 3), "R": round(r, 3),
        "F1": round(2 * p * r / (p + r), 3) if p + r else 0.0,
        "correct": correct, "extra": extra, "missing": missing,
        "typed": total.get("typed_unique", 0),
        "exact_graphs": sum(v["counts"]["exact_graph"]
                            for v in per_case.values()),
        "exact_typed": sum(v["counts"]["exact_typed_graph"]
                           for v in per_case.values()),
        "contaminated": total.get("contaminated_endpoint_edges", 0),
        "reverse": total.get("reverse_edges", 0),
        "duplicate": total.get("duplicate_supported_edges", 0),
        "nodes": agg_nodes, "per_case": per_case,
        "node_per_case": node_rows}


# ------------------------------------------------------ oracle decomposition
def oracle_decomp(arm: str = "v10", suite: str = "f5") -> dict:
    """Deterministic ceilings from the saved v10 output + gold.

    - node_ceiling_R: gold edges with both endpoint cids covered by
      CLEAN labeled nodes (achievable recall with perfect relation stack
      on these nodes).
    - proposal_R: gold edges whose endpoint node pair reached the
      relation stack (stage certificate/judge/licensed in the pair log,
      i.e. not cut at the ce_band stage).
    - licensing_attr: correct / node_ceiling (relation-stack efficiency
      on achievable edges).
    """
    gold = load_f5(suite)
    d = ARMDIR / f"{suite}_{arm}"
    out = {}
    tot_gold = tot_node = tot_prop = 0
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        nodes = {n["node_id"]: n for n in data.get("nodes", [])}
        clean_labels = {}
        for nid, n in nodes.items():
            lab = node_label(case, n)
            if lab and lab not in ("MIXED", "NON_EVENT"):
                clean_labels[nid] = lab
        label_to_nodes = defaultdict(set)
        for nid, lab in clean_labels.items():
            label_to_nodes[lab].add(nid)
        gold_edges = [(e["from_cid"], e["to_cid"])
                      for e in case["normative_edges"]]
        tot_gold += len(gold_edges)
        node_ok = sum(1 for a, b in gold_edges
                      if a in label_to_nodes and b in label_to_nodes)
        tot_node += node_ok
        # pair log: which (u,v) pairs reached certificate+ stage
        reached = set()
        for rec in data.get("pairs", []):
            if rec.get("stage") in ("certificate", "judge", "licensed"):
                reached.add((rec.get("u"), rec.get("v")))
                reached.add((rec.get("v"), rec.get("u")))
        prop_ok = sum(1 for a, b in gold_edges
                      if any(x in label_to_nodes.get(a, set()) and
                             y in label_to_nodes.get(b, set())
                             for x, y in reached))
        tot_prop += prop_ok
        out[cid] = {"gold": len(gold_edges), "node_ceiling": node_ok,
                    "proposal_ceiling": prop_ok}
    correct = None
    # correct from the arm's own scoring
    sc = score_arm(arm, suite)
    correct = sc.get("correct", 0)
    out["_aggregate"] = {
        "gold_edges": tot_gold,
        "node_ceiling": tot_node,
        "node_ceiling_R": round(tot_node / max(1, tot_gold), 3),
        "proposal_ceiling": tot_prop,
        "proposal_ceiling_R": round(tot_prop / max(1, tot_gold), 3),
        "actual_correct": correct,
        "licensing_efficiency": round(correct / max(1, tot_prop), 3)}
    return out


# ------------------------------------------------------ rename agreement
def rename_agreement() -> dict:
    """Behavioral invariance of v10/v11 across the 6 renamed cases.

    Per case (renamed id = original + '_ren'):
      - n_nodes equal?
      - induced cluster partition over gold cids equal?
      - edge set (gold-cid pairs after labeling) equal?
    Structural identity = all three."""
    gold_o = load_f5("f5")
    gold_r = load_f5("f5r")
    out = {}
    for arm in ARMS_F5R:
        rows = []
        for rcid, rcase in gold_r.items():
            ocid = rcid[:-4] if rcid.endswith("_ren") else rcid
            ocase = gold_o.get(ocid)
            if ocase is None:
                continue
            fo = ARMDIR / f"f5_{arm}" / f"{ocid}.json"
            fr = ARMDIR / f"f5r_{arm}" / f"{rcid}.json"
            if not (fo.exists() and fr.exists()):
                continue
            do = json.loads(fo.read_text(encoding="utf-8"))
            dr = json.loads(fr.read_text(encoding="utf-8"))

            def cluster_partition(data, case):
                parts = []
                for n in data.get("nodes", []):
                    lab = node_label(case, n)
                    if lab and lab not in ("MIXED", "NON_EVENT"):
                        parts.append(frozenset([lab]))
                    else:
                        parts.append(frozenset([f"__{n['node_id']}"]))
                return sorted(parts, key=repr)

            def edge_set(data, case):
                nodes = {n["node_id"]: n for n in data.get("nodes", [])}
                es = set()
                for e in data.get("edges", []):
                    la = node_label(case, nodes.get(e["u"], {}))
                    lb = node_label(case, nodes.get(e["v"], {}))
                    d = e.get("direction", "A_TO_B")
                    if d == "B_TO_A":
                        la, lb = lb, la
                    if la and lb and la not in ("MIXED", "NON_EVENT") \
                            and lb not in ("MIXED", "NON_EVENT"):
                        es.add((la, lb, e.get("relation")))
                return es

            n_eq = len(do.get("nodes", [])) == len(dr.get("nodes", []))
            cl_eq = cluster_partition(do, ocase) == \
                cluster_partition(dr, rcase)
            eo, er = edge_set(do, ocase), edge_set(dr, rcase)
            e_eq = eo == er
            rows.append({"case": ocid, "n_nodes_o": len(do.get("nodes",
                                                                [])),
                         "n_nodes_r": len(dr.get("nodes", [])),
                         "nodes_equal": n_eq,
                         "clusters_equal": cl_eq,
                         "edges_equal": e_eq,
                         "edges_o": sorted(eo), "edges_r": sorted(er),
                         "structural_identity": n_eq and cl_eq and e_eq})
        agree = sum(1 for r in rows if r["structural_identity"])
        out[arm] = {"per_case": rows,
                    "structural_identity": agree, "of": len(rows)}
        print(f"[rename:{arm}] structural identity {agree}/{len(rows)}",
              flush=True)
    return out


# ------------------------------------------------------ guard replay
def guard_replay(arm: str = "v10", suite: str = "f5") -> dict:
    """Post-hoc guard attribution on saved pair logs (zero LLM).

    For each saved pair-log record with a gate note, count gold vs
    non-gold pairs killed per guard; plus judge-stage losses."""
    gold = load_f5(suite)
    d = ARMDIR / f"{suite}_{arm}"
    agg = Counter()
    per_case = {}
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        nodes = {n["node_id"]: n for n in data.get("nodes", [])}
        gold_pairs = set()
        for e in case["normative_edges"]:
            gold_pairs.add((e["from_cid"], e["to_cid"]))
            gold_pairs.add((e["to_cid"], e["from_cid"]))
        cc = Counter()
        for rec in data.get("pairs", []):
            if rec.get("stage") == "licensed":
                continue
            na, nb = nodes.get(rec.get("u"), {}), nodes.get(rec.get("v"),
                                                            {})
            la, lb = node_label(case, na), node_label(case, nb)
            is_gold = (la, lb) in gold_pairs or (lb, la) in gold_pairs
            note = rec.get("judge_note") or rec.get("gate") or \
                rec.get("stage") or "unknown"
            key = ("gold_killed" if is_gold else "extra_killed", note)
            cc[key] += 1
        per_case[cid] = {f"{k[0]}:{k[1]}": v for k, v in cc.items()}
        agg.update(cc)
    out = {"aggregate": {f"{k[0]}:{k[1]}": v for k, v in agg.items()},
           "per_case": per_case}
    return out


# ------------------------------------------------------ failure taxonomy
TAXONOMY = [
    "node_junk_survivor",            # junk/non-event node survives
    "node_false_merge",              # node mixes >=2 gold cids
    "node_false_split",              # gold cid split across nodes
    "node_missing_mention",          # gold cid not covered at all
    "edge_extra_judge_overlicensing",  # judge YES on non-gold pair
    "edge_extra_multiclause_bridge",   # endpoints bridged via 3rd clause
    "edge_extra_object_containment",   # containment mis-binding
    "edge_extra_dup_consolidation",    # duplicate edge survived
    "edge_missing_node_absent",        # endpoint node missing
    "edge_missing_not_proposed",       # pair never reached the stack
    "edge_missing_certificate",        # certificate failed/unsupported
    "edge_missing_judge_no",           # judge rejected a gold pair
    "edge_missing_gate_kill",          # a guard killed a gold pair
    "edge_wrong_direction",            # reverse edge
]


def failure_taxonomy(arm: str = "v10", suite: str = "f5",
                     oracle: dict | None = None) -> dict:
    """Classify every error into the taxonomy (deterministic)."""
    gold = load_f5(suite)
    d = ARMDIR / f"{suite}_{arm}"
    if oracle is None:
        oracle = oracle_decomp(arm, suite)
    tax = Counter()
    examples = defaultdict(list)
    per_case = {}
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        sc = score_case(case, data)
        cc = Counter()
        # node-level failures
        nodes = data.get("nodes", [])
        nm = node_cluster_metrics(case, nodes)
        cc["node_junk_survivor"] = nm["junk_or_unlabeled_nodes"]
        cc["node_false_merge"] = nm["false_merge_nodes"]
        cc["node_false_split"] = nm["false_split_cids"]
        cc["node_missing_mention"] = nm["n_gold_cids"] - \
            nm["cid_coverage"]
        # edge-level failures
        nodes_by_id = {n["node_id"]: n for n in nodes}
        gold_map = {(e["from_cid"], e["to_cid"]): set(e["acceptable"])
                    for e in case["normative_edges"]}
        clean_labels = {nid: node_label(case, n)
                        for nid, n in nodes_by_id.items()}
        for err in sc["errors"]:
            reason = err.get("reason")
            if reason == "contaminated_or_junk_endpoint":
                cc["edge_extra_judge_overlicensing"] += 1
                examples["edge_extra_judge_overlicensing"].append(
                    f"{cid}:{err.get('from')}->{err.get('to')}")
            elif reason == "wrong_direction":
                cc["edge_wrong_direction"] += 1
            elif reason in ("unsupported_edge", "duplicate_gold_edge"):
                # inspect the pair log for the gate/judge note
                cc["edge_extra_judge_overlicensing"] += 1
                examples["edge_extra_judge_overlicensing"].append(
                    f"{cid}:{err.get('from')}->{err.get('to')}:{reason}")
            elif reason == "missing_node":
                cc["edge_missing_node_absent"] += 1
        # missing edges: attribute via oracle decomp pieces
        od = oracle.get(cid, {})
        node_ceiling = od.get("node_ceiling", 0)
        prop_ceiling = od.get("proposal_ceiling", 0)
        correct = sc["counts"].get("correct_unique", 0)
        cc["edge_missing_node_absent"] += len(sc["missing"]) - node_ceiling
        cc["edge_missing_not_proposed"] += max(0, node_ceiling -
                                               prop_ceiling)
        cc["edge_missing_certificate_or_judge_or_gate"] = max(
            0, prop_ceiling - correct)
        per_case[cid] = dict(cc)
        tax.update(cc)
    return {"taxonomy": dict(tax), "per_case": per_case,
            "examples": {k: v[:5] for k, v in examples.items()},
            "classes": TAXONOMY}


def main() -> None:
    out = {}
    # L1/L2/L3 for all arms
    for arm in ARMS_F5:
        out[f"f5_{arm}"] = score_arm(arm, "f5")
        s = out[f"f5_{arm}"]
        if not s.get("missing"):
            print(f"[score] f5 {arm}: P={s['P']} R={s['R']} "
                  f"correct={s['correct']} extra={s['extra']} "
                  f"missing={s['missing']} "
                  f"exact={s['exact_graphs']}/{s['cases']} "
                  f"conll={s['nodes'].get('conll_f')} "
                  f"FM={s['nodes'].get('false_merge_nodes')}",
                  flush=True)
    for arm in ARMS_F5R:
        out[f"f5r_{arm}"] = score_arm(arm, "f5r")
        s = out[f"f5r_{arm}"]
        if not s.get("missing"):
            print(f"[score] f5r {arm}: P={s['P']} R={s['R']} "
                  f"exact={s['exact_graphs']}/{s['cases']}", flush=True)
    (OUTD / "f5_score.json").write_text(json.dumps(out, indent=1))

    # oracle decomposition on v10 (+ v11 for comparison)
    od = {"v10": oracle_decomp("v10", "f5"),
          "v11": oracle_decomp("v11", "f5")}
    print("[oracle] v10:", od["v10"]["_aggregate"], flush=True)
    print("[oracle] v11:", od["v11"]["_aggregate"], flush=True)
    (OUTD / "f5_oracle_decomp.json").write_text(json.dumps(od, indent=1))

    # rename agreement
    ra = rename_agreement()
    (OUTD / "f5_rename_agreement.json").write_text(json.dumps(ra,
                                                              indent=1))

    # guard replay on F5 v10
    gr = guard_replay("v10", "f5")
    print("[guards] v10 f5:", gr["aggregate"], flush=True)
    (OUTD / "f5_guard_replay.json").write_text(json.dumps(gr, indent=1))

    # failure taxonomy v10 + v11
    for arm in ("v10", "v11"):
        tx = failure_taxonomy(arm, "f5", oracle=od[arm])
        print(f"[taxonomy] {arm}:", tx["taxonomy"], flush=True)
        (OUTD / f"f5_taxonomy_{arm}.json").write_text(json.dumps(tx,
                                                                 indent=1))

    print("saved ->", OUTD, flush=True)


if __name__ == "__main__":
    main()
