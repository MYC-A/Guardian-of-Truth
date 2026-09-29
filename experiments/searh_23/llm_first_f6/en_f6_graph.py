"""F6 graph-level scorer — w1_score.score_case semantics (strict) over
the F6 gold edges, plus L1/L2 node metrics with overlap-aware gold
labeling (raw-LLM boundaries differ from gold spans; exact-span
labeling would systematically undercount coverage).

Arms scored (outputs/stack/):
  f6_oracle1            gold nodes + frozen stack         (Oracle 1)
  f6_oracle2_mistralA   raw mentions + GOLD identity      (Oracle 2)
  f6_oracle3_mistralA   raw mistral-A mentions + stack    (Oracle 3)
  f6_v10                NLP-first chain + stack           (baseline)

L1: node precision (clean-labeled fraction), junk, false_split,
    cluster_recall (gold cid covered by >=1 clean node).
L2: B3/MUC/CEAF-E/CoNLL over node clusters vs gold clusters (per-case
    macro average, en_common-compatible greedy CEAF).
L3: edge P/R/F1 + exact graphs (strict W1 semantics).

Run: python3 en_f6_graph.py   (writes outputs/score/graph.json)
"""
from __future__ import annotations

import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
W1 = HERE.parent / "step1_working_v1"
IE = HERE.parent / "event_ie_frontends_v1"
sys.path[:0] = [str(W1), str(IE)]

from w1_score import score_case  # noqa: E402

STACK = HERE / "outputs" / "stack"
OUT = HERE / "outputs" / "score"
OUT.mkdir(parents=True, exist_ok=True)

ARMS = ["f6_oracle1", "f6_oracle2_mistralA", "f6_oracle3_mistralA",
        "f6_v10", "f6_hyb_mistralA", "f6_rawsan"]


def load_gold(suite: str = "f6") -> dict[str, dict]:
    fname = "level_f6_cases.json" if suite == "f6" else \
        "level_f6r_cases.json"
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / fname).read_text(encoding="utf-8"))}


# ---------------------------------------------------- overlap-aware label
def label_overlap(case: dict, node: dict):
    """Gold cid whose EVENT-like mention has the largest overlap with the
    node span; MIXED if several cids tie within the node; None if no
    event overlap (junk)."""
    best = defaultdict(int)
    for m in case["mentions"]:
        if not m.get("cid") or m["type"] in ("ENTITY", "ARTIFACT"):
            continue
        inter = max(0, min(node.get("end", node["start"] + len(node["span"])),
                           m["end"]) - max(node.get("start", 10**9), m["start"]))
        if inter > 0:
            best[m["cid"]] += inter
    if not best:
        # entity-only overlap?
        ent = any(max(0, min(node.get("end", 0), m["end"]) -
                      max(node.get("start", 10**9), m["start"])) > 0
                  for m in case["mentions"]
                  if m["type"] in ("ENTITY", "ARTIFACT"))
        return "NON_EVENT" if ent else None
    top = max(best.values())
    winners = [c for c, v in best.items() if v == top]
    return winners[0] if len(winners) == 1 else "MIXED"


def node_clusters(nodes: list[dict]) -> list[set]:
    out = []
    for n in nodes:
        labs = {n.get("gold_label")}
        out.append(labs)
    return out


def gold_clusters(case: dict) -> list[set]:
    spans_by_cid: dict[str, set] = defaultdict(set)
    for m in case["mentions"]:
        if m.get("cid"):
            spans_by_cid[m["cid"]].add(m["span"].strip())
    return [set(v) for v in spans_by_cid.values()]


