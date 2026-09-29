"""Event Normalization Generalization phase — shared utilities.

Reuses: W1 outputs (cached nodes/edges/pair logs), frozen F-suite gold,
EC-phase scoring machinery concepts. All node-level analyses here are
DETERMINISTIC replays (zero LLM) over saved outputs, per directive §19.
"""
from __future__ import annotations

import json
import os
import re
from collections import Counter, defaultdict
from pathlib import Path

HERE = Path(__file__).parent
IE = HERE.parent / "event_ie_frontends_v1"
W1 = HERE.parent / "step1_working_v1"
OUT = HERE / "outputs"

SUITES = {
    "main": "level_f_cases.json",
    "f2": "level_f2_cases.json",
    "f3": "level_f3_cases.json",
    "f4": "level_f4_cases.json",
}


def load_gold(suite: str) -> dict[str, dict]:
    return {c["case_id"]: c for c in json.loads(
        (IE / "frozen" / SUITES[suite]).read_text(encoding="utf-8"))}


def w1_output(suite: str, arm_dir: str = "W1_DOWN10_LLM_SG") -> Path:
    """Saved W1 pipeline output dir for a suite.

    W1 saved per-suite outputs in the SAME directory (files overwritten per
    LF_SUITE run); the final state of W1_DOWN10_LLM_SG on disk = F4 run (the
    last one). Historical suite outputs live in the W1 score jsons and in
    per-suite logs; for replay we re-derive from the git history when needed.
    """
    return W1 / "outputs" / arm_dir


# ---------------------------------------------------------------- gold labels
def mention_labels(case: dict) -> dict[str, list[str]]:
    """span(stripped) -> [gold labels] (cid or NON_EVENT for cid=None)."""
    by_span: dict[str, list[str]] = defaultdict(list)
    for m in case["mentions"]:
        by_span.setdefault(m["span"].strip(), []).append(
            m.get("cid") or "NON_EVENT")
    return by_span


def node_label(case: dict, node: dict) -> str | None:
    """Strict node label: single gold cid, MIXED, NON_EVENT, or None."""
    by_span = mention_labels(case)
    labels, matched = set(), False
    for span in node.get("member_spans", []) or [node.get("span", "")]:
        for lab in by_span.get((span or "").strip(), []):
            matched = True
            labels.add(lab)
    if not matched:
        return None
    if len(labels) == 1:
        return next(iter(labels))
    return "MIXED"


def gold_clusters(case: dict) -> dict[str, list[str]]:
    """gold cid -> gold mention spans."""
    cl: dict[str, list[str]] = defaultdict(list)
    for m in case["mentions"]:
        if m.get("cid"):
            cl[m["cid"]].append(m["span"].strip())
    return cl


# ---------------------------------------------------------------- cluster M/R
def node_cluster_metrics(case: dict, nodes: list[dict]) -> dict:
    """Mention/cluster quality of predicted nodes vs gold.

    - cid coverage (cluster recall): gold cid matched by >=1 clean node label.
    - node precision: clean nodes (single non-junk label) / all nodes.
    - false merge: node whose member labels span >=2 distinct gold cids.
    - false split: gold cid covered by >=2 distinct clean nodes.
    """
    gold_cids = set(gold_clusters(case))
    labels = [node_label(case, n) for n in nodes]
    clean = {i: lab for i, lab in enumerate(labels)
             if lab and lab not in ("MIXED", "NON_EVENT")}
    covered = set(clean.values())
    per_cid: dict[str, set[int]] = defaultdict(set)
    for i, lab in clean.items():
        per_cid[lab].add(i)
    mixed = sum(1 for lab in labels if lab == "MIXED")
    junk = sum(1 for lab in labels if lab in (None, "NON_EVENT"))
    return {
        "n_nodes": len(nodes),
        "n_gold_cids": len(gold_cids),
        "cid_coverage": len(covered & gold_cids),
        "cluster_recall": round(len(covered & gold_cids) /
                                max(1, len(gold_cids)), 3),
        "clean_nodes": len(clean),
        "node_precision": round(len(clean) / max(1, len(nodes)), 3),
        "mixed_nodes": mixed,
        "junk_or_unlabeled_nodes": junk,
        "false_merge_nodes": mixed,
        "false_split_cids": sum(1 for c in gold_cids
                                if len(per_cid.get(c, ())) >= 2),
    }