def _b3(pred: list[set], gold: list[set]) -> float:
    if not pred or not gold:
        return 0.0
    p_num = sum(len(cl) for cl in pred)
    r_num = 0.0
    for g in gold:
        for m in g:
            r_num += 1 / len(g)
    p_den = sum(1 for cl in pred for m in cl
                if any(m in g for g in gold))
    p = p_num / p_den if p_den else 0.0
    r_den = sum(1 for g in gold for m in g if any(m in cl for cl in pred))
    r = r_num / r_den if r_den else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def _muc(pred: list[set], gold: list[set]) -> float:
    def partitions(clusters, mentions):
        part = 0
        for cl in clusters:
            part += len(cl) - (1 if cl else 0)
        return part
    if not pred or not gold:
        return 0.0
    num = partitions(gold)
    if num == 0:
        return 1.0 if partitions(pred) == 0 else 0.0
    # pairwise recall
    pw_num = sum(1 for g in gold for a in g for b in g if a < b
                 and any(a in cl and b in cl for cl in pred))
    pw_den = sum(1 for g in gold for a in g for b in g if a < b)
    rec = pw_num / pw_den if pw_den else 1.0
    pw_pn = sum(1 for cl in pred for a in cl for b in cl if a < b)
    prec = 1.0 if pw_pn == 0 else (sum(1 for cl in pred for a in cl
                                       for b in cl if a < b
                                       and any(a in g and b in g
                                               for g in gold)) / pw_pn)
    return 2 * prec * rec / (prec + rec) if prec + rec else 0.0


def _ceaf_entity(pred: list[set], gold: list[set]) -> float:
    import itertools

    def sim(a, b):
        return len(a & b)
    if not pred or not gold:
        return 0.0
    n = min(len(pred), len(gold))
    best = -1.0
    for perm in itertools.permutations(range(len(pred)), n):
        s = sum(sim(pred[perm[i]], gold[i]) for i in range(n))
        best = max(best, s)
    total = sum(len(g) for g in gold)
    r = best / total if total else 0.0
    total_p = sum(len(p) for p in pred)
    p = best / total_p if total_p else 0.0
    return 2 * p * r / (p + r) if p + r else 0.0


def node_metrics(case: dict, nodes: list[dict]) -> dict:
    labs = []
    for n in nodes:
        lab = label_overlap(case, n)
        n["gold_label"] = lab
        labs.append(lab)
    clean = [l for l in labs if l and l not in ("MIXED", "NON_EVENT")]
    junk = sum(1 for l in labs if l in (None, "NON_EVENT"))
    mixed = sum(1 for l in labs if l == "MIXED")
    gold_cids = {m["cid"] for m in case["mentions"] if m.get("cid")}
    covered = {l for l in clean if l in gold_cids}
    # clusters: node sets by gold label over gold mention spans
    pred_cl = [set() for _ in nodes]
    for i, n in enumerate(nodes):
        if labs[i] and labs[i] not in ("MIXED", "NON_EVENT"):
            for m in case["mentions"]:
                if m.get("cid") == labs[i]:
                    inter = max(0, min(n.get("end", 0), m["end"]) -
                                max(n.get("start", 10**9), m["start"]))
                    if inter > 0:
                        pred_cl[i].add(m["span"].strip())
    gcl = gold_clusters(case)
    b3 = _b3([c for c in pred_cl if c], gcl)
    muc = _muc([c for c in pred_cl if c], gcl)
    ceaf = _ceaf_entity([c for c in pred_cl if c], gcl)
    conll = (b3 + muc + ceaf) / 3
    return {"nodes": len(nodes), "clean": len(clean), "junk": junk,
            "mixed": mixed,
            "node_precision": round(len(clean) / len(nodes), 3)
            if nodes else 0.0,
            "cluster_recall": round(len(covered) / len(gold_cids), 3)
            if gold_cids else 0.0,
            "false_merges": _false_merges(case, nodes, labs),
            "b3": round(b3, 3), "muc": round(muc, 3),
            "ceaf_e": round(ceaf, 3), "conll_f": round(conll, 3)}


def _false_merges(case: dict, nodes: list[dict], labs) -> int:
    """Nodes whose single member list contains >1 distinct gold cid via
    overlap, or nodes merged across gold cids (member spans labeling)."""
    fm = 0
    for n in nodes:
        cids = set()
        for m in case["mentions"]:
            if not m.get("cid"):
                continue
            inter = max(0, min(n.get("end", 0), m["end"]) -
                        max(n.get("start", 10**9), m["start"]))
            if inter > len(m["span"]) * 0.5:
                cids.add(m["cid"])
        if len(cids) > 1:
            fm += 1
    return fm


def score_arm(arm_dir: str, suite: str = "f6") -> dict:
    gold = load_gold(suite)
    d = STACK / arm_dir
    if not d.exists():
        return {"missing": True}
    per_case, node_rows = {}, {}
    total = Counter()
    nm_tot = Counter()
    for cid, case in gold.items():
        f = d / f"{cid}.json"
        if not f.exists():
            continue
        data = json.loads(f.read_text(encoding="utf-8"))
        row = score_case(case, data)
        per_case[cid] = row["counts"]
        total.update(row["counts"])
        nm = node_metrics(case, data.get("nodes", []))
        node_rows[cid] = nm
        for k in ("nodes", "clean", "junk", "mixed", "false_merges"):
            nm_tot[k] += nm[k]
        nm_tot["b3s"] += nm["b3"]
        nm_tot["mucs"] += nm["muc"]
        nm_tot["ceafs"] += nm["ceaf_e"]
        nm_tot["conlls"] += nm["conll_f"]
        nm_tot["gold_cids"] += len({m["cid"] for m in case["mentions"]
                                    if m.get("cid")})
        nm_tot["covered"] += round(nm["cluster_recall"] *
                                   len({m["cid"] for m in case["mentions"]
                                        if m.get("cid")}))
    n_cases = len(node_rows)
    correct = total["correct_unique"]
    extra = total["extra_strict"]
    missing = total["missing_directed"]
    p = correct / (correct + extra) if correct + extra else 0.0
    r = correct / (correct + missing) if correct + missing else 0.0
    f1 = 2 * p * r / (p + r) if p + r else 0.0
    return {"n_cases": n_cases,
            "edges": {"gold": total["gold_edges"], "correct": correct,
                      "extra": extra, "missing": missing,
                      "p": round(p, 3), "r": round(r, 3),
                      "f1": round(f1, 3),
                      "exact_graphs": total["exact_graph"],
                      "exact_typed": total["exact_typed_graph"],
                      "duplicate": total.get("duplicate_supported_edges", 0),
                      "contaminated": total.get(
                          "contaminated_endpoint_edges", 0)},
            "nodes": {"total": nm_tot["nodes"], "clean": nm_tot["clean"],
                      "junk": nm_tot["junk"], "mixed": nm_tot["mixed"],
                      "false_merges": nm_tot["false_merges"],
                      "node_precision": round(
                          nm_tot["clean"] / max(1, nm_tot["nodes"]), 3),
                      "cluster_recall": round(
                          nm_tot["covered"] /
                          max(1, nm_tot["gold_cids"]), 3),
                      "b3": round(nm_tot["b3s"] / max(1, n_cases), 3),
                      "muc": round(nm_tot["mucs"] / max(1, n_cases), 3),
                      "ceaf_e": round(nm_tot["ceafs"] / max(1, n_cases), 3),
                      "conll_f": round(nm_tot["conlls"] /
                                       max(1, n_cases), 3)},
            "per_case_edges": per_case, "per_case_nodes": node_rows}


def main() -> None:
    report = {}
    for arm in ARMS:
        rep = score_arm(arm)
        report[arm] = rep
        if "missing" in rep:
            print(arm, "MISSING")
            continue
        e, n = rep["edges"], rep["nodes"]
        print(f"{arm}: P {e['p']} R {e['r']} F1 {e['f1']} "
              f"exact {e['exact_graphs']}/{rep['n_cases']} | "
              f"nodes {n['total']} junk {n['junk']} FM {n['false_merges']} "
              f"cl-recall {n['cluster_recall']} CoNLL {n['conll_f']}",
              flush=True)
    (OUT / "graph.json").write_text(
        json.dumps(report, indent=1, ensure_ascii=False) + "\n",
        encoding="utf-8")
    print("[graph] written", OUT / "graph.json")


if __name__ == "__main__":
    main()