# ------------------------------------------------------- B3/MUC/CEAF metrics
def _b3(pred_clusters: list[set], gold_clusters: list[set]) -> float:
    """B-cubed precision/recall/F over mention→cluster assignment."""
    prec_num = rec_num = 0.0
    n_pred = sum(len(c) for c in pred_clusters) or 1
    n_gold = sum(len(c) for c in gold_clusters) or 1
    for pc in pred_clusters:
        for m in pc:
            gc = next((g for g in gold_clusters if m in g), None)
            if gc is None:
                continue
            inter = len(pc & gc)
            prec_num += inter / len(pc)
    for gc in gold_clusters:
        for m in gc:
            pc = next((p for p in pred_clusters if m in p), None)
            if pc is None:
                continue
            inter = len(pc & gc)
            rec_num += inter / len(gc)
    p = prec_num / n_pred
    r = rec_num / n_gold
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _muc(pred_clusters: list[set], gold_clusters: list[set]) -> tuple:
    """MUC precision/recall/F via link counting (partition of the same
    mention set is NOT assumed; mentions unmatched on one side count as
    singleton-partition members)."""
    def links(clusters: list[set]) -> int:
        return sum(len(c) - 1 for c in clusters if len(c) >= 1)
    # link recall: (# common links in pred+gold partition) etc. — we use the
    # standard formulation restricted to shared mentions
    shared = set().union(*pred_clusters) & set().union(*gold_clusters) \
        if pred_clusters and gold_clusters else set()
    p_shared = [c & shared for c in pred_clusters if c & shared]
    g_shared = [c & shared for c in gold_clusters if c & shared]
    ml_p = links(p_shared)
    ml_g = links(g_shared)
    # missing links = gold links not in pred; new links = pred links not in
    # gold; compute by pairing
    def pairwise(c): return {(a, b) for cl in c for i, a in enumerate(sorted(cl))
                             for b in sorted(cl)[i + 1:]}
    pw_p, pw_g = pairwise(p_shared), pairwise(g_shared)
    missing = len(pw_g - pw_p)
    new = len(pw_p - pw_g)
    r = (ml_g - missing) / ml_g if ml_g else 1.0
    p = (ml_p - new) / ml_p if ml_p else 1.0
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def _ceaf_entity(pred_clusters: list[set], gold_clusters: list[set]) -> tuple:
    """CEAF-E with one-to-one greedy alignment (adequate for small sets)."""
    import itertools

    def score(a: set, b: set) -> float:
        return len(a & b)
    n = min(len(pred_clusters), len(gold_clusters))
    if n == 0:
        return 1.0, 0.0, 0.0
    best = None
    for perm in itertools.permutations(range(len(gold_clusters)), n):
        s = sum(score(pred_clusters[i], gold_clusters[j])
                for i, j in enumerate(perm[:n]))
        if best is None or s > best[0]:
            best = (s, perm)
    s, perm = best
    aligned = sum(1 for i, j in enumerate(perm)
                  if score(pred_clusters[i], gold_clusters[j]) > 0)
    total_pred = sum(len(c) for c in pred_clusters) or 1
    total_gold = sum(len(c) for c in gold_clusters) or 1
    p = s / total_pred
    r = s / total_gold
    f = 2 * p * r / (p + r) if p + r else 0.0
    return p, r, f


def cluster_scores(pred: list[set], gold: list[set]) -> dict:
    """CoNLL aggregate (MUC+B3+CEAF average F) + false-merge extras."""
    b3 = _b3(pred, gold)
    muc = _muc(pred, gold)
    ceaf = _ceaf_entity(pred, gold)
    conll = round((b3[2] + muc[2] + ceaf[2]) / 3, 4)
    return {"b3": [round(x, 4) for x in b3],
            "muc": [round(x, 4) for x in muc],
            "ceaf_e": [round(x, 4) for x in ceaf],
            "conll_f": conll}


def node_clusters_as_sets(case: dict, nodes: list[dict]) -> list[set]:
    """Predicted clusters over GOLD mention indices (mentions matched by
    stripped span equality; unmatched predicted forms ignored)."""
    idx = {m["span"].strip(): i for i, m in enumerate(case["mentions"])}
    clusters: dict[int, set] = {}
    for ni, n in enumerate(nodes):
        members = set()
        for span in n.get("member_spans", []) or [n.get("span", "")]:
            i = idx.get((span or "").strip())
            if i is not None:
                members.add(i)
        if members:
            clusters[ni] = members
    # gold-mention indices not covered by any node become their own
    # singletons are NOT added (cluster metrics computed over shared set)
    return list(clusters.values())


def gold_clusters_as_sets(case: dict) -> list[set]:
    by_cid: dict[str, set] = defaultdict(set)
    for i, m in enumerate(case["mentions"]):
        if m.get("cid"):
            by_cid[m["cid"]].add(i)
    return list(by_cid.values())
